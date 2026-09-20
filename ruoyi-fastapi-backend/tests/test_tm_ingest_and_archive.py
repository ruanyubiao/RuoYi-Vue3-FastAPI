"""遥测批处理、归档事件、分区月份工具。"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

from module_payload.parsers import tm_ingest_batch as tib
from module_payload.parsers.tm_ingest_batch import (
    MAX_BATCH_PER_TYPE,
    PreparedTmFrame,
    TmIngestBatcher,
    _normalize_points,
    assign_unique_ts_ms,
    note_tm_frames,
    process_prepared_async,
    process_prepared_sync,
    reset_tm_fps_meter,
    tm_fps_value,
)
from module_payload.service.payload_telemetry_archive_service import build_archive_event, bytes_to_raw_hex
from module_payload.service.payload_tm_partition_service import (
    PARTITIONED_TABLES,
    _month_start_ms,
    _next_month,
    _partition_name,
)
from redis_fakes import install_write_batch


def _hold_flush_timers():
    """拉长刷写/latest 间隔，避免 0.1s 定时器在全量负载下抢在断言前开火。"""
    return patch.multiple(tib, FLUSH_INTERVAL_S=60.0, LATEST_INTERVAL_S=60.0)


def test_prepared_parse_key() -> None:
    fr = PreparedTmFrame(
        table_key='BIU:FF',
        name='n',
        payload=b'',
        raw_frame=b'',
        src_param='can:3:0:0',
        src_kind='can',
        parser_id='tm_can_biu',
        mgr=None,
        parse_key='',
    )
    assert fr.cfg_parse_key() == 'FF'
    fr.parse_key = 'FD'
    assert fr.cfg_parse_key() == 'FD'


def test_normalize_points() -> None:
    assert _normalize_points({'a': 1, 'b': '2.5', 'c': None, '': 3, 'd': 'x'}) == {
        'a': 1.0,
        'b': 2.5,
    }
    assert _normalize_points({'f': 1.5}) == {'f': 1.5}
    assert _normalize_points({}) == {}
    assert _normalize_points(None) == {}


def _ts_frame(table_key: str, ts_ms: int) -> PreparedTmFrame:
    return PreparedTmFrame(
        table_key=table_key,
        name='t',
        payload=b'\x00',
        raw_frame=b'\x00',
        src_param='s',
        src_kind='serial',
        parser_id='x',
        mgr=None,
        ts_ms=ts_ms,
    )


def test_assign_unique_ts_ms_increments_same_wall_clock() -> None:
    frames = [_ts_frame('D8', 1000) for _ in range(5)]
    assign_unique_ts_ms(frames)
    stamps = [f.ts_ms for f in frames]
    assert stamps == [1000, 1001, 1002, 1003, 1004]


def test_assign_unique_ts_ms_does_not_run_ahead_of_now(monkeypatch) -> None:
    """同毫秒突发不得把横轴推进未来；否则 600Hz 曲线会比电脑时间快数分钟。"""
    from module_payload.parsers import tm_ingest_batch as tib

    now_ms = 1_700_000_000_000
    monkeypatch.setattr(tib.time, 'time', lambda: now_ms / 1000.0)
    clock: dict[str, float] = {}
    burst = [_ts_frame('D9V17', now_ms) for _ in range(200)]
    assign_unique_ts_ms(burst, clock)
    assert max(float(f.ts_ms) for f in burst) < now_ms + 1
    assert len({float(f.ts_ms) for f in burst}) == 200

    later_ms = now_ms + 50
    monkeypatch.setattr(tib.time, 'time', lambda: later_ms / 1000.0)
    later = [_ts_frame('D9V17', later_ms) for _ in range(3)]
    assign_unique_ts_ms(later, clock)
    assert later[0].ts_ms == later_ms
    assert max(float(f.ts_ms) for f in later) < later_ms + 1


def test_latest_loop_does_not_republish_after_curve_mutates_ts() -> None:
    """曲线 assign_unique_ts_ms 改写同一帧 ts 后，latest 不得再推送新 dataId。"""
    from module_payload.parsers import tm_ingest_batch as tib

    class _Mgr:
        def parse(self, key, payload, **_kwargs):
            return [{'id': 'A', 'value': 1, 'show': '1'}]

        def parse_calc(self, key, payload, **_kwargs):
            return {'A': 1.0}

    frame = PreparedTmFrame(
        table_key='D9V17',
        name='fast',
        payload=b'\x00' * 16,
        raw_frame=b'\xeb\xd9' + b'\x00' * 18,
        src_param='serial:COM3',
        src_kind='serial',
        parser_id='tm_xl_camera_v17',
        mgr=_Mgr(),
        ts_ms=1_000_000,
    )
    redis = MagicMock()
    pipe = MagicMock()
    redis.pipeline.return_value = pipe
    pipe.set.return_value = pipe
    pipe.execute.return_value = []

    writes: list[int] = []

    def _capture(redis_client, fr, *, ts_ms=None):
        use = int(ts_ms if ts_ms is not None else fr.ts_ms)
        writes.append(use)
        return {'dataId': use}

    batcher = TmIngestBatcher()
    batcher._latest_stop.set()  # 不跑后台循环，手动调一次逻辑
    with patch.object(tib, '_write_latest_from_frame', side_effect=_capture):
        batcher.push(redis, frame, immediate=False)
        # 模拟曲线线程改写同一对象的 ts_ms
        frame.ts_ms = 1_000_500
        # 手动执行 latest 决策（与 _latest_loop 相同）
        key = 'D9V17'
        snap = batcher._latest_snap[key]
        fid, ts_ms = snap
        assert batcher._latest_written_id.get(key) != fid
        tib._write_latest_from_frame(redis, frame, ts_ms=ts_ms)
        batcher._latest_written_id[key] = fid
        # 再次：同一帧不应再写
        if batcher._latest_written_id.get(key) != fid:
            tib._write_latest_from_frame(redis, frame, ts_ms=frame.ts_ms)

    assert writes == [1_000_000]


def test_process_prepared_sync_keeps_all_frames() -> None:
    parsed = {'n': 0}

    class _Mgr:
        def parse_calc(self, key, payload, **_kwargs):
            parsed['n'] += 1
            return {'A': 1.0}

        def parse(self, key, payload, **_kwargs):
            return []

    mgr = _Mgr()
    frames = [
        PreparedTmFrame(
            table_key='D8',
            name=str(i),
            payload=b'\x00',
            raw_frame=b'\x00',
            src_param='serial:COM4',
            src_kind='serial',
            parser_id='tm_xl_camera',
            mgr=mgr,
        )
        for i in range(50)
    ]
    redis = MagicMock()
    pipe = MagicMock()
    redis.pipeline.return_value = pipe
    pipe.zadd.return_value = pipe
    pipe.zremrangebyrank.return_value = pipe
    pipe.execute.return_value = []
    install_write_batch(redis, pipe)
    process_prepared_sync(redis, frames)
    assert parsed['n'] == 50
    assert redis.lpush.call_count == 0
    assert len({f.ts_ms for f in frames}) == 50
    assert pipe.zadd.call_count == 1


def test_process_prepared_sync_archives_can_only() -> None:
    parsed = {'n': 0}

    class _Mgr:
        def parse_calc(self, key, payload, **_kwargs):
            parsed['n'] += 1
            return {'A': 1.0}

        def parse(self, key, payload, **_kwargs):
            return []

    mgr = _Mgr()
    frames = [
        PreparedTmFrame(
            table_key='BIU:FF',
            name=str(i),
            payload=b'\x00',
            raw_frame=b'\x00',
            src_param='can:3:0:0',
            src_kind='can',
            parser_id='tm_can_biu',
            mgr=mgr,
        )
        for i in range(10)
    ]
    redis = MagicMock()
    pipe = MagicMock()
    redis.pipeline.return_value = pipe
    pipe.zadd.return_value = pipe
    pipe.zremrangebyrank.return_value = pipe
    pipe.execute.return_value = []
    install_write_batch(redis, pipe)
    process_prepared_sync(redis, frames)
    assert parsed['n'] == 10
    assert redis.lpush.call_count == 10


def test_process_prepared_sync_mixed_src_archives_can_only() -> None:
    class _Mgr:
        def parse_calc(self, key, payload, **_kwargs):
            return {'A': 1.0}

        def parse(self, key, payload, **_kwargs):
            return []

    mgr = _Mgr()

    def _fr(i: int, *, src_kind: str, src_param: str, parser_id: str, table_key: str) -> PreparedTmFrame:
        return PreparedTmFrame(
            table_key=table_key,
            name=str(i),
            payload=b'\x00',
            raw_frame=b'\x00',
            src_param=src_param,
            src_kind=src_kind,
            parser_id=parser_id,
            mgr=mgr,
        )

    frames = [
        _fr(0, src_kind='serial', src_param='serial:COM3', parser_id='tm_xl_camera', table_key='D8'),
        _fr(1, src_kind='can', src_param='can:3:0:0', parser_id='tm_can_biu', table_key='BIU:FF'),
        _fr(2, src_kind='udp', src_param='udp:127.0.0.1:9', parser_id='tm_xl_board', table_key='ZK'),
    ]
    redis = MagicMock()
    pipe = MagicMock()
    redis.pipeline.return_value = pipe
    pipe.zadd.return_value = pipe
    pipe.zremrangebyrank.return_value = pipe
    pipe.execute.return_value = []
    install_write_batch(redis, pipe)
    process_prepared_sync(redis, frames)
    assert redis.lpush.call_count == 1
    assert pipe.zadd.call_count == 3


def _curve_redis() -> tuple[MagicMock, MagicMock]:
    redis = MagicMock()
    pipe = MagicMock()
    redis.pipeline.return_value = pipe
    pipe.zadd.return_value = pipe
    pipe.zremrangebyrank.return_value = pipe
    pipe.set.return_value = pipe
    pipe.setex.return_value = pipe
    pipe.execute.return_value = []
    install_write_batch(redis, pipe)
    return redis, pipe


def test_push_many_does_not_parse_until_flush() -> None:
    parsed = {'calc': 0}

    class _Mgr:
        def parse_calc(self, key, payload, **_kwargs):
            parsed['calc'] += 1
            return {'A': 1.0}

        def parse(self, key, payload, **_kwargs):
            return []

    redis, pipe = _curve_redis()
    mgr = _Mgr()
    frames = [
        PreparedTmFrame(
            table_key='D8',
            name=str(i),
            payload=b'\x00',
            raw_frame=b'\x00',
            src_param='serial:COM4',
            src_kind='serial',
            parser_id='tm_xl_camera',
            mgr=mgr,
            ts_ms=2000,
        )
        for i in range(8)
    ]
    with _hold_flush_timers():
        batcher = TmIngestBatcher()
        batcher.push_many(redis, frames)
        assert parsed['calc'] == 0
        batcher.flush(redis)
    assert parsed['calc'] == 8
    assert pipe.zadd.call_count == 1


def test_push_many_overflow_flushes_all_not_drop() -> None:
    parsed = {'n': 0}

    class _Mgr:
        def parse_calc(self, key, payload, **_kwargs):
            parsed['n'] += 1
            return {'A': 1.0}

        def parse(self, key, payload, **_kwargs):
            return []

    redis, _pipe = _curve_redis()
    mgr = _Mgr()
    frames = [
        PreparedTmFrame(
            table_key='D8',
            name=str(i),
            payload=b'\x00',
            raw_frame=b'\x00',
            src_param='serial:COM4',
            src_kind='serial',
            parser_id='tm_xl_camera',
            mgr=mgr,
        )
        for i in range(MAX_BATCH_PER_TYPE + 3)
    ]
    with _hold_flush_timers():
        batcher = TmIngestBatcher()
        batcher.push_many(redis, frames)
        deadline = time.monotonic() + 2.0
        while parsed['n'] < MAX_BATCH_PER_TYPE and time.monotonic() < deadline:
            time.sleep(0.01)
        assert parsed['n'] == MAX_BATCH_PER_TYPE
        batcher.flush(redis)
    assert parsed['n'] == MAX_BATCH_PER_TYPE + 3


def test_push_does_not_parse_on_collector_thread() -> None:
    parsed = {'parse': 0, 'calc': 0}

    class _Mgr:
        def parse_calc(self, key, payload, **_kwargs):
            parsed['calc'] += 1
            return {'A': 1.0}

        def parse(self, key, payload, **_kwargs):
            parsed['parse'] += 1
            return []

    redis = MagicMock()
    pipe = MagicMock()
    redis.pipeline.return_value = pipe
    pipe.zadd.return_value = pipe
    pipe.zremrangebyrank.return_value = pipe
    pipe.set.return_value = pipe
    pipe.execute.return_value = []
    install_write_batch(redis, pipe)
    mgr = _Mgr()
    with _hold_flush_timers():
        batcher = TmIngestBatcher()
        for i in range(10):
            batcher.push(
                redis,
                PreparedTmFrame(
                    table_key='D8',
                    name=str(i),
                    payload=b'\x00',
                    raw_frame=b'\x00',
                    src_param='serial:COM4',
                    src_kind='serial',
                    parser_id='tm_xl_camera',
                    mgr=mgr,
                    ts_ms=2000,
                ),
            )
        assert parsed['parse'] == 0
        assert parsed['calc'] == 0
        batcher.flush(redis)
    assert parsed['calc'] == 10
    assert parsed['parse'] == 0
    assert pipe.zadd.call_count == 1


def test_batcher_overflow_flushes_all_not_drop() -> None:
    parsed = {'n': 0}

    class _Mgr:
        def parse_calc(self, key, payload, **_kwargs):
            parsed['n'] += 1
            return {'A': 1.0}

        def parse(self, key, payload, **_kwargs):
            return []

    redis = MagicMock()
    pipe = MagicMock()
    redis.pipeline.return_value = pipe
    pipe.zadd.return_value = pipe
    pipe.zremrangebyrank.return_value = pipe
    pipe.execute.return_value = []
    batcher = TmIngestBatcher()
    mgr = _Mgr()
    for i in range(MAX_BATCH_PER_TYPE):
        batcher.push(
            redis,
            PreparedTmFrame(
                table_key='D8',
                name=str(i),
                payload=b'\x00',
                raw_frame=b'\x00',
                src_param='serial:COM4',
                src_kind='serial',
                parser_id='tm_xl_camera',
                mgr=mgr,
            ),
        )
    deadline = time.monotonic() + 2.0
    while parsed['n'] < MAX_BATCH_PER_TYPE and time.monotonic() < deadline:
        time.sleep(0.01)
    assert parsed['n'] == MAX_BATCH_PER_TYPE


def test_build_archive_event() -> None:
    ev = build_archive_event(
        ts_ms=1000,
        raw_frame=b'\xaa\xbb',
        points={'J1': 1.5, None: 1, 'skip': None},
        data_sub='ff',
        src_param='can:3:0:0',
        name='快遥',
    )
    assert ev['data_sub'] == 'FF'
    assert ev['raw_hex'] == 'AA BB'
    assert ev['points'] == {'J1': 1.5}
    assert ev['src_kind'] == 'can'
    assert ev['parsed_json']['name'] == '快遥'
    assert bytes_to_raw_hex(None) == ''
    assert bytes_to_raw_hex(b'') == ''
    assert bytes_to_raw_hex(b'\xaa\xbb') == 'AA BB'
    assert bytes_to_raw_hex(memoryview(b'\x01\x02')) == '01 02'


def test_partition_month_helpers() -> None:
    assert _partition_name(2026, 8) == 'p202608'
    assert _next_month(2026, 12) == (2027, 1)
    assert _next_month(2026, 1) == (2026, 2)
    assert _month_start_ms(2026, 1) < _month_start_ms(2026, 2)
    assert PARTITIONED_TABLES == ('payload_tm_frame', 'payload_tx_log')


def test_enqueue_sync_lpush() -> None:
    from module_payload.service.payload_telemetry_archive_service import PayloadTelemetryArchiveService

    redis = MagicMock()
    PayloadTelemetryArchiveService.enqueue_sync(
        redis, {'ts_ms': 1, 'points': {}, 'src_kind': 'can', 'src_param': 'can:3:0:0', 'parser_id': 'tm_can_biu'}
    )
    redis.write_batch.assert_called()
    redis.reset_mock()
    PayloadTelemetryArchiveService.enqueue_sync(
        redis,
        {
            'ts_ms': 1,
            'points': {},
            'src_kind': 'serial',
            'src_param': 'serial:COM3',
            'parser_id': 'tm_xl_camera',
        },
    )
    redis.write_batch.assert_not_called()
    redis.reset_mock()
    PayloadTelemetryArchiveService.enqueue_sync(
        redis,
        {
            'ts_ms': 1,
            'points': {},
            'src_kind': 'udp',
            'src_param': 'udp:127.0.0.1:9',
            'parser_id': 'tm_xl_board',
        },
    )
    redis.write_batch.assert_not_called()
    redis.reset_mock()
    PayloadTelemetryArchiveService.enqueue_sync(
        redis,
        {
            'ts_ms': 1,
            'points': {},
            'src_kind': 'tcp',
            'src_param': 'tcp:10.0.0.1:8',
            'parser_id': 'tm_xl_board',
        },
    )
    redis.write_batch.assert_not_called()
    redis.reset_mock()
    PayloadTelemetryArchiveService.enqueue_sync(
        redis,
        {
            'ts_ms': 1,
            'points': {},
            'src_kind': 'http',
            'src_param': 'http:devtest',
            'parser_id': 'tm_xl_camera',
        },
    )
    redis.write_batch.assert_not_called()
    redis.reset_mock()
    PayloadTelemetryArchiveService.enqueue_sync(
        redis,
        {
            'ts_ms': 1,
            'points': {},
            'src_kind': 'http',
            'src_param': 'http:devtest',
            'parser_id': 'tm_can_xl',
        },
    )
    redis.write_batch.assert_called()


class _CalcMgr:
    def parse_calc(self, key, payload, **_kwargs):
        return {'A': 1.0}

    def parse(self, key, payload, **_kwargs):
        return [{'id': 'A', 'value': 1.0}]


def _frames_for(src_kind: str, src_param: str, parser_id: str, table_key: str, n: int = 2) -> list[PreparedTmFrame]:
    mgr = _CalcMgr()
    return [
        PreparedTmFrame(
            table_key=table_key,
            name=str(i),
            payload=b'\x00',
            raw_frame=b'\x11',
            src_param=src_param,
            src_kind=src_kind,
            parser_id=parser_id,
            mgr=mgr,
            ts_ms=1_700_000_000_000 + i,
        )
        for i in range(n)
    ]


def _async_curve_redis() -> tuple[AsyncMock, MagicMock]:
    redis = AsyncMock()
    pipe = MagicMock()
    pipe.zadd.return_value = pipe
    pipe.zremrangebyrank.return_value = pipe
    pipe.execute = AsyncMock(return_value=[])
    redis.pipeline = MagicMock(return_value=pipe)
    redis.lpush = AsyncMock()
    redis.set = AsyncMock()
    return redis, pipe


def _zadd_pairs(pipe: MagicMock) -> list[tuple[str, dict]]:
    return [(c.args[0], c.args[1]) for c in pipe.zadd.call_args_list]


def _archive_subs(redis: MagicMock | AsyncMock) -> list[str]:
    subs: list[str] = []
    for c in redis.lpush.call_args_list:
        dumped = c.args[1]
        event = json.loads(dumped)
        subs.append(event['data_sub'])
    return subs


def test_process_prepared_async_archives_can_only() -> None:
    frames = _frames_for('can', 'can:3:0:0', 'tm_can_biu', 'BIU:FF', n=10)
    redis, _pipe = _async_curve_redis()
    with patch(
        'module_payload.redis_store.set_telemetry',
        new=AsyncMock(return_value={'dataId': 1}),
    ):
        asyncio.run(process_prepared_async(redis, frames))
    assert redis.lpush.await_count == 10


def test_process_prepared_async_mixed_src_archives_can_only() -> None:
    mgr = _CalcMgr()

    def _fr(i: int, **kw: str) -> PreparedTmFrame:
        return PreparedTmFrame(
            table_key=kw['table_key'],
            name=str(i),
            payload=b'\x00',
            raw_frame=b'\x00',
            src_param=kw['src_param'],
            src_kind=kw['src_kind'],
            parser_id=kw['parser_id'],
            mgr=mgr,
            ts_ms=1_700_000_000_000 + i,
        )

    frames = [
        _fr(0, src_kind='serial', src_param='serial:COM3', parser_id='tm_xl_camera', table_key='D8'),
        _fr(1, src_kind='can', src_param='can:3:0:0', parser_id='tm_can_biu', table_key='BIU:FF'),
        _fr(2, src_kind='udp', src_param='udp:127.0.0.1:9', parser_id='tm_xl_board', table_key='ZK'),
    ]
    redis, pipe = _async_curve_redis()
    with patch(
        'module_payload.redis_store.set_telemetry',
        new=AsyncMock(return_value={'dataId': 1}),
    ):
        asyncio.run(process_prepared_async(redis, frames))
    assert redis.lpush.await_count == 1
    assert pipe.zadd.call_count == 3


def test_process_prepared_sync_async_curve_and_archive_match() -> None:
    def _clone() -> list[PreparedTmFrame]:
        return _frames_for('can', 'can:3:0:0', 'tm_can_biu', 'BIU:FF', n=3)

    sync_frames = _clone()
    async_frames = _clone()
    sync_redis, sync_pipe = _curve_redis()
    async_redis, async_pipe = _async_curve_redis()
    process_prepared_sync(sync_redis, sync_frames, write_latest=False)
    with patch(
        'module_payload.redis_store.set_telemetry',
        new=AsyncMock(return_value={'dataId': 1}),
    ):
        asyncio.run(process_prepared_async(async_redis, async_frames))
    assert _zadd_pairs(sync_pipe) == _zadd_pairs(async_pipe)
    assert _archive_subs(sync_redis) == _archive_subs(async_redis)
    assert len(_archive_subs(sync_redis)) == 3


def test_process_prepared_latest_fork() -> None:
    parsed = {'n': 0}

    class _Mgr:
        def parse_calc(self, key, payload, **_kwargs):
            return {'A': 1.0}

        def parse(self, key, payload, **_kwargs):
            parsed['n'] += 1
            return [{'id': 'A', 'value': 1.0}]

    def _one() -> list[PreparedTmFrame]:
        return [
            PreparedTmFrame(
                table_key='D8',
                name='n',
                payload=b'\x00',
                raw_frame=b'\x00',
                src_param='serial:COM4',
                src_kind='serial',
                parser_id='tm_xl_camera',
                mgr=_Mgr(),
                ts_ms=1_700_000_000_000,
            )
        ]

    redis, _ = _curve_redis()
    process_prepared_sync(redis, _one(), write_latest=False)
    assert parsed['n'] == 0
    process_prepared_sync(redis, _one(), write_latest=True)
    assert parsed['n'] == 1

    aredis, _ = _async_curve_redis()
    set_tm = AsyncMock(return_value={'dataId': 9})
    with patch('module_payload.redis_store.set_telemetry', new=set_tm):
        asyncio.run(process_prepared_async(aredis, _one()))
    set_tm.assert_awaited_once()
    assert parsed['n'] == 2


def test_tm_fps_meter_per_table_type() -> None:
    """EB D9（D9V17）与 EB 90 D8 各自计数，窗口外的点不计入。"""
    reset_tm_fps_meter()
    t0 = 1000.0
    note_tm_frames('D8', 1, now=t0 - 1.1)
    note_tm_frames('D8', 10, now=t0)
    note_tm_frames('D9V17', 3, now=t0)
    note_tm_frames('d8', 2, now=t0)
    assert tm_fps_value('D8', now=t0) == 12
    assert tm_fps_value('D9V17', now=t0) == 3
    assert tm_fps_value('D8', now=t0 + 1.01) == 0
    reset_tm_fps_meter()
    assert tm_fps_value('D8') == 0


def test_process_prepared_sync_writes_fps() -> None:
    class _Mgr:
        def parse_calc(self, key, payload, **_kwargs):
            return {'A': 1.0}

        def parse(self, key, payload, **_kwargs):
            return []

    reset_tm_fps_meter()
    note_tm_frames('D8', 5)
    frames = [
        PreparedTmFrame(
            table_key='D8',
            name='n',
            payload=b'\x00',
            raw_frame=b'\x00',
            src_param='serial:COM4',
            src_kind='serial',
            parser_id='tm_xl_camera',
            mgr=_Mgr(),
        )
    ]
    redis, pipe = _curve_redis()
    process_prepared_sync(redis, frames, write_latest=False)
    assert pipe.setex.call_count == 1
    args = pipe.setex.call_args.args
    assert args[0] == 'payload:tm:D8:fps'
    assert args[1] == 2
    assert args[2] == '5'


def test_push_counts_receive_fps() -> None:
    class _Mgr:
        def parse_calc(self, key, payload, **_kwargs):
            return {'A': 1.0}

        def parse(self, key, payload, **_kwargs):
            return []

    reset_tm_fps_meter()
    redis, _pipe = _curve_redis()
    batcher = TmIngestBatcher()
    batcher._latest_stop.set()
    frame = PreparedTmFrame(
        table_key='D9V17',
        name='fast',
        payload=b'\x00',
        raw_frame=b'\xeb\xd9',
        src_param='serial:COM3',
        src_kind='serial',
        parser_id='tm_xl_camera_v17',
        mgr=_Mgr(),
    )
    batcher.push(redis, frame, immediate=False)
    assert tm_fps_value('D9V17') == 1
    assert tm_fps_value('D8') == 0
    batcher.push_many(
        redis,
        [
            PreparedTmFrame(
                table_key='D8',
                name='slow',
                payload=b'\x00',
                raw_frame=b'\xeb\x90\xd8',
                src_param='serial:COM4',
                src_kind='serial',
                parser_id='tm_xl_camera',
                mgr=_Mgr(),
            )
            for _ in range(4)
        ],
        immediate=False,
    )
    assert tm_fps_value('D8') == 4
    assert tm_fps_value('D9V17') == 1
    batcher.flush(redis)
    reset_tm_fps_meter()

