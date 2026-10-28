"""P0-4：发送历史写入含 can_frames；旧条目无该字段不炸。"""

from __future__ import annotations

import json
import threading
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collectors.base_collector import BaseCollector
from redis_fakes import fake_collector_redis


def _base(**kwargs) -> BaseCollector:
    c = BaseCollector.__new__(BaseCollector)
    c.device_id = kwargs.pop("device_id", "can:3:0:0")
    c.config = kwargs.pop("config", {"source": "xl-tc"})
    redis = kwargs.pop("redis", None)
    if redis is None:
        redis, c._fake = fake_collector_redis()
    c._redis = redis
    c._rx_count = 0
    c._tx_count = 0
    c._assembler = None
    c._assembler_id = None
    c._assemblers = {}
    c._demux = None
    c._demux_fp = None
    c._xfer_loggers = {}
    c._xfer_tags = {}
    c._session_cache = {}
    c._session_cache_mono = {}
    c._pipeline_lock = threading.RLock()
    c._rx_thread = None
    c._io_log_seq_local = {}
    c._stream_io_lock = threading.Lock()
    c._stream_io_bufs = {}
    c._stream_io_seq = {}
    c._stream_io_flushed_seq = {}
    for k, v in kwargs.items():
        setattr(c, k, v)
    return c


def _can_frame_rows(entry: dict[str, Any]) -> list[str]:
    """契约：有 can_frames 则格式化；缺字段 / 非 list → 空列表，不得抛错。"""
    frames = entry.get("can_frames") if isinstance(entry, dict) else None
    if not isinstance(frames, list) or not frames:
        return []
    rows: list[str] = []
    for fr in frames:
        if isinstance(fr, str):
            rows.append(fr)
            continue
        if not isinstance(fr, dict):
            continue
        fid = fr.get("id")
        try:
            id_hex = f"{int(fid) & 0x1FFFFFFF:08X}"
        except (TypeError, ValueError):
            id_hex = "00000000"
        data = fr.get("data")
        if isinstance(data, str):
            data_s = data.strip()
        elif isinstance(data, list):
            data_s = " ".join(f"{int(b) & 0xFF:02X}" for b in data[:8])
        else:
            data_s = ""
        rows.append(f"{id_hex} [{data_s}]")
    return rows


def test_push_history_writes_can_frames() -> None:
    """新发送历史条目应带上 command.can_frames。"""
    c = _base()
    c._push_io = lambda *a, **k: None  # type: ignore[method-assign]
    c._push_stream_io = lambda *a, **k: None  # type: ignore[method-assign]
    c._history_source = lambda _src: "xl-tc"  # type: ignore[method-assign]

    frames = [{"id": 0x368, "data": [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07]}]
    c._push_history(
        {"hex": "AA", "name": "K1501", "can_frames": frames},
        {"success": True, "ts": "2026-10-29 01:00:00.000"},
    )
    c._redis.flush()
    hist_key = rk.source_history_key("xl-tc")
    ops = [args for name, args in c._fake.executed if name == "lpush" and args[0] == hist_key]
    assert ops, "应 LPUSH 到来源历史"
    entry = json.loads(ops[0][1])
    assert entry["can_frames"] == frames
    assert _can_frame_rows(entry) == ["00000368 [00 01 02 03 04 05 06 07]"]


def test_old_history_entry_without_can_frames_does_not_crash() -> None:
    """旧条目无 can_frames 字段：消费侧契约返回空，不得 KeyError/TypeError。"""
    legacy = {
        "ts": "2026-10-01 00:00:00.000",
        "name": "旧指令",
        "hex": "EB 90",
        "success": True,
        "message": "OK",
        "deviceId": "can:3:0:0",
    }
    assert "can_frames" not in legacy
    assert _can_frame_rows(legacy) == []
    assert _can_frame_rows({}) == []
    assert _can_frame_rows({"can_frames": None}) == []  # type: ignore[dict-item]
    assert _can_frame_rows({"can_frames": "not-a-list"}) == []  # type: ignore[dict-item]
    assert _can_frame_rows({"can_frames": []}) == []

    c = _base()
    c._push_io = lambda *a, **k: None  # type: ignore[method-assign]
    c._push_stream_io = lambda *a, **k: None  # type: ignore[method-assign]
    c._history_source = lambda _src: "xl-tc"  # type: ignore[method-assign]
    c._push_history(
        {"hex": "01 02", "name": "plain"},
        {"success": True, "ts": "2026-10-29 01:00:01.000"},
    )
    c._redis.flush()
    hist_key = rk.source_history_key("xl-tc")
    ops = [args for name, args in c._fake.executed if name == "lpush" and args[0] == hist_key]
    entry = json.loads(ops[0][1])
    assert "can_frames" not in entry
    assert _can_frame_rows(entry) == []
