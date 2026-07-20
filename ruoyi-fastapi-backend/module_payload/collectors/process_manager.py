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
        import time

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
        err_reuse = ''

        # 进程仍在则先尝试复用（勿用心跳误杀：open_can 阻塞期间本来就没有心跳）
        if entry is not None and self._is_alive(entry.process):
            self._push_ctrl(card_id, {'op': 'open_channel', 'can_index': can_index, 'config': ch_cfg})
            ok, err = self._wait_channel_ready(channel_id, entry.process, timeout_s=10.0)
            if ok:
                entry.opened_channels.add(can_index)
                return channel_id
            # 复用失败 → 杀掉后冷启动；稍等驱动释放，避免立刻 open 失败退出
            err_reuse = err
            self.stop(card_id)
            time.sleep(0.5)
        elif entry is not None:
            self.stop(card_id)
            time.sleep(0.3)

        # 冷启动前清掉卡级残留 stop/status，防止新进程秒退
        self._clear_device_ipc(card_id)
        self._clear_channel_status(channel_id)
        cfg = {'vendor': vendor, 'dev_index': dev_index, 'channels': [ch_cfg]}
        entry = self._spawn('can', card_id, cfg)
        ok, err = self._wait_channel_ready(channel_id, entry.process, timeout_s=15.0)
        if not ok:
            self.stop(card_id)
            raise RuntimeError(err or err_reuse or 'CAN 通道打开失败，请检查设备是否接入')
        entry.opened_channels.add(can_index)
        return channel_id

    def _clear_channel_status(self, channel_id: str) -> None:
        from module_payload.collectors.redis_sync import create_sync_redis

        r = create_sync_redis()
        try:
            r.delete(rk.status_key(channel_id))
        finally:
            r.close()

    def _clear_device_ipc(self, device_id: str) -> None:
        """清理残留 ctrl/cmd/status，避免旧 stop 指令让新进程一启动就退出。"""
        from module_payload.collectors.redis_sync import create_sync_redis

        r = create_sync_redis()
        try:
            r.delete(
                rk.status_key(device_id),
                rk.ctrl_queue_key(device_id),
                rk.cmd_queue_key(device_id),
                rk.heartbeat_key(device_id),
            )
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
        last_state = ''
        try:
            while time.time() < deadline:
                raw = r.get(key)
                if raw:
                    data = loads_json(raw) or {}
                    state = str(data.get('state') or '')
                    last_state = state or last_state
                    last_msg = data.get('message') or last_msg
                    if state == 'running' and data.get('connected'):
                        return True, ''
                    if state == 'error':
                        return False, last_msg or '设备打开失败'
                    # stopped/closed：可能是旧进程收尾，进程仍存活时忽略
                if proc is not None and proc.poll() is not None:
                    raw = r.get(key)
                    if raw:
                        data = loads_json(raw) or {}
                        last_msg = data.get('message') or last_msg
                        last_state = str(data.get('state') or last_state)
                        if data.get('state') == 'error':
                            return False, last_msg or '设备打开失败'
                    if last_state in ('stopped', 'closed') or last_msg in ('已停止', '已关闭'):
                        return False, '采集进程异常退出（可能被残留 stop 指令关闭），请重试'
                    if last_msg:
                        return False, last_msg
                    return False, '采集进程已退出，请检查设备是否被占用或驱动异常'
                time.sleep(0.05)
            if last_msg in ('正在打开 CAN 通道…', '采集进程启动中…') or last_state == 'opening':
                return False, '设备打开超时（仍在打开中），请重试或检查 USB-CAN 是否被占用'
            return False, last_msg or '设备打开超时，请检查设备是否接入'
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
        import time

        device_id = rk.serial_id(port)
        if device_id in self._registry:
            self.stop(device_id)
            time.sleep(0.3)
        self._clear_device_ipc(device_id)
        cfg = {'port': port, **config}
        entry = self._spawn('serial', device_id, cfg)
        ok, err = self._wait_channel_ready(device_id, entry.process, timeout_s=8.0)
        if not ok:
            self.stop(device_id)
            raise RuntimeError(err or '串口打开失败，请检查端口是否被占用')
        return device_id

    def start_net(
        self,
        proto: str,
        local_host: str,
        local_port: int,
        config: dict[str, Any],
    ) -> str:
        import time

        device_id = rk.net_id(proto, local_host, local_port)
        if device_id in self._registry:
            self.stop(device_id)
            time.sleep(0.3)
        self._clear_device_ipc(device_id)
        cfg = {
            'proto': proto,
            'local_host': local_host,
            'local_port': local_port,
            **config,
        }
        entry = self._spawn('net', device_id, cfg)
        ok, err = self._wait_channel_ready(device_id, entry.process, timeout_s=8.0)
        if not ok:
            self.stop(device_id)
            raise RuntimeError(err or '网络连接打开失败')
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
