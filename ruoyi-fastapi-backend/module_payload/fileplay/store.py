"""文件回放 Redis Hash 读写（同步客户端；禁止碰 ``payload:tm:*``）。

Hash 名 ``payload:fileplay:{pathHash}``：
    meta     JSON：status(parsing/ready/error)、frameCount、frameCountExact、type、path
    f:{n}    第 n 帧表快照 JSON（1-based）
    c:{id}   曲线点列 JSON

预估改精确只 HSET 覆盖 ``meta``，不 DEL 整个 key，已解析的 ``f:{n}`` 保留。
"""

from __future__ import annotations

import json
from typing import Any

from module_payload import redis_keys as rk

META_FIELD = 'meta'
FRAME_FIELD_PREFIX = 'f:'


def frame_field(index: int) -> str:
    """第 n 帧的 Hash 子 key。"""
    return f'{FRAME_FIELD_PREFIX}{int(index)}'


def dumps(data: Any) -> str:
    """JSON 序列化，保留中文。"""
    return json.dumps(data, ensure_ascii=False)


def loads(text: str | None) -> Any:
    """反序列化；空串/非法 JSON 返回 None（不当成半截帧）。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None


def write_meta(redis, path_hash: str, meta: dict[str, Any]) -> None:
    """HSET 同一 ``meta`` 字段（预估改精确时覆盖）。"""
    key = rk.fileplay_hash_key(path_hash)
    redis.hset(key, META_FIELD, dumps(meta))


def read_meta(redis, path_hash: str) -> dict[str, Any] | None:
    """读 meta；无 key 或坏 JSON 为 None。"""
    key = rk.fileplay_hash_key(path_hash)
    return loads(redis.hget(key, META_FIELD))


def write_frame(redis, path_hash: str, index: int, frame: dict[str, Any]) -> None:
    """写入第 n 帧快照（1-based）。"""
    key = rk.fileplay_hash_key(path_hash)
    redis.hset(key, frame_field(index), dumps(frame))


def read_frame(redis, path_hash: str, index: int) -> dict[str, Any] | None:
    """读第 n 帧；未解析为 None。"""
    key = rk.fileplay_hash_key(path_hash)
    return loads(redis.hget(key, frame_field(index)))


def delete_session(redis, path_hash: str) -> None:
    """切文件时 DEL 整个 Hash。"""
    redis.delete(rk.fileplay_hash_key(path_hash))


def iter_parsed_frames(redis, path_hash: str, start: int, end: int) -> list[tuple[int, dict[str, Any]]]:
    """读取已解析帧 [start, end]（1-based，含端）。"""
    key = rk.fileplay_hash_key(path_hash)
    out: list[tuple[int, dict[str, Any]]] = []
    for i in range(start, end + 1):
        data = loads(redis.hget(key, frame_field(i)))
        if data:
            out.append((i, data))
    return out


def assert_not_live_tm_key(key: str) -> None:
    """测试/防护：文件回放 key 不得落入实时遥测前缀。"""
    if key.startswith(f'{rk.PREFIX}:tm:'):
        raise RuntimeError(f'禁止写入实时遥测 key: {key}')
