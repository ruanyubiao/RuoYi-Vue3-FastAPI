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


async def get_telemetry(redis: aioredis.Redis, device_id: str, table_type: str) -> dict[str, Any] | None:
    return _loads(await redis.get(rk.telemetry_key(device_id, table_type.upper())))


async def set_telemetry(
    redis: aioredis.Redis,
    device_id: str,
    table_type: str,
    fields: list[dict[str, Any]],
    name: str = '',
) -> dict[str, Any]:
    from datetime import datetime

    tkey = (table_type or '').upper()
    now = datetime.now()
    ts = now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    payload = {
        'type': tkey,
        'name': name,
        'ts': ts,
        'dataId': int(now.timestamp() * 1000),
        'fields': fields,
    }
    await redis.set(rk.telemetry_key(device_id, tkey), _dumps(payload))
    await redis.set(rk.telemetry_ts_key(device_id, tkey), ts)
    return payload


async def append_curve_points(
    redis: aioredis.Redis,
    device_id: str,
    table_type: str,
    fields: list[dict[str, Any]],
    ts_str: str,
) -> None:
    """本帧每个可数值化字段都写入曲线 ZSet（与前端是否订阅无关；与采集进程 _append_curve 一致）。"""
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
        ckey = rk.curve_key(device_id, tkey, fid)
        # ZSet member 需要唯一；member=ts|val，score=ts
        pipe.zadd(ckey, {f'{ts_ms}|{val}': ts_ms})
        pipe.zremrangebyrank(ckey, 0, -(CURVE_MAX_POINTS + 1))
        wrote = True
    if wrote:
        await pipe.execute()


async def get_history(redis: aioredis.Redis, device_id: str, limit: int = 50) -> list[dict[str, Any]]:
    items = await redis.lrange(rk.history_key(device_id), 0, limit - 1)
    return [_loads(x) for x in items if x]


async def clear_history(redis: aioredis.Redis, device_id: str) -> None:
    await redis.delete(rk.history_key(device_id))


async def get_curve_points(
    redis: aioredis.Redis,
    device_id: str,
    table_type: str,
    field: str,
    limit: int = CURVE_MAX_POINTS,
    since_t: int | None = None,
) -> list[dict[str, Any]]:
    key = rk.curve_key(device_id, table_type.upper(), field)
    if since_t is not None:
        raw = await redis.zrangebyscore(
            key, min=f'({since_t}', max='+inf', start=0, num=limit, withscores=True
        )
    else:
        raw = await redis.zrange(key, -limit, -1, withscores=True)
    points: list[dict[str, Any]] = []
    for member, score in raw:
        m = member.decode() if isinstance(member, bytes) else str(member)
        # member 格式：{tsMs}|{val}
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
