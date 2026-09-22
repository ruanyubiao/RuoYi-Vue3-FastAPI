"""主进程异步 Redis 读写封装。"""

from __future__ import annotations

import inspect
import time
from typing import Any

from redis import asyncio as aioredis

from module_payload import redis_keys as rk
from module_payload.constants import (
    CMD_RESULT_TTL,
    CURVE_MAX_POINTS,
    CURVE_TS_MAX_AHEAD_MS,
    HEARTBEAT_TTL,
    HISTORY_MAX,
)
from module_payload.store.curve_blob import (
    points_from_blobs,
    unpack_member,
)
from module_payload.store.jsonutil import dumps_json, loads_json


def _dumps(data: Any) -> str:
    """写入 Redis 前的 JSON 编码。"""
    return dumps_json(data)


def _loads(text: str | None) -> Any:
    """Redis 取值反序列化；空返回 None。"""
    return loads_json(text)


async def push_command(redis: aioredis.Redis, device_id: str, command: dict[str, Any]) -> None:
    """LPUSH 设备命令队列，采集进程消费。"""
    await redis.lpush(rk.cmd_queue_key(device_id), _dumps(command))


async def wait_command_result(
    redis: aioredis.Redis, device_id: str, cmd_id: str, timeout_s: float = 5.0
) -> dict[str, Any] | None:
    """轮询 Redis 命令结果键直至超时。"""
    import asyncio

    key = rk.cmd_result_key(device_id, cmd_id)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        raw = await redis.get(key)
        if raw:
            return _loads(raw)
        await asyncio.sleep(0.05)
    return None


async def get_status(redis: aioredis.Redis, device_id: str) -> dict[str, Any] | None:
    """读设备状态 JSON。"""
    return _loads(await redis.get(rk.status_key(device_id)))


async def get_telemetry_latest(redis: aioredis.Redis, table_type: str) -> dict[str, Any] | None:
    """按子类型取最新一帧（跨来源）。"""
    return _loads(await redis.get(rk.telemetry_latest_key(table_type)))


async def set_telemetry(
    redis: aioredis.Redis,
    table_type: str,
    fields: list[dict[str, Any]],
    name: str = '',
    *,
    src_param: str,
    data_kind: str = 'tm',
    src_kind: str | None = None,
    parser_id: str | None = None,
) -> dict[str, Any]:
    """写最新一帧到 Redis（telemetry:latest + ts）；返回带 dataId 的 payload。"""
    from datetime import datetime

    from module_payload.constants import infer_src_kind

    tkey = (table_type or '').upper()
    now = datetime.now()
    ts = now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    src_kind = src_kind or infer_src_kind(src_param)
    payload = {
        'type': tkey,
        'name': name,
        'ts': ts,
        'dataId': int(now.timestamp() * 1000),
        'fields': fields,
        'dataKind': data_kind,
        'dataSub': tkey,
        'srcKind': src_kind,
        'srcParam': src_param,
        'parserId': parser_id,
    }
    dumped = _dumps(payload)
    await redis.set(rk.telemetry_latest_key(tkey), dumped)
    await redis.set(rk.telemetry_latest_ts_key(tkey), ts)
    return payload


async def append_curve_points(
    redis: aioredis.Redis,
    table_type: str,
    fields: list[dict[str, Any]],
    ts_str: str,
) -> None:
    """本帧可数值化字段打成一个整表压缩包写入曲线 ZSet。"""
    from datetime import datetime

    from module_payload.collectors import redis_cmd_helper as redis_cmd
    from module_payload.parsers.tm_field_util import curve_numeric

    try:
        ts_ms = int(datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S.%f').timestamp() * 1000)
    except Exception:
        ts_ms = int(time.time() * 1000)
    tkey = (table_type or '').upper()
    points: dict[str, float] = {}
    for row in fields:
        fid = row.get('id')
        if not fid:
            continue
        val = curve_numeric(row)
        if val is None:
            continue
        points[str(fid)] = float(val)
    ops = redis_cmd.curves([(tkey, points, ts_ms)]) if points else []
    if not ops:
        return
    pipe = redis.pipeline(transaction=False)
    for cmd, args in ops:
        getattr(pipe, cmd)(*args)
    await pipe.execute()


async def get_history(redis: aioredis.Redis, source: str, limit: int = 50) -> list[dict[str, Any]]:
    """读来源发送历史 List（新在前）。"""
    items = await redis.lrange(rk.source_history_key(source), 0, limit - 1)
    return [_loads(x) for x in items if x]


async def clear_history(redis: aioredis.Redis, source: str) -> None:
    """删除该来源的发送历史 List。"""
    await redis.delete(rk.source_history_key(source))


SEQ_RUN_TTL = 7 * 24 * 3600  # 序列执行记录 TTL
SEQ_RUN_HISTORY_MAX = 50  # 每序列保留的 runId 条数


async def save_seq_run(redis: aioredis.Redis, run: dict[str, Any]) -> None:
    """写序列执行进度（带 TTL）。"""
    run_id = run.get('runId') or run.get('run_id')
    if not run_id:
        return
    await redis.set(rk.seq_run_key(str(run_id)), _dumps(run), ex=SEQ_RUN_TTL)


async def get_seq_run(redis: aioredis.Redis, run_id: str) -> dict[str, Any] | None:
    """读一次序列执行进度。"""
    return _loads(await redis.get(rk.seq_run_key(run_id)))


async def push_seq_run_history(redis: aioredis.Redis, seq_id: int, run_id: str) -> None:
    """将该 runId 记入序列历史 List 并续期。"""
    key = rk.seq_run_history_key(seq_id)
    await redis.lpush(key, run_id)
    await redis.ltrim(key, 0, SEQ_RUN_HISTORY_MAX - 1)
    await redis.expire(key, SEQ_RUN_TTL)


async def list_seq_run_history(redis: aioredis.Redis, seq_id: int, limit: int = 30) -> list[dict[str, Any]]:
    """取序列最近若干次执行详情。"""
    run_ids = await redis.lrange(rk.seq_run_history_key(seq_id), 0, max(0, limit - 1))
    result: list[dict[str, Any]] = []
    for raw_id in run_ids:
        run_id = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
        run = await get_seq_run(redis, run_id)
        if run:
            result.append(run)
    return result


def _score_float(score: Any) -> float:
    if isinstance(score, bytes):
        score = score.decode()
    return float(score)


def _zset_pairs(raw: Any) -> list[tuple[Any, float]]:
    """ZRANGEBYSCORE WITHSCORES → ``[(member, score), ...]``。"""
    if not raw:
        return []
    first = raw[0]
    if isinstance(first, (tuple, list)) and len(first) >= 2:
        out: list[tuple[Any, float]] = []
        for item in raw:
            out.append((item[0], _score_float(item[1])))
        return out
    pairs: list[tuple[Any, float]] = []
    it = iter(raw)
    for member in it:
        score = next(it, None)
        if score is None:
            break
        pairs.append((member, _score_float(score)))
    return pairs


async def _zrangebyscore_pairs(
    redis: Any,
    key: str,
    min_s: Any,
    max_s: Any,
    *,
    reverse: bool = False,
) -> list[tuple[Any, float]]:
    """读曲线 ZSet；真 Redis 用 NEVER_DECODE，避免 zstd member 被当 UTF-8。"""
    pool = getattr(redis, 'connection_pool', None)
    exec_cmd = getattr(redis, 'execute_command', None)
    if pool is not None and callable(exec_cmd):
        from redis.client import NEVER_DECODE

        cmd = 'ZREVRANGEBYSCORE' if reverse else 'ZRANGEBYSCORE'
        lo, hi = (max_s, min_s) if reverse else (min_s, max_s)
        raw = exec_cmd(cmd, key, lo, hi, 'WITHSCORES', **{NEVER_DECODE: []})
        if inspect.isawaitable(raw):
            raw = await raw
        return _zset_pairs(raw)
    if reverse:
        raw = await redis.zrevrangebyscore(key, max_s, min_s, withscores=True)
    else:
        raw = await redis.zrangebyscore(key, min=min_s, max=max_s, withscores=True)
    return _zset_pairs(raw)


async def load_curve_blobs(
    redis: aioredis.Redis,
    table_type: str,
    since_t: int | float | None = None,
    until_t: int | float | None = None,
) -> list[dict[str, Any]]:
    """解压整表曲线包，按时间从旧到新。since_t 开区间作用于 member score。"""
    key = rk.curve_latest_key(table_type)
    horizon = time.time() * 1000.0 + CURVE_TS_MAX_AHEAD_MS
    if since_t is not None and float(since_t) > horizon:
        since_t = None
    cap = horizon if until_t is None else min(float(until_t), horizon)
    if since_t is None:
        raw = await _zrangebyscore_pairs(redis, key, '-inf', cap, reverse=True)
        raw = list(reversed(raw))
    else:
        raw = await _zrangebyscore_pairs(redis, key, f'({since_t}', cap, reverse=False)
    blobs: list[dict[str, Any]] = []
    for member, _score in raw:
        data = unpack_member(member)
        if data is not None:
            blobs.append(data)
    return blobs


async def get_curve_points(
    redis: aioredis.Redis,
    table_type: str,
    field: str,
    limit: int = CURVE_MAX_POINTS,
    since_t: int | float | None = None,
    until_t: int | float | None = None,
    blobs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """从 Redis ZSet 取曲线点；since_t 开区间左端，until_t 闭区间右端。

    横轴不得超过墙钟（允许 ``CURVE_TS_MAX_AHEAD_MS``）。since_t 若已在未来，
    当作无 since_t，改拉当前墙钟之前最近的 limit 个点，否则增量会永远为空。

    有 since_t 时从开区间左端按时间顺序取，保证相邻两轮能接上，曲线不断档。
    显示侧抽稀后再上屏，不在这里跳过中间点。
    FastAPI 解压后只返回请求字段的 ``{t,v}``。
    """
    horizon = time.time() * 1000.0 + CURVE_TS_MAX_AHEAD_MS
    use_since = since_t
    if use_since is not None and float(use_since) > horizon:
        use_since = None
    cap = horizon if until_t is None else min(float(until_t), horizon)
    if blobs is None:
        blobs = await load_curve_blobs(redis, table_type, use_since, until_t)
    return points_from_blobs(
        blobs,
        field,
        limit=limit,
        since_t=use_since,
        until_t=cap,
        newest=use_since is None,
    )


async def get_image_meta(redis: aioredis.Redis, device_id: str) -> dict[str, Any] | None:
    """读相机图像 meta（phase/message 等）。"""
    return _loads(await redis.get(rk.image_meta_key(device_id)))


async def get_lvds_points(
    redis: aioredis.Redis, device_id: str, signal: str, limit: int = 2000
) -> list[dict[str, Any]]:
    """读 LVDS 信号采样 List。"""
    key = rk.lvds_key(device_id, signal)
    raw = await redis.lrange(key, -limit, -1)
    return [_loads(x) for x in raw if x]
