"""
采集进程生命周期管理器。

Windows 下 uvicorn 使用 spawn worker，不宜再嵌套 multiprocessing；
统一用 subprocess.Popen 拉起独立 Python 进程。
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

    @classmethod
    def instance(cls) -> 'CollectorProcessManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _is_alive(self, proc: Popen | None) -> bool:
        return proc is not None and proc.poll() is None

    def _spawn(self, collector_type: str, device_id: str, config: dict[str, Any]) -> ProcessEntry:
        env = os.environ.copy()
        env.setdefault('APP_ENV', 'sqlite')
        config_json = json.dumps(config, ensure_ascii=False)
        proc = subprocess.Popen(
            [sys.executable, str(_RUNNER), collector_type, device_id, config_json],
            cwd=str(_BACKEND_ROOT),
            env=env,
        )
        entry = ProcessEntry(device_id=device_id, collector_type=collector_type, process=proc, config=config)
        self._registry[device_id] = entry
        return entry

    def _push_ctrl(self, device_id: str, msg: dict[str, Any]) -> None:
        from module_payload.collectors.redis_sync import create_sync_redis

        r = create_sync_redis()
        r.lpush(rk.ctrl_queue_key(device_id), json.dumps(msg, ensure_ascii=False))

    def open_can_channel(self, vendor: int, dev_index: int, can_index: int, config: dict[str, Any]) -> str:
        card_id = rk.can_card_id(vendor, dev_index)
        channel_id = rk.can_channel_id(vendor, dev_index, can_index)
        ch_cfg = {
            'vendor': vendor,
            'dev_index': dev_index,
            'can_index': can_index,
            **config,
        }
        entry = self._registry.get(card_id)
        if entry is None or not self._is_alive(entry.process):
            cfg = {'vendor': vendor, 'dev_index': dev_index, 'channels': [ch_cfg]}
            entry = self._spawn('can', card_id, cfg)
        else:
            self._push_ctrl(card_id, {'op': 'open_channel', 'can_index': can_index, 'config': ch_cfg})
        entry.opened_channels.add(can_index)
        return channel_id

    def close_can_channel(self, vendor: int, dev_index: int, can_index: int) -> None:
        card_id = rk.can_card_id(vendor, dev_index)
        entry = self._registry.get(card_id)
        if not entry:
            return
        self._push_ctrl(card_id, {'op': 'close_channel', 'can_index': can_index})
        entry.opened_channels.discard(can_index)
        if not entry.opened_channels:
            self.stop(card_id)

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
        if self._is_alive(entry.process):
            self._push_ctrl(device_id, {'op': 'stop'})
            try:
                entry.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                entry.process.terminate()
                try:
                    entry.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    entry.process.kill()

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
                }
            )
        return result

    def shutdown_all(self) -> None:
        for device_id in list(self._registry.keys()):
            self.stop(device_id)
