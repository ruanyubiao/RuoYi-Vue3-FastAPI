"""Redis 预览 IO 日志：500ms 节流、HEX 截断、双写目标；文件旁路每包都写。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from module_payload.collectors.base_collector import BaseCollector
from module_payload.constants import IO_LOG_MAX, IO_LOG_MIN_INTERVAL_S
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


def test_io_log_hex_keeps_full_payload(monkeypatch) -> None:
    c = _coll()
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.time.monotonic',
        lambda: 1.0,
    )
    payload = bytes(range(256)) + b'\xFF' * 284
    c._push_io('recv', payload)
    entry = _lpush_entries(c._redis)[0]
    assert entry['len'] == 540
    assert 'truncated' not in entry
    assert '...(+' not in entry['hex']
    assert entry['hex'].startswith('00 01 02')
    assert entry['hex'].endswith('FF FF FF')
    assert len(entry['hex'].split()) == 540


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


def test_io_log_to_file_false_skips_xfer(monkeypatch) -> None:
    c = _coll()
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.time.monotonic',
        lambda: 1.0,
    )
    c._push_io('recv', b'\xEB\x90', to_file=False)
    assert c._xfer_append_io.call_count == 0
    assert c._redis.lpush.call_count == 1


def test_dispatch_serial_preview_uses_parsed_d8(monkeypatch) -> None:
    from module_payload.assemblers.base import AssembledPayload
    from module_payload.cfg.hex_text import hex_to_bytes
    from module_payload.constants import PARSER_CAMERA_SC_LINK41EP, SRC_KIND_SERIAL
    from module_payload.parsers.camera_sc_link41ep import CameraScLink41epIngest

    frame = hex_to_bytes(
        'EB 90 D8 00 00 2D 34 8A AA AA 01 36 3C 7F 8D FF 00 10 66 9E 06 05 '
        '01 00 10 00 00 00 09 E7 02 58 01 4F 00 01 01 14 07 D2 0D 48 03 90 '
        '0A 6A 00 00 00 00 32 01 32 0F'
    )
    blob = bytes.fromhex('01 07 00 00 00 13 24 E5') + frame

    class _Ing:
        ingest_bytes_sync = MagicMock(return_value=None)
        io_preview_frames = staticmethod(CameraScLink41epIngest.io_preview_frames)

    c = _coll()
    c._store_assembled = MagicMock()  # type: ignore[method-assign]
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.time.monotonic',
        lambda: 1.0,
    )
    c._dispatch_payloads(
        [AssembledPayload(data=blob)],
        src_param='serial:COM3',
        src_kind=SRC_KIND_SERIAL,
        assembler_id='passthrough',
        parser_id=PARSER_CAMERA_SC_LINK41EP,
        resolve_parser=lambda _pid: _Ing,
        push_pipeline_error=MagicMock(),
    )
    entry = _lpush_entries(c._redis)[0]
    assert entry['hex'].startswith('EB 90 D8')
    assert not entry['hex'].startswith('01 07')
    assert entry['len'] == len(frame)
    c._xfer_append_io.assert_not_called()


def test_dispatch_serial_without_parser_logs_chunk(monkeypatch) -> None:
    from module_payload.assemblers.base import AssembledPayload
    from module_payload.constants import SRC_KIND_SERIAL

    c = _coll()
    c._store_assembled = MagicMock()  # type: ignore[method-assign]
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.time.monotonic',
        lambda: 1.0,
    )
    c._dispatch_payloads(
        [AssembledPayload(data=b'\xAA\xBB')],
        src_param='serial:COM3',
        src_kind=SRC_KIND_SERIAL,
        assembler_id='passthrough',
        parser_id='',
        resolve_parser=lambda _pid: None,
        push_pipeline_error=MagicMock(),
    )
    entry = _lpush_entries(c._redis)[0]
    assert entry['hex'] == 'AA BB'


def test_dispatch_can_does_not_preview_io(monkeypatch) -> None:
    from module_payload.assemblers.base import AssembledPayload
    from module_payload.constants import SRC_KIND_CAN

    class _Ing:
        ingest_bytes_sync = MagicMock(return_value=None)
        io_preview_frames = staticmethod(lambda _data: [b'\xFF'])

    c = _coll()
    c._store_assembled = MagicMock()  # type: ignore[method-assign]
    c._dispatch_payloads(
        [AssembledPayload(data=b'\x01\x02')],
        src_param='can:0:0',
        src_kind=SRC_KIND_CAN,
        assembler_id='can_biu',
        parser_id='tm_can_biu',
        resolve_parser=lambda _pid: _Ing,
        push_pipeline_error=MagicMock(),
    )
    c._redis.lpush.assert_not_called()
    _Ing.ingest_bytes_sync.assert_called()


def test_push_stream_io_stays_in_memory_until_flush() -> None:
    c = _coll()
    c._push_stream_io('recv', b'\x01')
    c._push_stream_io('recv', b'\x02')
    assert c._redis.lpush.call_count == 0
    c._xfer_append_io.assert_not_called()
    c._flush_stream_io_to_redis()
    assert c._redis.lpush.call_count == 1
    args = c._redis.lpush.call_args[0]
    assert args[0] == rk.io_stream_key('serial:COM3')
    assert len(args) == 3
    entries = [json.loads(x) for x in args[1:]]
    assert [e['seq'] for e in entries] == [1, 2]
    assert [e['hex'] for e in entries] == ['01', '02']
    c._redis.ltrim.assert_called_with(rk.io_stream_key('serial:COM3'), 0, IO_LOG_MAX - 1)


def test_flush_stream_io_incremental_and_redis_fail_retries() -> None:
    c = _coll()
    c._push_stream_io('recv', b'\x01')
    c._flush_stream_io_to_redis()
    c._redis.lpush.reset_mock()
    c._flush_stream_io_to_redis()
    assert c._redis.lpush.call_count == 0
    c._push_stream_io('recv', b'\x02')
    c._flush_stream_io_to_redis()
    assert c._redis.lpush.call_count == 1
    entries = [json.loads(x) for x in c._redis.lpush.call_args[0][1:]]
    assert [e['seq'] for e in entries] == [2]

    c._redis.lpush.side_effect = ConnectionError('down')
    c._push_stream_io('recv', b'\x03')
    c._flush_stream_io_to_redis()  # 不断连异常
    c._redis.lpush.side_effect = None
    c._redis.lpush.reset_mock()
    c._flush_stream_io_to_redis()
    entries = [json.loads(x) for x in c._redis.lpush.call_args[0][1:]]
    assert [e['seq'] for e in entries] == [3]


def test_stream_io_ring_keeps_last_max() -> None:
    c = _coll()
    for i in range(IO_LOG_MAX + 3):
        c._push_stream_io('recv', bytes([i & 0xFF]))
    c._flush_stream_io_to_redis()
    args = c._redis.lpush.call_args[0]
    assert args[0] == rk.io_stream_key('serial:COM3')
    assert len(args) == IO_LOG_MAX + 1
    first = json.loads(args[1])
    last = json.loads(args[-1])
    assert first['seq'] == 4
    assert last['seq'] == IO_LOG_MAX + 3


def test_teardown_flushes_stream_io() -> None:
    c = _coll()
    c._xfer_loggers = {}
    c._xfer_tags = {}
    c._push_stream_io('recv', b'\xAA')
    c.teardown()
    assert c._redis.lpush.call_count == 1


def test_consume_control_flush_and_clear_stream() -> None:
    c = _coll()
    c._running = True
    c._push_stream_io('recv', b'\x01')
    flush_msg = json.dumps(
        {'op': 'flush_io_stream', 'device_id': 'serial:COM3', 'req_id': 'r1'}
    )
    c._redis.lpop = MagicMock(side_effect=[flush_msg, None])
    c._consume_control()
    assert c._redis.lpush.call_count == 1
    c._redis.setex.assert_called()
    ack_key = c._redis.setex.call_args[0][0]
    assert ack_key == rk.io_stream_flush_ack_key('serial:COM3', 'r1')

    c._redis.delete.reset_mock()
    c._redis.setex.reset_mock()
    clear_msg = json.dumps(
        {'op': 'clear_io_stream', 'device_id': 'serial:COM3', 'req_id': 'r2'}
    )
    c._redis.lpop = MagicMock(side_effect=[clear_msg, None])
    c._consume_control()
    deleted = c._redis.delete.call_args[0]
    assert rk.io_stream_key('serial:COM3') in deleted
    assert not c._stream_io_bufs.get('serial:COM3')


def test_push_io_preview_does_not_write_stream(monkeypatch) -> None:
    c = _coll()
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.time.monotonic',
        lambda: 1.0,
    )
    c._push_io('recv', b'\xAA', to_file=False)
    keys = [call[0][0] for call in c._redis.lpush.call_args_list]
    assert rk.io_log_key('serial:COM3') in keys
    assert rk.io_stream_key('serial:COM3') not in keys
    c._push_stream_io('recv', b'\xBB')
    assert rk.io_stream_key('serial:COM3') not in [
        call[0][0] for call in c._redis.lpush.call_args_list
    ]


def test_get_clear_io_log_kind_stream() -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from module_payload.service.payload_device_service import PayloadDeviceService

    redis = AsyncMock()
    redis.lrange = AsyncMock(
        return_value=[
            json.dumps({'seq': 2, 'hex': 'AA'}).encode(),
            json.dumps({'seq': 1, 'hex': 'BB'}).encode(),
        ]
    )
    out = asyncio.run(
        PayloadDeviceService.get_io_log(redis, 'serial:COM3', since_seq=0, kind='stream')
    )
    redis.lrange.assert_awaited_with(rk.io_stream_key('serial:COM3'), 0, 199)
    assert out['kind'] == 'stream'
    assert [e['seq'] for e in out['items']] == [1, 2]

    redis.delete = AsyncMock()
    asyncio.run(PayloadDeviceService.clear_io_log(redis, 'serial:COM3', kind='stream'))
    args = redis.delete.await_args[0]
    assert rk.io_stream_key('serial:COM3') in args
    assert rk.io_stream_seq_key('serial:COM3') in args
    assert rk.io_log_key('serial:COM3') not in args


def test_get_io_log_stream_waits_flush_ack(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from module_payload.service.payload_device_service import PayloadDeviceService

    order: list[str] = []
    redis = AsyncMock()

    async def get(_k):
        order.append('ack')
        return b'1'

    async def lrange(*_a, **_k):
        order.append('lrange')
        return []

    redis.get = get
    redis.lrange = lrange
    redis.delete = AsyncMock()
    monkeypatch.setattr(
        PayloadDeviceService, '_is_device_alive', classmethod(lambda cls, _did: True)
    )
    mgr = MagicMock()
    monkeypatch.setattr(
        'module_payload.service.payload_device_service.CollectorProcessManager.instance',
        lambda: mgr,
    )
    asyncio.run(PayloadDeviceService.get_io_log(redis, 'serial:COM3', kind='stream'))
    mgr.notify_flush_io_stream.assert_called_once()
    assert mgr.notify_flush_io_stream.call_args[0][0] == 'serial:COM3'
    assert order == ['ack', 'lrange']


def test_get_io_log_default_kind_is_preview() -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from module_payload.service.payload_device_service import PayloadDeviceService

    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=[])
    out = asyncio.run(PayloadDeviceService.get_io_log(redis, 'serial:COM3'))
    redis.lrange.assert_awaited_with(rk.io_log_key('serial:COM3'), 0, 199)
    assert out['kind'] == 'preview'
