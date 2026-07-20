"""主进程异步 Redis 读写封装。"""

from __future__ import annotations

import json
import time
from typing import Any

from redis import asyncio as aioredis

from module_payload import redis_keys as rk

HISTORY_MAX = 100
HEARTBEAT_TTL = 15
CMD_RESULT_TTL = 120
CURVE_MAX_POINTS = 50000


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _loads(text: str | None) -> Any:
    if not text:
        return None
    return json.loads(text)


async def push_command(redis: aioredis.Redis, device_id: str, command: dict[str, Any]) -> None:
    await redis.lpush(rk.cmd_queue_key(device_id), _dumps(command))


async def wait_command_result(
    redis: aioredis.Redis, device_id: str, cmd_id: str, timeout_s: float = 5.0
) -> dict[str, Any] | None:
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
    """本帧每个可数值化字段写入按子类型共享的曲线 ZSet。"""
    from datetime import datetime

    try:
        ts_ms = int(datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S.%f').timestamp() * 1000)
    except Exception:
        ts_ms = int(time.time() * 1000)
    tkey = (table_type or '').upper()
    pipe = redis.pipeline(transaction=False)
    wrote = False
    for row in fields:
        fid = row.get('id')
        if not fid:
            continue
        try:
            val = float(row.get('value', row.get('show', 0)))
        except (TypeError, ValueError):
            continue
        member = {f'{ts_ms}|{val}': ts_ms}
        lkey = rk.curve_latest_key(tkey, fid)
        pipe.zadd(lkey, member)
        pipe.zremrangebyrank(lkey, 0, -(CURVE_MAX_POINTS + 1))
        wrote = True
    if wrote:
        await pipe.execute()


async def get_history(redis: aioredis.Redis, device_id: str, limit: int = 50) -> list[dict[str, Any]]:
    items = await redis.lrange(rk.history_key(device_id), 0, limit - 1)
    return [_loads(x) for x in items if x]


async def clear_history(redis: aioredis.Redis, device_id: str) -> None:
    await redis.delete(rk.history_key(device_id))


SEQ_RUN_TTL = 7 * 24 * 3600
SEQ_RUN_HISTORY_MAX = 50


async def save_seq_run(redis: aioredis.Redis, run: dict[str, Any]) -> None:
    run_id = run.get('runId') or run.get('run_id')
    if not run_id:
        return
    await redis.set(rk.seq_run_key(str(run_id)), _dumps(run), ex=SEQ_RUN_TTL)


async def get_seq_run(redis: aioredis.Redis, run_id: str) -> dict[str, Any] | None:
    return _loads(await redis.get(rk.seq_run_key(run_id)))


async def push_seq_run_history(redis: aioredis.Redis, seq_id: int, run_id: str) -> None:
    key = rk.seq_run_history_key(seq_id)
    await redis.lpush(key, run_id)
    await redis.ltrim(key, 0, SEQ_RUN_HISTORY_MAX - 1)
    await redis.expire(key, SEQ_RUN_TTL)


async def list_seq_run_history(redis: aioredis.Redis, seq_id: int, limit: int = 30) -> list[dict[str, Any]]:
    run_ids = await redis.lrange(rk.seq_run_history_key(seq_id), 0, max(0, limit - 1))
    result: list[dict[str, Any]] = []
    for raw_id in run_ids:
        run_id = raw_id.decode() if isinstance(raw_id, bytes) else str(raw_id)
        run = await get_seq_run(redis, run_id)
        if run:
            result.append(run)
    return result


async def get_curve_points(
    redis: aioredis.Redis,
    table_type: str,
    field: str,
    limit: int = CURVE_MAX_POINTS,
    since_t: int | None = None,
) -> list[dict[str, Any]]:
    key = rk.curve_latest_key(table_type.upper(), field)
    if since_t is not None:
        raw = await redis.zrangebyscore(
            key, min=f'({since_t}', max='+inf', start=0, num=limit, withscores=True
        )
    else:
        raw = await redis.zrange(key, -limit, -1, withscores=True)
    points: list[dict[str, Any]] = []
    for member, score in raw:
        m = member.decode() if isinstance(member, bytes) else str(member)
        if '|' not in m:
            continue
        _, v_str = m.split('|', 1)
        try:
            v = float(v_str)
        except (TypeError, ValueError):
            continue
        points.append({'t': int(score), 'v': v})
    return points


async def get_image_meta(redis: aioredis.Redis, device_id: str) -> dict[str, Any] | None:
    return _loads(await redis.get(f'{rk.PREFIX}:{device_id}:image:meta'))


async def get_lvds_points(
    redis: aioredis.Redis, device_id: str, signal: str, limit: int = 2000
) -> list[dict[str, Any]]:
    key = rk.lvds_key(device_id, signal)
    raw = await redis.lrange(key, -limit, -1)
    return [_loads(x) for x in raw if x]
