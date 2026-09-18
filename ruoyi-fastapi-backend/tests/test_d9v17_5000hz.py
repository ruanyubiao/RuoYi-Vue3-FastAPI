"""相机 V1.7 快遥 D9：5000 帧/秒曲线全量解析写入。

表格 latest 仍 0.5s 采样，不在此压。曲线路径按采集实际节拍：满 200 帧交给
``process_prepared_sync``（每秒约 25 批），每字段一条合并 ZADD。
"""

from __future__ import annotations

import time

from module_payload import redis_keys as rk
from module_payload.constants import TM_FLUSH_INTERVAL_S
from module_payload.parsers.tm_ingest_batch import (
    MAX_BATCH_PER_TYPE,
    process_prepared_sync,
    reset_tm_fps_meter,
)
from module_payload.parsers.xl_camera_tm_v17 import XlCameraTmV17Ingest, reset_xl_camera_tm_v17_mgr
from redis_fakes import executed_ops, fake_collector_redis

# 地检抓包：与 600Hz 用例同一帧
D9V17_HEX = 'EB D9 02 AA AA 01 FF FF FF FF 00 00 0B 2B 00 0E A7 01 2C 6B'
D9V17_RAW = bytes.fromhex(D9V17_HEX)
N_FRAMES = 5000
BATCH = MAX_BATCH_PER_TYPE  # 200：采集缓冲满批即交给曲线线程


def setup_function() -> None:
    reset_xl_camera_tm_v17_mgr()
    reset_tm_fps_meter()


def teardown_function() -> None:
    reset_xl_camera_tm_v17_mgr()
    reset_tm_fps_meter()


def _prepared_5000() -> list:
    frames = []
    for _ in range(N_FRAMES):
        frames.extend(XlCameraTmV17Ingest._collect_prepared(D9V17_RAW, src_param='serial:COM4'))
    assert len(frames) == N_FRAMES
    return frames


def test_d9v17_parse_calc_field_count() -> None:
    """样本帧 parse_calc 应对上配置里的快遥字段（39 个 CAMF）。"""
    frames = XlCameraTmV17Ingest._collect_prepared(D9V17_RAW, src_param='serial:COM4')
    assert len(frames) == 1
    fr = frames[0]
    points = fr.mgr.parse_calc(fr.cfg_parse_key(), fr.payload, big_endian_buffer=fr.big_endian_buffer)
    assert fr.table_key == 'D9V17'
    assert len(points) == 39
    assert 'CAMF001' in points
    assert 'CAMF039' in points


def test_d9v17_5000_curve_batches_keep_up_under_one_second() -> None:
    """模拟曲线线程：25×200 帧 parse_calc + 合并 ZADD + 刷出，1s 内完成才跟得上 5000Hz。"""
    frames = _prepared_5000()
    n_fields = len(
        frames[0].mgr.parse_calc(
            frames[0].cfg_parse_key(),
            frames[0].payload,
            big_endian_buffer=frames[0].big_endian_buffer,
        )
        or {}
    )
    redis, fake = fake_collector_redis()
    t0 = time.perf_counter()
    for i in range(0, N_FRAMES, BATCH):
        process_prepared_sync(redis, frames[i : i + BATCH], write_latest=False)
    redis.flush()
    elapsed = time.perf_counter() - t0

    zadds = executed_ops(fake, 'zadd')
    camf001_n = sum(
        len(args[1]) for args in zadds if args[0] == rk.curve_latest_key('D9V17', 'CAMF001')
    )
    assert camf001_n == N_FRAMES
    # 每批每字段一条 ZADD；另有 fps SETEX，不含裁剪
    assert len(zadds) == n_fields * (N_FRAMES // BATCH)
    assert executed_ops(fake, 'zremrangebyrank') == []
    assert elapsed < 1.0, (
        f'5000 帧曲线批处理耗时 {elapsed:.3f}s，应 < 1s 才能跟上 5000Hz 接收'
        f'（{n_fields} 字段 × {N_FRAMES // BATCH} 批，FLUSH={TM_FLUSH_INTERVAL_S}s）'
    )


LIVE_TABLE_5000 = '_PERF5000'


def test_d9v17_5000_live_redis_write() -> None:
    """真 Redis：5000 帧分批曲线写入；写隔离表，测完删除。"""
    from redis_fakes import live_collector_redis_or_skip

    frames = _prepared_5000()
    points = (
        frames[0].mgr.parse_calc(
            frames[0].cfg_parse_key(),
            frames[0].payload,
            big_endian_buffer=frames[0].big_endian_buffer,
        )
        or {}
    )
    fields = list(points)
    n_fields = len(fields)
    for fr in frames:
        if not fr.parse_key:
            fr.parse_key = fr.cfg_parse_key()
        fr.table_key = LIVE_TABLE_5000
    redis, raw = live_collector_redis_or_skip()
    keys = [rk.curve_latest_key(LIVE_TABLE_5000, fid) for fid in fields]
    keys.append(rk.telemetry_fps_key(LIVE_TABLE_5000))
    try:
        t0 = time.perf_counter()
        for i in range(0, N_FRAMES, BATCH):
            process_prepared_sync(redis, frames[i : i + BATCH], write_latest=False)
        assert redis.flush() is True
        elapsed = time.perf_counter() - t0
        n = int(raw.zcard(rk.curve_latest_key(LIVE_TABLE_5000, 'CAMF001')) or 0)
        assert n == N_FRAMES
        assert elapsed < 2.0, f'真 Redis 5000 帧耗时 {elapsed:.3f}s（{n_fields} 字段）'
    finally:
        if keys:
            raw.delete(*keys)
        redis.close()
