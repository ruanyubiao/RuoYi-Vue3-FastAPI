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


def run_collector(collector_type: str, device_id: str, config: dict[str, Any]) -> None:
    _bootstrap_env()
    if collector_type == 'can':
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
    parser = argparse.ArgumentParser(description='地检平台采集进程')
    parser.add_argument('collector_type', choices=['can', 'serial', 'net'])
    parser.add_argument('device_id')
    parser.add_argument('config_json')
    args = parser.parse_args()
    config = json.loads(args.config_json)
    run_collector(args.collector_type, args.device_id, config)


if __name__ == '__main__':
    main()
