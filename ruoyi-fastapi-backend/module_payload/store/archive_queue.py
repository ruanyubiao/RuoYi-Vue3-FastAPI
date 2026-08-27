"""遥测归档 Redis 队列（入队）。MySQL worker 仍在 payload_telemetry_archive_service。"""

from __future__ import annotations

from typing import Any

from redis import asyncio as aioredis

from module_payload import redis_keys as rk
from module_payload.constants import DATA_KIND_TM, PARSER_TM_CAN_BIU, infer_src_kind, should_archive_tm_mysql
from module_payload.store.jsonutil import dumps_json


def bytes_to_raw_hex(data: bytes | bytearray | memoryview | None) -> str:
    """完整复合帧 → 空格分隔大写 HEX（如 ``AA BB CC``）。"""
    if not data:
        return ''
    return bytes(data).hex(' ').upper()


def build_archive_event(
    *,
    ts_ms: int,
    raw_frame: bytes,
    points: dict[str, float | int],
    data_sub: str,
    src_param: str,
    name: str = '',
    src_kind: str | None = None,
    data_kind: str = DATA_KIND_TM,
    parser_id: str | None = PARSER_TM_CAN_BIU,
    cfg_version: str | None = None,
) -> dict[str, Any]:
    """归档队列事件：完整复合帧 HEX + 数值点；不含全量 fields。"""
    data_sub = (data_sub or '').upper()
    src_kind = src_kind or infer_src_kind(src_param)
    points_norm = {str(k): float(v) for k, v in (points or {}).items() if k is not None and v is not None}
    parsed_json = {
        'name': name,
        'dataKind': data_kind,
        'dataSub': data_sub,
        'srcKind': src_kind,
        'srcParam': src_param,
        'parserId': parser_id,
    }
    return {
        'data_kind': data_kind,
        'data_sub': data_sub,
        'src_kind': src_kind,
        'src_param': src_param,
        'parser_id': parser_id,
        'ts_ms': ts_ms,
        'raw_hex': bytes_to_raw_hex(raw_frame),
        'points': points_norm,
        'parsed_json': parsed_json,
        'field_count': len(points_norm),
        'cfg_version': cfg_version,
    }


def enqueue_sync(redis_client: Any, event: dict[str, Any]) -> None:
    """符合条件的遥测事件同步 LPUSH 到 Redis 归档队列。"""
    if not should_archive_tm_mysql(
        event.get('src_kind'),
        event.get('src_param') or '',
        event.get('parser_id'),
    ):
        return
    redis_client.lpush(rk.archive_queue_key(), dumps_json(event))


async def enqueue(redis: aioredis.Redis, event: dict[str, Any]) -> None:
    """符合条件的遥测事件异步入 Redis 归档队列。"""
    if not should_archive_tm_mysql(
        event.get('src_kind'),
        event.get('src_param') or '',
        event.get('parser_id'),
    ):
        return
    await redis.lpush(rk.archive_queue_key(), dumps_json(event))
