"""Redis 预览 IO 日志按最小间隔落盘；文件旁路每包都写。"""

from __future__ import annotations

from unittest.mock import MagicMock

from module_payload.collectors.base_collector import BaseCollector
from module_payload.constants import IO_LOG_MIN_INTERVAL_S


def _coll() -> BaseCollector:
    c = BaseCollector.__new__(BaseCollector)
    c.device_id = 'serial:COM3'
    c.config = {'source': 'home'}
    c._io_log_last_mono = {}
    c._redis = MagicMock()
    c._redis.incr = MagicMock(side_effect=lambda *_a, **_k: 1)
    c._io_log_targets = lambda did: [did]  # type: ignore[method-assign]
    c._xfer_append_io = MagicMock()  # type: ignore[method-assign]
    return c


def test_io_log_redis_throttled_xfer_not(monkeypatch) -> None:
    c = _coll()
    mono = {'t': 1000.0}
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.time.monotonic',
        lambda: mono['t'],
    )
    c._push_io('recv', b'\x01\x02')
    c._push_io('recv', b'\x03\x04')
    assert c._redis.lpush.call_count == 1
    assert c._xfer_append_io.call_count == 2

    mono['t'] += IO_LOG_MIN_INTERVAL_S
    c._push_io('recv', b'\x05')
    assert c._redis.lpush.call_count == 2
    assert c._xfer_append_io.call_count == 3


def test_io_log_send_not_blocked_by_recv(monkeypatch) -> None:
    c = _coll()
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.time.monotonic',
        lambda: 1.0,
    )
    c._push_io('recv', b'\x01')
    c._push_io('send', b'\x02')
    assert c._redis.lpush.call_count == 2
