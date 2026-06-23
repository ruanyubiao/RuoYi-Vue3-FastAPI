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
CURVE_MAX_POINTS = 600


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


async def get_history(redis: aioredis.Redis, device_id: str, limit: int = 50) -> list[dict[str, Any]]:
    items = await redis.lrange(rk.history_key(device_id), 0, limit - 1)
    return [_loads(x) for x in items if x]


async def get_curve_points(
    redis: aioredis.Redis, device_id: str, table_type: str, field: str, limit: int = CURVE_MAX_POINTS
) -> list[dict[str, Any]]:
    key = rk.curve_key(device_id, table_type.upper(), field)
    raw = await redis.zrange(key, -limit, -1, withscores=True)
    return [{'t': int(score), 'v': float(val)} for val, score in raw]


async def set_curve_subscribe(
    redis: aioredis.Redis, device_id: str, table_type: str, field: str, enabled: bool = True
) -> None:
    key = rk.curve_subscribe_key(device_id)
    member = f'{table_type.upper()}:{field}'
    if enabled:
        await redis.sadd(key, member)
    else:
        await redis.srem(key, member)


async def get_image_meta(redis: aioredis.Redis, device_id: str) -> dict[str, Any] | None:
    return _loads(await redis.get(f'{rk.PREFIX}:{device_id}:image:meta'))


async def get_lvds_points(
    redis: aioredis.Redis, device_id: str, signal: str, limit: int = 2000
) -> list[dict[str, Any]]:
    key = rk.lvds_key(device_id, signal)
    raw = await redis.lrange(key, -limit, -1)
    return [_loads(x) for x in raw if x]
