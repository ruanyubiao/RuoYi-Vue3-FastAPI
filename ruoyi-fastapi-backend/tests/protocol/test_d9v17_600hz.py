"""相机 V1.7 快遥 D9 在开窗 80 时的写入能力。

这个速率是 600 帧/秒。样本是一帧地检实采（表键 D9V17）。
四条用例锁同一件事：600 帧曲线打成一条 ZADD，不裁剪旧点，并且写得完。

- ``curves``：600 个点合成一条 ZADD，成员里的帧数是 600。
- ``ingest_bytes_sync``：逐帧拆帧、解析、写入、刷出。安静机器应在 1 秒内；
  整轮 pytest 墙钟会晃到 1.5–2.5 秒，所以套件门槛是 4 秒
  （``PGT_PERF_SCALE`` 和覆盖率插桩再乘）。
- ``process_prepared_sync``：曲线线程一次吃下 600 帧，仍是一条 ZADD，1 秒内完成。
- 真 Redis：同样一批写入隔离键 ``_PERF600``，成员数为 1，测完删除。
  本机没有 Redis 时跳过。
"""

from __future__ import annotations

import os
import sys
import time

from module_payload import redis_keys as rk
from module_payload.collectors import redis_cmd_helper as redis_cmd
from module_payload.tm.tm_ingest_batch import process_prepared_sync
from module_payload.protocol.xl.camera_v17.tm import XlCameraTmV17Ingest, reset_xl_camera_tm_v17_mgr
from module_payload.store.curve_blob import parse_prefix
from redis_fakes import executed_ops, fake_collector_redis

# 地检抓包：开窗 80 时 D9 快遥
D9V17_HEX = 'EB D9 02 AA AA 01 FF FF FF FF 00 00 0B 2B 00 0E A7 01 2C 6B'
D9V17_RAW = bytes.fromhex(D9V17_HEX)
N_FRAMES = 600


def setup_function() -> None:
    reset_xl_camera_tm_v17_mgr()


def teardown_function() -> None:
    reset_xl_camera_tm_v17_mgr()


def test_helper_curves_600_frames_one_zadd_per_table() -> None:
    """600 帧同一批交给 helper，整表只生成一条 ZADD，不含裁剪。"""
    rows = [('D9V17', {'CAMF001': float(i), 'CAMF004': 1.0}, 1_700_000_000_000 + i) for i in range(N_FRAMES)]
    ops = redis_cmd.curves(rows)
    assert [op.cmd for op in ops] == ['zadd']
    mapping = ops[0].args[1]
    assert ops[0].args[0] == rk.curve_latest_key('D9V17')
    assert len(mapping) == 1
    parsed = parse_prefix(next(iter(mapping)))
    assert parsed is not None
    assert parsed[1] == N_FRAMES


def _perf_budget(seconds: float) -> float:
    """慢机 / CI 用 PGT_PERF_SCALE；pytest --cov 插桩再乘 2。"""
    cov_mod = sys.modules.get('coverage')
    slow = 1.0
    if cov_mod is not None and getattr(cov_mod.Coverage, 'current', lambda: None)() is not None:
        slow = 2.0
    return seconds * float(os.environ.get('PGT_PERF_SCALE', '1')) * slow


def test_d9v17_600_parse_and_write_under_one_second() -> None:
    """拆帧 + parse_calc + write_batch + 刷出。安静机器应在 1s 内；整轮套件按 4s。"""
    parsed = XlCameraTmV17Ingest.parse_bytes(D9V17_RAW)
    assert parsed.table_key == 'D9V17'

    warm_redis, _warm_fake = fake_collector_redis()
    XlCameraTmV17Ingest.ingest_bytes_sync(
        warm_redis,
        D9V17_RAW,
        src_param='serial:COM4',
        immediate=True,
    )
    warm_redis.flush()

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
    assert any(rk.curve_latest_key('D9V17') == args[0] for args in zadds)
    assert executed_ops(fake, 'zremrangebyrank') == []
    # 整轮 pytest 里这条逐帧路径在 1.5s–2.5s 之间晃，贴着刚测到的数字还会误报。
    budget = _perf_budget(4.0)
    assert elapsed < budget, f'600 帧解析写入耗时 {elapsed:.3f}s，应 < {budget:.1f}s'


def test_d9v17_600_curve_thread_batch_is_merged() -> None:
    """曲线线程一次处理 600 帧时，整表一条 ZADD（一包 600 帧）。"""
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
    mapping = next(args[1] for args in zadds if args[0] == rk.curve_latest_key('D9V17'))
    assert len(mapping) == 1
    parsed = parse_prefix(next(iter(mapping)))
    assert parsed is not None
    assert parsed[1] == N_FRAMES
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
    for fr in frames:
        if not fr.parse_key:
            fr.parse_key = fr.cfg_parse_key()
        fr.table_key = LIVE_TABLE_600
    keys = [rk.curve_latest_key(LIVE_TABLE_600), rk.telemetry_fps_key(LIVE_TABLE_600)]
    try:
        t0 = time.perf_counter()
        process_prepared_sync(redis, frames, write_latest=False)
        assert redis.flush() is True
        elapsed = time.perf_counter() - t0
        n = int(raw.zcard(rk.curve_latest_key(LIVE_TABLE_600)) or 0)
        assert n == 1
        assert elapsed < 2.0, f'真 Redis 600 帧耗时 {elapsed:.3f}s'
    finally:
        if keys:
            raw.delete(*keys)
        redis.close()
