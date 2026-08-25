"""Redis 预览 IO 日志：500ms 节流、HEX 截断、双写目标；文件旁路每包都写。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from module_payload.collectors.base_collector import BaseCollector
from module_payload.constants import IO_LOG_HEX_MAX_BYTES, IO_LOG_MAX, IO_LOG_MIN_INTERVAL_S
from module_payload import redis_keys as rk


def _coll(**kwargs) -> BaseCollector:
    c = BaseCollector.__new__(BaseCollector)
    c.device_id = kwargs.pop('device_id', 'serial:COM3')
    c.config = kwargs.pop('config', {'source': 'home'})
    c._io_log_last_mono = {}
    c._redis = MagicMock()
    c._redis.incr = MagicMock(side_effect=lambda *_a, **_k: c._redis.incr.call_count)
    c._io_log_targets = kwargs.pop(  # type: ignore[method-assign]
        'targets_fn', lambda did: [did]
    )
    c._xfer_append_io = MagicMock()  # type: ignore[method-assign]
    for key, val in kwargs.items():
        setattr(c, key, val)
    return c


def _lpush_entries(mock_redis) -> list[dict]:
    out = []
    for call in mock_redis.lpush.call_args_list:
        key, raw = call[0][:2]
        entry = json.loads(raw)
        entry['_key'] = key
        out.append(entry)
    return out


def test_io_log_min_interval_constant() -> None:
    assert IO_LOG_MIN_INTERVAL_S == 0.5
    assert IO_LOG_HEX_MAX_BYTES == 256
    assert IO_LOG_MAX == 1000


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

    mono['t'] += IO_LOG_MIN_INTERVAL_S - 0.001
    c._push_io('recv', b'\xAA')
    assert c._redis.lpush.call_count == 1

    mono['t'] += 0.001
    c._push_io('recv', b'\x05')
    assert c._redis.lpush.call_count == 2
    assert c._xfer_append_io.call_count == 4


def test_io_log_send_not_blocked_by_recv(monkeypatch) -> None:
    c = _coll()
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.time.monotonic',
        lambda: 1.0,
    )
    c._push_io('recv', b'\x01')
    c._push_io('send', b'\x02')
    assert c._redis.lpush.call_count == 2
    dirs = [e['dir'] for e in _lpush_entries(c._redis)]
    assert dirs == ['recv', 'send']


def test_io_log_same_dir_independent_per_device(monkeypatch) -> None:
    c = _coll()
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.time.monotonic',
        lambda: 1.0,
    )
    c._push_io('recv', b'\x01', device_id='serial:COM3')
    c._push_io('recv', b'\x02', device_id='serial:COM4')
    assert c._redis.lpush.call_count == 2


def test_io_log_empty_payload_without_frame_id_skipped() -> None:
    c = _coll()
    c._push_io('recv', b'')
    c._redis.lpush.assert_not_called()
    c._xfer_append_io.assert_not_called()


def test_io_log_hex_truncated_keeps_real_len(monkeypatch) -> None:
    c = _coll()
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.time.monotonic',
        lambda: 1.0,
    )
    payload = bytes(range(256)) + b'\xFF'
    c._push_io('recv', payload)
    entry = _lpush_entries(c._redis)[0]
    assert entry['len'] == 257
    assert entry['truncated'] is True
    assert f'+{257 - IO_LOG_HEX_MAX_BYTES}B' in entry['hex']
    assert entry['hex'].startswith('00 01 02')
    assert 'FF' not in entry['hex'].split()[:3]


def test_io_log_short_payload_not_truncated(monkeypatch) -> None:
    c = _coll()
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.time.monotonic',
        lambda: 1.0,
    )
    c._push_io('recv', b'\xEB\x90\x5B')
    entry = _lpush_entries(c._redis)[0]
    assert entry['hex'] == 'EB 90 5B'
    assert 'truncated' not in entry
    assert entry['len'] == 3


def test_io_log_dual_write_source_and_device(monkeypatch) -> None:
    c = _coll(targets_fn=lambda did: [did, rk.source_id('camera_ctrl')])
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.time.monotonic',
        lambda: 1.0,
    )
    c._push_io('recv', b'\x01')
    keys = [e['_key'] for e in _lpush_entries(c._redis)]
    assert rk.io_log_key('serial:COM3') in keys
    assert rk.io_log_key(rk.source_id('camera_ctrl')) in keys
    assert c._redis.ltrim.call_count == 2


def test_io_log_trims_to_max(monkeypatch) -> None:
    c = _coll()
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.time.monotonic',
        lambda: 1.0,
    )
    c._push_io('recv', b'\x01')
    c._redis.ltrim.assert_called_with(rk.io_log_key('serial:COM3'), 0, IO_LOG_MAX - 1)


def test_io_log_missing_last_mono_dict(monkeypatch) -> None:
    c = _coll()
    del c._io_log_last_mono
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.time.monotonic',
        lambda: 1.0,
    )
    c._push_io('recv', b'\x01')
    assert c._redis.lpush.call_count == 1
    assert isinstance(c._io_log_last_mono, dict)


def test_io_log_frame_id_hex(monkeypatch) -> None:
    c = _coll()
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.time.monotonic',
        lambda: 1.0,
    )
    c._push_io('recv', b'\xAA', frame_id=0x234)
    entry = _lpush_entries(c._redis)[0]
    assert entry['frameIdHex'] == '00 00 02 34'
    assert entry['hex'] == 'AA'
