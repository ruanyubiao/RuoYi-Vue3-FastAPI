"""采集进程统一入口（subprocess / 直接调用）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _bootstrap_env() -> None:
    os.chdir(_BACKEND_ROOT)
    if str(_BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(_BACKEND_ROOT))


def _mark_can_opening(config: dict[str, Any]) -> None:
    """尽早写 opening，让主进程知道子进程已起来（再加载重库）。"""
    try:
        import os

        from module_payload import redis_keys as rk
        from module_payload.collectors.redis_sync import create_sync_redis, dumps_json

        channels = config.get('channels') or []
        if not channels and config.get('can_index') is not None:
            channels = [config]
        r = create_sync_redis()
        try:
            for ch in channels:
                vendor = int(ch.get('vendor', config.get('vendor', 0)))
                dev_index = int(ch.get('dev_index', config.get('dev_index', 0)))
                can_index = int(ch['can_index'])
                channel_id = rk.can_channel_id(vendor, dev_index, can_index)
                r.set(
                    rk.status_key(channel_id),
                    dumps_json(
                        {
                            'deviceId': channel_id,
                            'state': 'opening',
                            'connected': False,
                            'message': '采集进程启动中…',
                            'pid': os.getpid(),
                        }
                    ),
                )
        finally:
            r.close()
    except Exception:
        pass


def run_collector(collector_type: str, device_id: str, config: dict[str, Any]) -> None:
    _bootstrap_env()
    if collector_type == 'can':
        _mark_can_opening(config)
        from module_payload.collectors.can_collector import CanCollector

        CanCollector(device_id, config).run()
    elif collector_type == 'serial':
        from module_payload.collectors.serial_collector import SerialCollector

        SerialCollector(device_id, config).run()
    elif collector_type == 'net':
        from module_payload.collectors.net_collector import NetCollector

        NetCollector(device_id, config).run()
    else:
        raise ValueError(f'未知采集类型: {collector_type}')


def main() -> None:
    import signal

    # 子进程忽略 Ctrl+C：由主进程 JobObject / shutdown_all 统一回收，避免在 Redis IO 上刷 KeyboardInterrupt 堆栈
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception:
        pass

    parser = argparse.ArgumentParser(description='地检平台采集进程')
    parser.add_argument('collector_type', choices=['can', 'serial', 'net'])
    parser.add_argument('device_id')
    parser.add_argument('config_json')
    args = parser.parse_args()
    config = json.loads(args.config_json)
    try:
        run_collector(args.collector_type, args.device_id, config)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == '__main__':
    main()
