"""Redis 预览 IO 日志：同类 recv 1s 合并最新一条；send 不拦截；调试 stream 不合并。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from module_payload.collectors.base_collector import BaseCollector
from module_payload.constants import IO_LOG_MAX
from module_payload import redis_keys as rk
from redis_fakes import fake_collector_redis, lpush_entries


def _coll(**kwargs) -> BaseCollector:
    c = BaseCollector.__new__(BaseCollector)
    c.device_id = kwargs.pop('device_id', 'serial:COM3')
    c.config = kwargs.pop('config', {'source': 'home'})
    c._io_log_seq_local = {}
    c._redis, c._fake = fake_collector_redis()
    c._io_log_targets = kwargs.pop(  # type: ignore[method-assign]
        'targets_fn', lambda did: [did]
    )
    c._xfer_append_io = MagicMock()  # type: ignore[method-assign]
    c._stream_recv_on = {c.device_id: True}
    for key, val in kwargs.items():
        setattr(c, key, val)
    return c


def _lpush_entries(coll: BaseCollector) -> list[dict]:
    coll._redis.flush()
    return lpush_entries(coll._fake)


def test_io_log_max_constant() -> None:
    assert IO_LOG_MAX == 1000


def test_io_log_records_every_packet() -> None:
    """不同类型 recv 仍每包都记；文件旁路也不丢。"""
    c = _coll()
    c._push_io('recv', b'\x01\x02')
    c._push_io('recv', b'\x03\x04')
    c._push_io('recv', b'\xAA')
    assert len(_lpush_entries(c)) == 3
    assert c._xfer_append_io.call_count == 3


def test_io_log_writes_are_buffered_until_flush() -> None:
    """业务线程只入队，不打 Redis：一条日志 = 序号写回 + LPUSH。"""
    c = _coll()
    c._push_io('recv', b'\x01')
    assert c._fake.executed == []
    assert c._redis.pending_count == 2


def test_io_log_send_and_recv_both_recorded() -> None:
    c = _coll()
    c._push_io('recv', b'\x01')
    c._push_io('send', b'\x02')
    dirs = [e['dir'] for e in _lpush_entries(c)]
    assert dirs == ['recv', 'send']


_D9_A = bytes.fromhex('EB D9 01 AA AA 01 FF FF FF FF 00 00 07 22 00 00 00 00 DE 31')
_D9_B = bytes.fromhex('EB D9 02 AA AA 01 FF FF FF FF 00 00 07 28 00 01 01 01 14 72')
_D8 = bytes.fromhex('EB 90 D8 00 00 2D 00 01')


def _pin_now(c: BaseCollector, clock: dict[str, float]) -> None:
    c._preview_io_now = lambda: clock['t']  # type: ignore[method-assign]


def test_preview_kind_d9_d8_send() -> None:
    from module_payload.collectors.base_collector import preview_io_coalesce_kind

    assert preview_io_coalesce_kind('send', _D9_A) is None
    assert preview_io_coalesce_kind('recv', _D9_A) == 'EB D9'
    assert preview_io_coalesce_kind('recv', _D8) == 'EB 90 D8'
    assert preview_io_coalesce_kind('recv', b'\xEB\x90\xD6' + bytes(10)) == 'EB 90 D6'
    assert preview_io_coalesce_kind('recv', b'\x55\xAA\x00') == '55 AA'


def test_preview_coalesce_same_d9_writes_latest_after_1s() -> None:
    """首条立即写；1s 内同类只缓存最新；到期写出缓存。"""
    c = _coll()
    clock = {'t': 10.0}
    _pin_now(c, clock)
    c._push_io('recv', _D9_A, to_file=False)
    c._push_io('recv', _D9_B, to_file=False)
    c._push_io('recv', _D9_A, to_file=False)
    first = _lpush_entries(c)
    assert len(first) == 1
    assert first[0]['hex'].startswith('EB D9 01')
    clock['t'] = 11.0
    c._flush_preview_io_due()
    entries = _lpush_entries(c)
    assert len(entries) == 2
    assert entries[1]['hex'].startswith('EB D9 01')
    assert [e['seq'] for e in entries] == [1, 2]


def test_preview_coalesce_two_per_second_burst_stays_one_hz() -> None:
    """实际遥测每秒成对到达（间隔约 3ms）：预览按上次写入限 1Hz。"""
    c = _coll()
    clock = {'t': 0.0}
    _pin_now(c, clock)
    clock['t'] = 53.454
    c._push_io('recv', _D9_A, to_file=False)
    clock['t'] = 53.457
    c._push_io('recv', _D9_B, to_file=False)
    assert len(_lpush_entries(c)) == 1
    clock['t'] = 54.454
    c._flush_preview_io_due()
    assert len(_lpush_entries(c)) == 2
    clock['t'] = 54.462
    c._push_io('recv', _D9_A, to_file=False)
    clock['t'] = 54.465
    c._push_io('recv', _D9_B, to_file=False)
    assert len(_lpush_entries(c)) == 2
    clock['t'] = 55.462
    c._flush_preview_io_due()
    entries = _lpush_entries(c)
    assert len(entries) == 3
    assert entries[-1]['hex'].startswith('EB D9 02')


def test_preview_coalesce_expired_packet_does_not_double_write() -> None:
    """窗口到期时新包取代缓存，不得把 pending 和新包各写一次。"""
    c = _coll()
    clock = {'t': 0.0}
    _pin_now(c, clock)
    c._push_io('recv', _D9_A, to_file=False)
    c._push_io('recv', _D9_B, to_file=False)
    clock['t'] = 1.008
    c._push_io('recv', _D9_A, to_file=False)
    entries = _lpush_entries(c)
    assert len(entries) == 2
    assert entries[1]['hex'].startswith('EB D9 01')


def test_preview_coalesce_d8_flushes_pending_d9() -> None:
    c = _coll()
    clock = {'t': 1.0}
    _pin_now(c, clock)
    c._push_io('recv', _D9_A, to_file=False)
    c._push_io('recv', _D9_B, to_file=False)
    c._push_io('recv', _D8, to_file=False)
    entries = _lpush_entries(c)
    assert len(entries) == 3
    assert entries[0]['hex'].startswith('EB D9 01')
    assert entries[1]['hex'].startswith('EB D9 02')
    assert entries[2]['hex'].startswith('EB 90 D8')


def test_preview_coalesce_send_not_intercepted() -> None:
    """send 不合并；出现 send 时先刷出缓存的 recv。"""
    c = _coll()
    clock = {'t': 1.0}
    _pin_now(c, clock)
    c._push_io('recv', _D9_A, to_file=False)
    c._push_io('recv', _D9_B, to_file=False)
    c._push_io('send', b'\xAA\xBB', to_file=False)
    c._push_io('send', b'\xCC', to_file=False)
    entries = _lpush_entries(c)
    assert [e['dir'] for e in entries] == ['recv', 'recv', 'send', 'send']
    assert entries[1]['hex'].startswith('EB D9 02')
    assert entries[2]['hex'] == 'AA BB'
    assert entries[3]['hex'] == 'CC'


def test_preview_coalesce_does_not_drop_file_side() -> None:
    """合并只挡 Redis 预览，recv.bin 仍每包落盘。"""
    c = _coll()
    clock = {'t': 1.0}
    _pin_now(c, clock)
    c._push_io('recv', _D9_A)
    c._push_io('recv', _D9_B)
    assert c._xfer_append_io.call_count == 2
    assert len(_lpush_entries(c)) == 1


def test_preview_coalesce_heartbeat_flushes_due() -> None:
    c = _coll()
    clock = {'t': 5.0}
    _pin_now(c, clock)
    c._push_io('recv', _D9_A, to_file=False)
    c._push_io('recv', _D9_B, to_file=False)
    clock['t'] = 6.0
    c._heartbeat()
    entries = [e for e in _lpush_entries(c) if e.get('dir') == 'recv']
    assert len(entries) == 2
    assert entries[1]['hex'].startswith('EB D9 02')


def test_io_log_seq_increments_per_target() -> None:
    c = _coll()
    c._push_io('recv', b'\x01')
    c._push_io('recv', b'\x02')
    assert [e['seq'] for e in _lpush_entries(c)] == [1, 2]


def test_io_log_seq_resumes_from_redis_once() -> None:
    """重启后从 Redis 续号；之后本地自增，不再每包往返。"""
    c = _coll()
    c._fake.store[rk.io_log_seq_key('serial:COM3')] = '50'
    c._push_io('recv', b'\x01')
    c._push_io('recv', b'\x02')
    assert [e['seq'] for e in _lpush_entries(c)] == [51, 52]
    sets = [args for name, args in c._fake.executed if name == 'set']
    assert (rk.io_log_seq_key('serial:COM3'), '52') in sets


def test_io_log_seq_does_not_round_trip_per_packet() -> None:
    """整图上千帧不能按包数做同步往返：只有首包读一次序号。"""
    c = _coll()
    reads = {'n': 0}
    real_get = c._fake.get

    def counting_get(key):
        reads['n'] += 1
        return real_get(key)

    c._fake.get = counting_get  # type: ignore[method-assign]
    for i in range(200):
        c._push_io('recv', bytes([i & 0xFF]), to_file=False)
    assert reads['n'] == 1
    assert [e['seq'] for e in _lpush_entries(c)] == list(range(1, 201))


def test_io_log_seq_survives_redis_read_failure() -> None:
    c = _coll()
    c._fake.get = MagicMock(side_effect=RuntimeError('down'))  # type: ignore[method-assign]
    c._push_io('recv', b'\x01')
    assert [e['seq'] for e in _lpush_entries(c)] == [1]


def test_io_log_same_dir_independent_per_device() -> None:
    c = _coll()
    c._push_io('recv', b'\x01', device_id='serial:COM3')
    c._push_io('recv', b'\x02', device_id='serial:COM4')
    keys = {e['_key'] for e in _lpush_entries(c)}
    assert keys == {rk.io_log_key('serial:COM3'), rk.io_log_key('serial:COM4')}


def test_io_log_empty_payload_without_frame_id_skipped() -> None:
    c = _coll()
    c._push_io('recv', b'')
    assert _lpush_entries(c) == []
    c._xfer_append_io.assert_not_called()


def test_io_log_hex_keeps_full_payload() -> None:
    c = _coll()
    payload = bytes(range(256)) + b'\xFF' * 284
    c._push_io('recv', payload)
    entry = _lpush_entries(c)[0]
    assert entry['len'] == 540
    assert 'truncated' not in entry
    assert '...(+' not in entry['hex']
    assert entry['hex'].startswith('00 01 02')
    assert entry['hex'].endswith('FF FF FF')
    assert len(entry['hex'].split()) == 540


def test_io_log_short_payload_not_truncated() -> None:
    c = _coll()
    c._push_io('recv', b'\xEB\x90\x5B')
    entry = _lpush_entries(c)[0]
    assert entry['hex'] == 'EB 90 5B'
    assert 'truncated' not in entry
    assert entry['len'] == 3


def test_io_log_preview_writes_source_only() -> None:
    c = _coll(config={'source': 'camera_ctrl_v17'})
    c._io_log_targets = BaseCollector._io_log_targets.__get__(c, BaseCollector)
    c._push_io('recv', b'\x01')
    keys = {e['_key'] for e in _lpush_entries(c)}
    assert keys == {rk.io_log_key(rk.source_id('camera_ctrl_v17'))}


def test_io_log_preview_skips_when_no_source() -> None:
    c = _coll()
    c._io_log_targets = BaseCollector._io_log_targets.__get__(c, BaseCollector)
    c._push_io('recv', b'\x01')
    assert _lpush_entries(c) == []
    assert c._xfer_append_io.call_count == 1


def test_io_log_trim_is_periodic_not_per_write() -> None:
    """写入路径不带 LTRIM；定时器到点才裁到上限。"""
    c = _coll()
    c._push_io('recv', b'\x01')
    c._redis.flush()
    assert [name for name, _ in c._fake.executed] == ['set', 'lpush']
    c._redis._trim_due(force=True)
    trims = [args for name, args in c._fake.executed if name == 'ltrim']
    assert trims == [(rk.io_log_key('serial:COM3'), 0, IO_LOG_MAX - 1)]


def test_io_log_frame_id_hex() -> None:
    c = _coll()
    c._push_io('recv', b'\xAA', frame_id=0x234)
    entry = _lpush_entries(c)[0]
    assert entry['frameIdHex'] == '00 00 02 34'
    assert entry['hex'] == 'AA'


def test_io_log_to_file_false_skips_xfer() -> None:
    c = _coll()
    c._push_io('recv', b'\xEB\x90', to_file=False)
    assert c._xfer_append_io.call_count == 0
    assert len(_lpush_entries(c)) == 1


def test_io_log_uses_provided_ts() -> None:
    c = _coll()
    c._push_io('recv', b'\xEB\x90', to_file=False, ts='2026-09-17 16:58:03.226')
    entries = _lpush_entries(c)
    assert entries[0]['ts'] == '2026-09-17 16:58:03.226'


def test_camera_frame_burst_is_one_pipeline() -> None:
    """整图 1250 帧逐条入队，刷出时按 pipeline 上限分段，而不是每帧打一次 Redis。"""
    c = _coll()
    for i in range(1250):
        c._push_io('recv', bytes([i & 0xFF]), to_file=False)
    assert c._fake.executed == []
    c._redis.flush()
    assert len(c._fake.batches) == 4
    assert len(lpush_entries(c._fake)) == 1250


def test_dispatch_serial_preview_uses_parsed_d8(monkeypatch) -> None:
    from module_payload.assemblers.base import AssembledPayload
    from module_payload.cfg.hex_text import hex_to_bytes
    from module_payload.constants import PARSER_TM_XL_CAMERA, SRC_KIND_SERIAL
    from module_payload.parsers.xl_camera_tm import XlCameraTmIngest

    frame = hex_to_bytes(
        'EB 90 D8 00 00 2D 34 8A AA AA 01 36 3C 7F 8D FF 00 10 66 9E 06 05 '
        '01 00 10 00 00 00 09 E7 02 58 01 4F 00 01 01 14 07 D2 0D 48 03 90 '
        '0A 6A 00 00 00 00 32 01 32 0F'
    )
    blob = bytes.fromhex('01 07 00 00 00 13 24 E5') + frame

    class _Ing:
        ingest_bytes_sync = MagicMock(return_value=None)
        io_preview_frames = staticmethod(XlCameraTmIngest.io_preview_frames)

    c = _coll()
    c._store_assembled = MagicMock()  # type: ignore[method-assign]
    c._dispatch_payloads(
        [AssembledPayload(data=blob)],
        src_param='serial:COM3',
        src_kind=SRC_KIND_SERIAL,
        assembler_id='passthrough',
        parser_id=PARSER_TM_XL_CAMERA,
        resolve_parser=lambda _pid: _Ing,
        push_pipeline_error=MagicMock(),
    )
    entry = _lpush_entries(c)[0]
    assert entry['hex'].startswith('EB 90 D8')
    assert not entry['hex'].startswith('01 07')
    assert entry['len'] == len(frame)
    c._xfer_append_io.assert_not_called()


def test_dispatch_serial_without_parser_logs_chunk() -> None:
    from module_payload.assemblers.base import AssembledPayload
    from module_payload.constants import SRC_KIND_SERIAL

    c = _coll()
    c._store_assembled = MagicMock()  # type: ignore[method-assign]
    c._dispatch_payloads(
        [AssembledPayload(data=b'\xAA\xBB')],
        src_param='serial:COM3',
        src_kind=SRC_KIND_SERIAL,
        assembler_id='passthrough',
        parser_id='',
        resolve_parser=lambda _pid: None,
        push_pipeline_error=MagicMock(),
    )
    entry = _lpush_entries(c)[0]
    assert entry['hex'] == 'AA BB'


def test_dispatch_can_does_not_preview_io() -> None:
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
    assert _lpush_entries(c) == []
    _Ing.ingest_bytes_sync.assert_called()


def test_push_stream_io_stays_in_memory_until_flush() -> None:
    c = _coll()
    c._push_stream_io('recv', b'\x01')
    c._push_stream_io('recv', b'\x02')
    assert c._fake.executed == []
    c._xfer_append_io.assert_not_called()
    c._flush_stream_io_to_redis()
    entries = lpush_entries(c._fake, rk.io_stream_key('serial:COM3'))
    assert [e['seq'] for e in entries] == [1, 2]
    assert [e['hex'] for e in entries] == ['01', '02']
    c._redis._trim_due(force=True)
    trims = [args for name, args in c._fake.executed if name == 'ltrim']
    assert trims == [(rk.io_stream_key('serial:COM3'), 0, IO_LOG_MAX - 1)]


def test_flush_stream_io_incremental_and_redis_fail_retries() -> None:
    c = _coll()
    c._push_stream_io('recv', b'\x01')
    c._flush_stream_io_to_redis()
    assert [e['seq'] for e in lpush_entries(c._fake)] == [1]
    c._flush_stream_io_to_redis()
    assert [e['seq'] for e in lpush_entries(c._fake)] == [1]
    c._push_stream_io('recv', b'\x02')
    c._flush_stream_io_to_redis()
    assert [e['seq'] for e in lpush_entries(c._fake)] == [1, 2]

    c._fake.fail = True
    c._push_stream_io('recv', b'\x03')
    c._flush_stream_io_to_redis()  # 断连不抛异常，命令留在封装缓冲
    assert [e['seq'] for e in lpush_entries(c._fake)] == [1, 2]
    c._fake.fail = False
    c._redis.flush()  # 刷写线程下个节拍重试；不重复发，seq 3 只写一次
    assert [e['seq'] for e in lpush_entries(c._fake)] == [1, 2, 3]
    c._flush_stream_io_to_redis()
    assert [e['seq'] for e in lpush_entries(c._fake)] == [1, 2, 3]


def test_stream_io_ring_keeps_last_max() -> None:
    c = _coll()
    for i in range(IO_LOG_MAX + 3):
        c._push_stream_io('recv', bytes([i & 0xFF]))
    c._flush_stream_io_to_redis()
    entries = lpush_entries(c._fake, rk.io_stream_key('serial:COM3'))
    seqs = [e['seq'] for e in entries]
    assert len(seqs) == IO_LOG_MAX
    assert seqs[0] == 4
    assert seqs[-1] == IO_LOG_MAX + 3


def test_teardown_flushes_stream_io() -> None:
    c = _coll()
    c._xfer_loggers = {}
    c._xfer_tags = {}
    c._push_stream_io('recv', b'\xAA')
    c.teardown()
    assert len(lpush_entries(c._fake, rk.io_stream_key('serial:COM3'))) == 1


def test_consume_control_flush_and_clear_stream() -> None:
    c = _coll()
    c._running = True
    c._push_stream_io('recv', b'\x01')
    flush_msg = json.dumps(
        {'op': 'flush_io_stream', 'device_id': 'serial:COM3', 'req_id': 'r1'}
    )
    c._fake.store[rk.ctrl_queue_key('serial:COM3')] = [flush_msg]
    c._consume_control()
    assert len(lpush_entries(c._fake, rk.io_stream_key('serial:COM3'))) == 1
    acks = [args for name, args in c._fake.executed if name == 'setex']
    assert acks[0][0] == rk.io_stream_flush_ack_key('serial:COM3', 'r1')

    clear_msg = json.dumps(
        {'op': 'clear_io_stream', 'device_id': 'serial:COM3', 'req_id': 'r2'}
    )
    c._fake.store[rk.ctrl_queue_key('serial:COM3')] = [clear_msg]
    c._consume_control()
    c._redis.flush()
    deleted = [args for name, args in c._fake.executed if name == 'delete']
    assert any(rk.io_stream_key('serial:COM3') in args for args in deleted)
    assert not c._stream_io_bufs.get('serial:COM3')


def test_push_io_preview_does_not_write_stream() -> None:
    c = _coll()
    c._push_io('recv', b'\xAA', to_file=False)
    keys = {e['_key'] for e in _lpush_entries(c)}
    assert keys == {rk.io_log_key('serial:COM3')}
    c._push_stream_io('recv', b'\xBB')
    c._redis.flush()
    assert rk.io_stream_key('serial:COM3') not in {e['_key'] for e in lpush_entries(c._fake)}


def test_get_clear_io_log_kind_stream() -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from module_payload.service.payload_device_service import PayloadDeviceService

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.lrange = AsyncMock(
        return_value=[
            json.dumps({'seq': 2, 'hex': 'AA'}).encode(),
            json.dumps({'seq': 1, 'hex': 'BB'}).encode(),
        ]
    )
    out = asyncio.run(
        PayloadDeviceService.get_io_log(redis, 'serial:COM3', since_seq=0, kind='stream')
    )
    redis.lrange.assert_awaited_with(rk.io_stream_key('serial:COM3'), 0, IO_LOG_MAX - 1)
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

    async def get(k):
        key = k.decode() if isinstance(k, bytes) else str(k)
        if ':heartbeat' in key:
            order.append('hb')
            return b'alive'
        if key.endswith(':io:stream:on'):
            order.append('on')
            return b'1'
        order.append('ack')
        return b'1'

    async def lrange(*_a, **_k):
        order.append('lrange')
        return []

    redis.get = get
    redis.lrange = lrange
    redis.delete = AsyncMock()
    monkeypatch.setattr(
        PayloadDeviceService, '_is_device_alive', classmethod(lambda cls, _did: False)
    )
    mgr = MagicMock()
    monkeypatch.setattr(
        'module_payload.service.payload_device_service.CollectorProcessManager.instance',
        lambda: mgr,
    )
    asyncio.run(PayloadDeviceService.get_io_log(redis, 'serial:COM3', kind='stream'))
    mgr.notify_flush_io_stream.assert_called_once()
    assert mgr.notify_flush_io_stream.call_args[0][0] == 'serial:COM3'
    assert order == ['hb', 'on', 'hb', 'ack', 'lrange']


def test_get_io_log_default_kind_is_preview() -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from module_payload.service.payload_device_service import PayloadDeviceService

    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=[])
    out = asyncio.run(PayloadDeviceService.get_io_log(redis, 'serial:COM3'))
    redis.lrange.assert_awaited_with(rk.io_log_key('serial:COM3'), 0, IO_LOG_MAX - 1)
    assert out['kind'] == 'preview'


def _io_log_newest_first(seqs: list[int]) -> list[bytes]:
    """模拟 Redis List：index 0 为最新。"""
    return [json.dumps({'seq': s}).encode() for s in reversed(seqs)]


def test_get_io_log_stream_full_then_incremental() -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from module_payload.service.payload_device_service import PayloadDeviceService

    seqs = list(range(1, IO_LOG_MAX + 1))
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.lrange = AsyncMock(return_value=_io_log_newest_first(seqs))
    out = asyncio.run(
        PayloadDeviceService.get_io_log(redis, 'serial:COM3', since_seq=0, kind='stream')
    )
    assert [e['seq'] for e in out['items']] == seqs
    out2 = asyncio.run(
        PayloadDeviceService.get_io_log(redis, 'serial:COM3', since_seq=800, kind='stream')
    )
    assert [e['seq'] for e in out2['items']] == list(range(801, IO_LOG_MAX + 1))


def test_get_io_log_preview_full_then_incremental() -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from module_payload.service.payload_device_service import PayloadDeviceService

    seqs = list(range(1, IO_LOG_MAX + 1))
    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=_io_log_newest_first(seqs))
    out = asyncio.run(
        PayloadDeviceService.get_io_log(redis, 'serial:COM3', since_seq=0, kind='preview')
    )
    assert [e['seq'] for e in out['items']] == seqs
    out2 = asyncio.run(
        PayloadDeviceService.get_io_log(redis, 'serial:COM3', since_seq=800, kind='preview')
    )
    assert [e['seq'] for e in out2['items']] == list(range(801, IO_LOG_MAX + 1))


def test_get_io_log_stale_since_seq_replays_when_list_max_behind() -> None:
    """前端 lastSeq 高于 Redis 序号（序号键被清/回绕）时不能一直空读，否则传输信息假死。"""
    import asyncio
    from unittest.mock import AsyncMock

    from module_payload.service.payload_device_service import PayloadDeviceService

    seqs = [1, 2, 3, 4, 5]
    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=_io_log_newest_first(seqs))
    out = asyncio.run(
        PayloadDeviceService.get_io_log(
            redis, 'source:camera_ctrl_v17', since_seq=9999, kind='preview'
        )
    )
    assert [e['seq'] for e in out['items']] == seqs


def test_get_io_log_caught_up_does_not_replay() -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from module_payload.service.payload_device_service import PayloadDeviceService

    seqs = [1, 2, 3, 4, 5]
    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=_io_log_newest_first(seqs))
    out = asyncio.run(
        PayloadDeviceService.get_io_log(redis, 'serial:COM3', since_seq=5, kind='preview')
    )
    assert out['items'] == []


def test_io_log_seq_keeps_monotonic_when_redis_seq_reset() -> None:
    """Redis 序号键被清空（调试页清日志）后不得回绕，前端才不会漏行。"""
    c = _coll()
    c._push_io('recv', b'\x01')
    c._fake.store.pop(rk.io_log_seq_key('serial:COM3'), None)
    c._push_io('recv', b'\x02')
    assert [e['seq'] for e in _lpush_entries(c)] == [1, 2]


def test_get_io_log_stream_no_heartbeat_skips_notify(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from module_payload.service.payload_device_service import PayloadDeviceService

    sleeps: list[int] = []

    async def nosleep(*_a, **_k):
        sleeps.append(1)

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.lrange = AsyncMock(return_value=[])
    mgr = MagicMock()
    monkeypatch.setattr(
        PayloadDeviceService, '_is_device_alive', classmethod(lambda cls, _did: True)
    )
    monkeypatch.setattr(
        'module_payload.service.payload_device_service.CollectorProcessManager.instance',
        lambda: mgr,
    )
    monkeypatch.setattr(
        'module_payload.service.payload_device_service.asyncio.sleep', nosleep
    )
    asyncio.run(PayloadDeviceService.get_io_log(redis, 'serial:COM3', kind='stream'))
    mgr.notify_flush_io_stream.assert_not_called()
    assert sleeps == []
    out = asyncio.run(PayloadDeviceService.get_io_log(redis, 'serial:COM3', kind='stream'))
    assert out.get('streamEnabled') is False


def test_flush_stream_io_one_pipeline_for_whole_ring() -> None:
    """整段环缓一次交给封装，一次交互写完。"""
    c = _coll()
    n = 100
    for i in range(n):
        c._push_stream_io('recv', bytes([i & 0xFF]))
    c._flush_stream_io_to_redis()
    assert len(c._fake.batches) == 1
    entries = lpush_entries(c._fake, rk.io_stream_key('serial:COM3'))
    assert [e['seq'] for e in entries] == list(range(1, n + 1))


def test_flush_stream_io_redis_fail_does_not_ack() -> None:
    c = _coll()
    c._push_stream_io('recv', b'\x01')
    c._fake.fail = True
    c._flush_stream_io_to_redis(device_id='serial:COM3', req_id='r-fail')
    c._fake.fail = False
    c._redis.flush()
    acks = [args for name, args in c._fake.executed if name == 'setex']
    assert acks == []


def test_flush_stream_io_empty_still_acks() -> None:
    c = _coll()
    c._flush_stream_io_to_redis(device_id='serial:COM3', req_id='r-empty')
    acks = [args for name, args in c._fake.executed if name == 'setex']
    assert acks[0][0] == rk.io_stream_flush_ack_key('serial:COM3', 'r-empty')


def test_consume_control_flush_only_named_channel() -> None:
    c = _coll(device_id='can:3:0')
    c._stream_recv_on['can:3:0:0'] = True
    c._stream_recv_on['can:3:0:1'] = True
    c._running = True
    c._push_stream_io('recv', b'\x01', device_id='can:3:0:0')
    c._push_stream_io('recv', b'\x02', device_id='can:3:0:1')
    flush_msg = json.dumps(
        {'op': 'flush_io_stream', 'device_id': 'can:3:0:1', 'req_id': 'r1'}
    )
    c._fake.store[rk.ctrl_queue_key('can:3:0')] = [flush_msg]
    c._consume_control()
    keys = {e['_key'] for e in lpush_entries(c._fake)}
    assert rk.io_stream_key('can:3:0:1') in keys
    assert rk.io_stream_key('can:3:0:0') not in keys


def test_stream_recv_off_skips_ring_and_flush() -> None:
    c = _coll()
    c._stream_recv_on['serial:COM3'] = False
    c._push_stream_io('recv', b'\xAA')
    c._flush_stream_io_to_redis()
    assert lpush_entries(c._fake, rk.io_stream_key('serial:COM3')) == []


def test_stream_send_flushes_when_recv_off() -> None:
    c = _coll()
    c._stream_recv_on['serial:COM3'] = False
    c._push_stream_io('send', b'\xBB')
    entries = lpush_entries(c._fake, rk.io_stream_key('serial:COM3'))
    assert [e['hex'] for e in entries] == ['BB']
    assert entries[0]['dir'] == 'send'


def test_set_io_stream_ctrl_toggles_recv() -> None:
    c = _coll()
    c._running = True
    c._stream_recv_on['serial:COM3'] = False
    c._fake.store[rk.ctrl_queue_key('serial:COM3')] = [
        json.dumps({'op': 'set_io_stream', 'device_id': 'serial:COM3', 'enabled': True})
    ]
    c._consume_control()
    assert c._stream_recv_on['serial:COM3'] is True
    c._push_stream_io('recv', b'\x01')
    c._flush_stream_io_to_redis()
    assert [e['hex'] for e in lpush_entries(c._fake, rk.io_stream_key('serial:COM3'))] == ['01']


def test_drop_stale_stream_enable_keeps_other_ctrl() -> None:
    c = _coll()
    key = rk.ctrl_queue_key('serial:COM3')
    c._fake.store[key] = [
        json.dumps({'op': 'set_io_stream', 'device_id': 'serial:COM3', 'enabled': True}),
        json.dumps({'op': 'session_changed'}),
    ]
    c._drop_stale_stream_enable_ctrl()
    left = c._fake.store.get(key) or []
    ops = [json.loads(x).get('op') for x in left]
    assert ops == ['session_changed']


def test_get_io_log_stream_skips_flush_when_off(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from module_payload.service.payload_device_service import PayloadDeviceService

    redis = AsyncMock()

    async def get(k):
        key = k.decode() if isinstance(k, bytes) else str(k)
        if ':heartbeat' in key:
            return b'alive'
        if key.endswith(':io:stream:on'):
            return b'0'
        return None

    redis.get = get
    redis.lrange = AsyncMock(return_value=[])
    mgr = MagicMock()
    monkeypatch.setattr(
        'module_payload.service.payload_device_service.CollectorProcessManager.instance',
        lambda: mgr,
    )
    out = asyncio.run(PayloadDeviceService.get_io_log(redis, 'serial:COM3', kind='stream'))
    mgr.notify_flush_io_stream.assert_not_called()
    assert out['streamEnabled'] is False
    assert 'devices' not in out


def test_get_io_log_stream_includes_devices_when_asked(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from module_payload.service.payload_device_service import PayloadDeviceService

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.lrange = AsyncMock(return_value=[])
    snap = {
        'can': [],
        'serialOpened': [{'deviceId': 'serial:COM3', 'alive': True, 'port': 'COM3'}],
        'netOpened': [],
        'sessions': [{'srcParam': 'serial:COM3', 'source': 'home'}],
    }
    monkeypatch.setattr(
        PayloadDeviceService, 'get_snapshot', AsyncMock(return_value=snap)
    )
    out = asyncio.run(
        PayloadDeviceService.get_io_log(
            redis, 'serial:COM3', kind='stream', include_devices=True
        )
    )
    assert out['devices']['serialOpened'][0]['deviceId'] == 'serial:COM3'
    preview = asyncio.run(
        PayloadDeviceService.get_io_log(
            redis, 'serial:COM3', kind='preview', include_devices=True
        )
    )
    assert 'devices' not in preview


def test_set_io_stream_recv_requires_alive(monkeypatch) -> None:
    from module_payload.service.payload_device_service import PayloadDeviceService

    monkeypatch.setattr(
        PayloadDeviceService, '_is_device_alive', classmethod(lambda cls, _did: False)
    )
    mgr = MagicMock()
    monkeypatch.setattr(
        'module_payload.service.payload_device_service.CollectorProcessManager.instance',
        lambda: mgr,
    )
    out = PayloadDeviceService.set_io_stream_recv('serial:COM3', True)
    assert out == {'deviceId': 'serial:COM3', 'streamEnabled': False}
    mgr.notify_set_io_stream.assert_not_called()


def test_set_io_stream_recv_notifies_when_alive(monkeypatch) -> None:
    from module_payload.service.payload_device_service import PayloadDeviceService

    monkeypatch.setattr(
        PayloadDeviceService, '_is_device_alive', classmethod(lambda cls, _did: True)
    )
    mgr = MagicMock()
    monkeypatch.setattr(
        'module_payload.service.payload_device_service.CollectorProcessManager.instance',
        lambda: mgr,
    )
    out = PayloadDeviceService.set_io_stream_recv('serial:COM3', True)
    assert out == {'deviceId': 'serial:COM3', 'streamEnabled': True}
    mgr.notify_set_io_stream.assert_called_once_with('serial:COM3', True)

