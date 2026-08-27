"""组装预览：assembler.feed + assembled Redis 条目（采集/模拟共用，不依赖 service）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from module_payload import redis_keys as rk
from module_payload.constants import ASSEMBLED_LOG_MAX
from module_payload.store.jsonutil import dumps_json


def feed_assembler(assembler: Any, raw: bytes) -> tuple[list[Any], list[str]]:
    """喂入原始字节，返回完整载荷与 take_errors() 取出的错误。"""
    payloads = assembler.feed(raw)
    take_errors = getattr(assembler, 'take_errors', None)
    errors: list[str] = []
    if callable(take_errors):
        errors = list(take_errors() or [])
    return list(payloads or []), errors


def assembled_entry(
    device_id: str,
    assembler_id: str,
    data: bytes,
    meta: dict[str, Any] | None = None,
    *,
    hex_max: int | None = None,
    ts: str | None = None,
    is_image: bool | None = None,
) -> dict[str, Any]:
    """assembled Redis JSON：字段集合固定；hex 长度由 hex_max 控制（None=全文）。"""
    meta_out = dict(meta or {})
    meta_out.setdefault('assemblerId', assembler_id)
    if is_image is None:
        is_image = meta_out.get('kind') == 'image'
    if is_image:
        hex_text = ''
    else:
        blob = data if hex_max is None else data[:hex_max]
        hex_text = ' '.join(f'{b:02X}' for b in blob)
    return {
        'deviceId': device_id,
        'assemblerId': assembler_id,
        'ts': ts or datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
        'len': len(data),
        'hex': hex_text,
        'meta': meta_out,
    }


def write_assembled_sync(redis: Any, device_id: str, entry: dict[str, Any]) -> None:
    """同步写入 assembled:latest 与 log（采集热路径）。"""
    dumped = dumps_json(entry)
    latest_key = rk.assembled_latest_key(device_id)
    log_key = rk.assembled_log_key(device_id)
    pipe = getattr(redis, 'pipeline', None)
    if callable(pipe):
        p = pipe(transaction=False)
        p.set(latest_key, dumped)
        p.lpush(log_key, dumped)
        p.ltrim(log_key, 0, ASSEMBLED_LOG_MAX - 1)
        p.execute()
        return
    redis.set(latest_key, dumped)
    redis.lpush(log_key, dumped)
    redis.ltrim(log_key, 0, ASSEMBLED_LOG_MAX - 1)


async def write_assembled_async(redis: Any, device_id: str, entry: dict[str, Any]) -> None:
    """异步写入 assembled:latest 与 log（HTTP 模拟注入）。"""
    dumped = dumps_json(entry)
    await redis.set(rk.assembled_latest_key(device_id), dumped)
    log_key = rk.assembled_log_key(device_id)
    await redis.lpush(log_key, dumped)
    await redis.ltrim(log_key, 0, ASSEMBLED_LOG_MAX - 1)
