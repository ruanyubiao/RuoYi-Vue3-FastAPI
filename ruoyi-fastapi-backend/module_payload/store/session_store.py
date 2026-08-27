"""设备会话 Redis 读写（采集热路径只 GET，不碰 ProcessManager）。"""

from __future__ import annotations

import json
from typing import Any

from module_payload import redis_keys as rk
from module_payload.constants import infer_src_kind
from module_payload.store.jsonutil import dumps_json


def loads_session(text: str | bytes | None) -> dict[str, Any] | None:
    """Redis 会话值 → dict；空返回 None。"""
    if not text:
        return None
    if isinstance(text, bytes):
        text = text.decode()
    data = json.loads(text)
    return data if isinstance(data, dict) else None


def dumps_session(session: dict[str, Any]) -> str:
    """会话写入 Redis 前的 JSON。"""
    return dumps_json(session)


def get_session_sync(
    redis_client: Any, src_param: str, src_kind: str | None = None
) -> dict[str, Any] | None:
    """同步读 Redis 会话；不存在返回 None。"""
    src_kind = src_kind or infer_src_kind(src_param)
    return loads_session(redis_client.get(rk.session_key(src_kind, src_param)))


def delete_session_sync(redis_client: Any, src_param: str, src_kind: str | None = None) -> None:
    """删除 Redis 会话键。"""
    src_kind = src_kind or infer_src_kind(src_param)
    redis_client.delete(rk.session_key(src_kind, src_param))
