"""
采集进程生命周期管理器。

Windows 下 uvicorn 使用 spawn worker，不宜再嵌套 multiprocessing；
统一用 subprocess.Popen 拉起独立 Python 进程。

主进程退出时通过 Job Object / atexit / 信号尽量带走子进程（见 process_guard）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import Popen
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collectors import process_guard

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_RUNNER = _BACKEND_ROOT / 'module_payload' / 'collectors' / 'runner.py'


@dataclass
class ProcessEntry:
    device_id: str
    collector_type: str
    process: Popen | None = None
    opened_channels: set[int] = field(default_factory=set)
    config: dict[str, Any] = field(default_factory=dict)


class CollectorProcessManager:
    _instance: 'CollectorProcessManager | None' = None

    def __init__(self) -> None:
        self._registry: dict[str, ProcessEntry] = {}
        process_guard.install_shutdown_hooks(self.shutdown_all)

    @classmethod
    def instance(cls) -> 'CollectorProcessManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _is_alive(self, proc: Popen | None) -> bool:
        return proc is not None and proc.poll() is None

    def _spawn(self, collector_type: str, device_id: str, config: dict[str, Any]) -> ProcessEntry:
        env = os.environ.copy()
        # 与主进程一致；切勿默认 sqlite（会加载 .env.sqlite → 本地 Redis，主进程等不到 status）
        env['APP_ENV'] = os.environ.get('APP_ENV') or 'dev'
        config_json = json.dumps(config, ensure_ascii=False)
        popen_kwargs: dict[str, Any] = {
            'args': [sys.executable, str(_RUNNER), collector_type, device_id, config_json],
            'cwd': str(_BACKEND_ROOT),
            'env': env,
        }
        if sys.platform != 'win32':
            popen_kwargs['preexec_fn'] = process_guard.unix_child_preexec
        proc = subprocess.Popen(**popen_kwargs)
        process_guard.assign_to_kill_job(proc)
        entry = ProcessEntry(device_id=device_id, collector_type=collector_type, process=proc, config=config)
        self._registry[device_id] = entry
        return entry

    def _push_ctrl(self, device_id: str, msg: dict[str, Any]) -> None:
        from module_payload.collectors.redis_sync import create_sync_redis

        r = create_sync_redis()
        try:
            r.lpush(rk.ctrl_queue_key(device_id), json.dumps(msg, ensure_ascii=False))
        finally:
            r.close()

    def open_can_channel(self, vendor: int, dev_index: int, can_index: int, config: dict[str, Any]) -> str:
        card_id = rk.can_card_id(vendor, dev_index)
        channel_id = rk.can_channel_id(vendor, dev_index, can_index)
        ch_cfg = {
            'vendor': vendor,
            'dev_index': dev_index,
            'can_index': can_index,
            **config,
        }
        # 清掉上次残留状态，避免误判 / 干扰本次等待
        self._clear_channel_status(channel_id)
        entry = self._registry.get(card_id)
        if entry is None or not self._is_alive(entry.process):
            cfg = {'vendor': vendor, 'dev_index': dev_index, 'channels': [ch_cfg]}
            entry = self._spawn('can', card_id, cfg)
            ok, err = self._wait_channel_ready(channel_id, entry.process, timeout_s=15.0)
            if not ok:
                self.stop(card_id)
                raise RuntimeError(err or 'CAN 通道打开失败，请检查设备是否接入')
        else:
            self._push_ctrl(card_id, {'op': 'open_channel', 'can_index': can_index, 'config': ch_cfg})
            ok, err = self._wait_channel_ready(channel_id, entry.process, timeout_s=10.0)
            if not ok:
                raise RuntimeError(err or f'CAN{can_index} 打开失败')
        entry.opened_channels.add(can_index)
        return channel_id

    def _clear_channel_status(self, channel_id: str) -> None:
        from module_payload.collectors.redis_sync import create_sync_redis

        r = create_sync_redis()
        try:
            r.delete(rk.status_key(channel_id))
        finally:
            r.close()

    def _wait_channel_ready(
        self, channel_id: str, proc: Popen | None = None, timeout_s: float = 15.0
    ) -> tuple[bool, str]:
        import time

        from module_payload.collectors.redis_sync import create_sync_redis, loads_json

        r = create_sync_redis()
        key = rk.status_key(channel_id)
        deadline = time.time() + timeout_s
        last_msg = ''
        try:
            while time.time() < deadline:
                if proc is not None and proc.poll() is not None:
                    return False, last_msg or 'CAN 采集进程已退出，请检查设备驱动或端口占用'
                raw = r.get(key)
                if raw:
                    data = loads_json(raw) or {}
                    state = data.get('state')
                    last_msg = data.get('message') or ''
                    if state == 'running' and data.get('connected'):
                        return True, ''
                    if state == 'error':
                        return False, last_msg or 'CAN 通道打开失败'
                time.sleep(0.05)
            return False, last_msg or 'CAN 通道打开超时，请检查设备是否接入'
        finally:
            r.close()

    def close_can_channel(self, vendor: int, dev_index: int, can_index: int) -> None:
        card_id = rk.can_card_id(vendor, dev_index)
        entry = self._registry.get(card_id)
        if not entry:
            return
        self._push_ctrl(card_id, {'op': 'close_channel', 'can_index': can_index})
        entry.opened_channels.discard(can_index)
        # 末通道关闭后保留采集进程，下次打开走 ctrl 复用，避免 3~4s 冷启动
        # 进程在 app shutdown / shutdown_all 时统一回收

    def start_serial(self, port: str, config: dict[str, Any]) -> str:
        device_id = rk.serial_id(port)
        if device_id in self._registry:
            self.stop(device_id)
        cfg = {'port': port, **config}
        self._spawn('serial', device_id, cfg)
        return device_id

    def stop(self, device_id: str) -> None:
        entry = self._registry.pop(device_id, None)
        if not entry:
            return
        if not self._is_alive(entry.process):
            return
        # 先礼后兵：短等优雅退出，超时立刻 terminate，避免关闭卡 2~3 秒
        self._push_ctrl(device_id, {'op': 'stop'})
        try:
            entry.process.wait(timeout=0.35)
            return
        except subprocess.TimeoutExpired:
            pass
        entry.process.terminate()
        try:
            entry.process.wait(timeout=0.4)
        except subprocess.TimeoutExpired:
            entry.process.kill()
            try:
                entry.process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass

    def list_opened(self) -> list[dict[str, Any]]:
        result = []
        for device_id, entry in self._registry.items():
            alive = self._is_alive(entry.process)
            result.append(
                {
                    'deviceId': device_id,
                    'type': entry.collector_type,
                    'alive': alive,
                    'channels': sorted(entry.opened_channels),
                    'config': dict(entry.config),
                }
            )
        return result

    def shutdown_all(self) -> None:
        for device_id in list(self._registry.keys()):
            self.stop(device_id)
