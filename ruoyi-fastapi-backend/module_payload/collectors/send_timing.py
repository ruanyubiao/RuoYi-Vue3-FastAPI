"""CAN 发送链路分段时间追踪（诊断首帧延迟）。写入 logs 目录下 ``can_send_timing.jsonl``。"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_origins: dict[str, float] = {}


def trace_file_path() -> Path:
    from config.paths import get_logs_data_dir

    return get_logs_data_dir() / 'can_send_timing.jsonl'


def start_trace(trace_id: str, *, label: str = '', note: str = '') -> None:
    if not trace_id:
        return
    mono = time.monotonic()
    with _lock:
        _origins[trace_id] = mono
    mark(
        trace_id,
        'trace.start',
        label=label,
        note=note or '定时遥测帧在采集进程内组包直发 CAN，不经 Redis 逐帧队列',
    )


def mark(trace_id: str | None, stage: str, **extra: Any) -> None:
    if not trace_id:
        return
    mono = time.monotonic()
    with _lock:
        origin = _origins.get(trace_id, mono)
        row = {
            'traceId': trace_id,
            'stage': stage,
            'wall': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'monoMs': round(mono * 1000, 3),
            'sinceStartMs': round((mono - origin) * 1000, 3),
            **extra,
        }
        path = trace_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as fp:
            fp.write(json.dumps(row, ensure_ascii=False) + '\n')


def finish_trace(trace_id: str | None, **extra: Any) -> None:
    if not trace_id:
        return
    mark(trace_id, 'trace.end', **extra)
    with _lock:
        _origins.pop(trace_id, None)
