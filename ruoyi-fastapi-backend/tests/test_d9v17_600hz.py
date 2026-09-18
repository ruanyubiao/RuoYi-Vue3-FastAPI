"""相机 V1.7 快遥 D9：600 帧/秒解析写入（开窗 80 时的频率）。"""

from __future__ import annotations

import time

from module_payload import redis_keys as rk
from module_payload.collectors import redis_cmd_helper as redis_cmd
from module_payload.parsers.tm_ingest_batch import process_prepared_sync
from module_payload.parsers.xl_camera_tm_v17 import XlCameraTmV17Ingest, reset_xl_camera_tm_v17_mgr
from redis_fakes import executed_ops, fake_collector_redis

# 地检抓包：开窗 80 时 D9 快遥
D9V17_HEX = 'EB D9 02 AA AA 01 FF FF FF FF 00 00 0B 2B 00 0E A7 01 2C 6B'
D9V17_RAW = bytes.fromhex(D9V17_HEX)
N_FRAMES = 600


def setup_function() -> None:
    reset_xl_camera_tm_v17_mgr()


def teardown_function() -> None:
    reset_xl_camera_tm_v17_mgr()


def test_helper_curves_600_frames_one_zadd_per_field() -> None:
    """600 帧同一批交给 helper，每个字段只生成一条 ZADD，不含裁剪。"""
    rows = [('D9V17', {'CAMF001': float(i), 'CAMF004': 1.0}, 1_700_000_000_000 + i) for i in range(N_FRAMES)]
    ops = redis_cmd.curves(rows)
    assert [op.cmd for op in ops] == ['zadd', 'zadd']
    camf001 = next(op.args[1] for op in ops if op.args[0] == rk.curve_latest_key('D9V17', 'CAMF001'))
    assert len(camf001) == N_FRAMES


def test_d9v17_600_parse_and_write_under_one_second() -> None:
    """拆帧 + parse_calc + write_batch + 刷出，600 帧应在 1s 内完成。"""
    parsed = XlCameraTmV17Ingest.parse_bytes(D9V17_RAW)
    assert parsed.table_key == 'D9V17'

    redis, fake = fake_collector_redis()
    t0 = time.perf_counter()
    for _ in range(N_FRAMES):
        XlCameraTmV17Ingest.ingest_bytes_sync(
            redis,
            D9V17_RAW,
            src_param='serial:COM4',
            immediate=True,
        )
    redis.flush()
    elapsed = time.perf_counter() - t0

    zadds = executed_ops(fake, 'zadd')
    assert zadds, '应写出曲线 ZADD'
    assert any(rk.curve_latest_key('D9V17', 'CAMF001') == args[0] for args in zadds)
    assert executed_ops(fake, 'zremrangebyrank') == []
    assert elapsed < 1.0, f'600 帧解析写入耗时 {elapsed:.3f}s，应 < 1s'


def test_d9v17_600_curve_thread_batch_is_merged() -> None:
    """曲线线程一次处理 600 帧时，每个字段一条 ZADD（成员 600 个）。"""
    frames = []
    for _ in range(N_FRAMES):
        frames.extend(XlCameraTmV17Ingest._collect_prepared(D9V17_RAW, src_param='serial:COM4'))
    assert len(frames) == N_FRAMES

    redis, fake = fake_collector_redis()
    t0 = time.perf_counter()
    process_prepared_sync(redis, frames, write_latest=False)
    redis.flush()
    elapsed = time.perf_counter() - t0

    zadds = executed_ops(fake, 'zadd')
    assert zadds
    members = next(args[1] for args in zadds if args[0] == rk.curve_latest_key('D9V17', 'CAMF001'))
    assert len(members) == N_FRAMES
    assert executed_ops(fake, 'zremrangebyrank') == []
    assert elapsed < 1.0, f'曲线线程 600 帧耗时 {elapsed:.3f}s，应 < 1s'


LIVE_TABLE_600 = '_PERF600'


def test_d9v17_600_live_redis_write() -> None:
    """真 Redis：600 帧曲线 ZADD 成员数与墙钟；写隔离表，测完删除。"""
    from redis_fakes import live_collector_redis_or_skip

    redis, raw = live_collector_redis_or_skip()
    frames = []
    for _ in range(N_FRAMES):
        frames.extend(XlCameraTmV17Ingest._collect_prepared(D9V17_RAW, src_param='serial:COM4'))
    points = frames[0].mgr.parse_calc(
        frames[0].cfg_parse_key(),
        frames[0].payload,
        big_endian_buffer=frames[0].big_endian_buffer,
    ) or {}
    fields = list(points)
    for fr in frames:
        if not fr.parse_key:
            fr.parse_key = fr.cfg_parse_key()
        fr.table_key = LIVE_TABLE_600
    keys = [rk.curve_latest_key(LIVE_TABLE_600, fid) for fid in fields]
    keys.append(rk.telemetry_fps_key(LIVE_TABLE_600))
    try:
        t0 = time.perf_counter()
        process_prepared_sync(redis, frames, write_latest=False)
        assert redis.flush() is True
        elapsed = time.perf_counter() - t0
        n = int(raw.zcard(rk.curve_latest_key(LIVE_TABLE_600, 'CAMF001')) or 0)
        assert n == N_FRAMES
        assert elapsed < 2.0, f'真 Redis 600 帧耗时 {elapsed:.3f}s'
    finally:
        if keys:
            raw.delete(*keys)
        redis.close()
