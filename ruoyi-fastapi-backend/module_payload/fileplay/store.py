"""文件回放 Redis 读写（同步客户端；禁止碰 ``payload:tm:*``）。

频道 ``history`` / ``curve`` 互不删除；同一频道按 pathHash 隔离：

    payload:play:file:{channel}:{hash}:meta    该文件会话 JSON
    payload:play:file:{channel}:{hash}:worker  该文件子进程心跳
    payload:play:file:{channel}:{hash}:ctrl    该文件控制队列
    payload:play:file:{channel}:{hash}:touch   最后访问 unix 秒
    payload:play:file:{channel}:{hash}:data    history=帧 Hash；curve=万帧压缩块 Hash
"""

from __future__ import annotations

import json
import time
from typing import Any

from module_payload import redis_keys as rk

META_FIELD = 'meta'
CURVE_CHUNK = 10000


def frame_field(index: int) -> str:
    """第 n 帧的 Hash 字段（纯序号，无前缀）。"""
    return str(int(index))


def curve_field(field_id: str) -> str:
    """遥测量 id，用作点列 key 的末段。"""
    return str(field_id or '').strip().upper()


def curve_chunk_field(chunk: int) -> str:
    """万点块序号字段：0 表示 [0, 10000)。"""
    return str(int(chunk))


def curve_chunk_count(frame_count: int) -> int:
    """帧数对应的块数（向上取整）。0 帧 → 0 块。"""
    n = int(frame_count or 0)
    if n <= 0:
        return 0
    return (n + CURVE_CHUNK - 1) // CURVE_CHUNK


def curve_chunks_complete(frame_count: int, stored_chunks: int) -> bool:
    """已写入的万帧块是否覆盖全部精确帧。"""
    need = curve_chunk_count(frame_count)
    return need > 0 and int(stored_chunks or 0) >= need


def curve_all_chunks_ready(redis, path_hash: str, frame_count: int, *, channel: str = 'curve') -> bool:
    """curve data Hash 的块字段数 >= 总帧对应块数。"""
    return curve_chunks_complete(frame_count, stored_frame_count(redis, path_hash, channel=channel))


def curve_chunk_frames(chunk: int, frame_count: int) -> tuple[int, int] | None:
    """块对应的 1-based 含端帧区间。超出总帧则 None。"""
    n = int(frame_count or 0)
    start0 = int(chunk) * CURVE_CHUNK
    if start0 < 0 or start0 >= n:
        return None
    end0 = min(start0 + CURVE_CHUNK, n)
    return start0 + 1, end0


def curve_chunks_requested(body: dict[str, Any] | None, frame_count: int = 0) -> list[int]:
    """请求体 → 半开块区间 [start, end) 的序号列表。"""
    d = body or {}
    raw = d.get('chunks')
    if isinstance(raw, list) and raw:
        out: list[int] = []
        for x in raw:
            try:
                i = int(x)
            except (TypeError, ValueError):
                continue
            if i >= 0:
                out.append(i)
        return out
    start = int(d.get('startIndex') or d.get('start_index') or 0)
    raw_end = d.get('endIndex') if d.get('endIndex') is not None else d.get('end_index')
    cap = curve_chunk_count(frame_count)
    if raw_end in (None, ''):
        end = cap if cap else start + 1
    else:
        end = int(raw_end)
    start = max(0, start)
    end = max(start, end)
    return list(range(start, end))


def dumps(data: Any) -> str:
    """JSON 序列化，保留中文、无空格。"""
    from module_payload.store.jsonutil import dumps_json

    return dumps_json(data)


def loads(text: str | bytes | bytearray | None) -> Any:
    """反序列化；空串/非法 JSON 返回 None（不当成半截帧）。"""
    if not text:
        return None
    if isinstance(text, (bytes, bytearray)):
        text = text.decode('utf-8', errors='ignore')
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None


def _norm_hash(path_hash: str) -> str:
    return (path_hash or '').strip().lower()


def write_meta(redis, path_hash: str, meta: dict[str, Any], *, channel: str = 'history') -> None:
    """写该文件会话 meta（SET，不进文件 Hash）。"""
    ch = rk.fileplay_channel(channel)
    h = _norm_hash(path_hash)
    payload = {
        **meta,
        'pathHash': h,
        'channel': ch,
    }
    redis.set(rk.fileplay_meta_key(h, ch), dumps(payload))
    touch(redis, h, channel=ch)


def read_meta(redis, path_hash: str, *, channel: str = 'history') -> dict[str, Any] | None:
    """读该文件 meta；path_hash 为空则 None。"""
    ch = rk.fileplay_channel(channel)
    h = _norm_hash(path_hash)
    if not h:
        return None
    data = loads(redis.get(rk.fileplay_meta_key(h, ch)))
    if not isinstance(data, dict):
        return None
    return data


def touch(redis, path_hash: str, *, channel: str = 'history') -> None:
    """刷新该文件最后访问时间。"""
    h = _norm_hash(path_hash)
    if not h:
        return
    redis.set(rk.fileplay_touch_key(h, channel), str(int(time.time())))


def stored_frame_count(redis, path_hash: str, *, channel: str = 'history') -> int:
    """Hash 里已写入的帧字段数。"""
    key = rk.fileplay_hash_key(path_hash, channel)
    try:
        n = redis.hlen(key)
    except Exception:
        return 0
    try:
        return int(n or 0)
    except (TypeError, ValueError):
        return 0


def iter_meta_hashes(redis, channel: str = 'history') -> list[str]:
    """该频道下已有 meta 的 pathHash 列表。"""
    ch = rk.fileplay_channel(channel)
    out: list[str] = []
    for key in _scan_keys(redis, f'{rk.fileplay_channel_prefix(ch)}*:meta'):
        h = rk.fileplay_hash_from_leaf_key(key)
        if h:
            out.append(h)
    return out


def write_frame(redis, path_hash: str, index: int, frame: dict[str, Any], *, channel: str = 'history') -> None:
    """写入第 n 帧快照（1-based）。"""
    key = rk.fileplay_hash_key(path_hash, channel)
    redis.hset(key, frame_field(index), dumps(frame))


def read_frame(redis, path_hash: str, index: int, *, channel: str = 'history') -> dict[str, Any] | None:
    """读第 n 帧；未解析为 None。"""
    key = rk.fileplay_hash_key(path_hash, channel)
    return loads(redis.hget(key, frame_field(index)))


def _scan_keys(redis, pattern: str) -> list[str]:
    """SCAN 匹配的 key（含 Hash / STRING）。"""
    found: list[str] = []
    cursor: int | str = 0
    while True:
        cursor, keys = redis.scan(cursor=cursor, match=pattern, count=200)
        found.extend(k for k in (keys or []) if k)
        if cursor in (0, '0', b'0', None):
            break
    return found


def _delete_keys(redis, keys: list[str]) -> int:
    if not keys:
        return 0
    unlink = getattr(redis, 'unlink', None)
    fn = unlink if callable(unlink) else redis.delete
    fn(*keys)
    return len(keys)


def _hget_bytes(redis, key: str, field: str):
    """读 Hash 字段原字节；真 Redis 跳过 UTF-8 解码。"""
    pool = getattr(redis, 'connection_pool', None)
    exec_cmd = getattr(redis, 'execute_command', None)
    if pool is not None and callable(exec_cmd):
        from redis.client import NEVER_DECODE

        return exec_cmd('HGET', key, field, **{NEVER_DECODE: []})
    return redis.hget(key, field)


def _hset_bytes(redis, key: str, field: str, value: bytes) -> None:
    redis.hset(key, field, value)


def write_curve_chunk(
    redis,
    path_hash: str,
    chunk: int,
    rows: list[tuple[int | float, dict[str, float]]],
    *,
    channel: str = 'curve',
    field_id: str | None = None,
) -> None:
    """写入一块整表压缩点列。Hash 字段存在即表示该块已解析。

    ``rows`` 为 ``(ts_ms, {字段: 数值})``。field_id 已废弃。
    """
    _ = field_id
    key = rk.fileplay_points_key(path_hash, channel=channel)
    assert_not_live_tm_key(key)
    field = curve_chunk_field(chunk)
    if not rows:
        _hset_bytes(redis, key, field, b'')
        return
    from module_payload.store.curve_blob import columns_from_rows, encode_payload

    timestamps, columns = columns_from_rows([(pts, ts) for ts, pts in rows])
    _hset_bytes(redis, key, field, encode_payload(timestamps, columns))


def points_from_chunk_value(raw: Any, field_id: str) -> list[list[float | int]] | None:
    """一块压缩值 → 某字段 ``[[t, v], …]``。``None`` 表示块不存在。"""
    if raw is None:
        return None
    if raw in (b'', '', bytearray()):
        return []
    from module_payload.store.curve_blob import decode_payload, extract_field

    data = decode_payload(raw)
    if data is None:
        return []
    fid = curve_field(field_id)
    return [[p['t'], p['v']] for p in extract_field(data, fid)]


def read_curve_chunk(redis, path_hash: str, field_id: str, chunk: int, *, channel: str = 'curve'):
    """读一块里某字段的点列；没有该块返回 None。"""
    fid = curve_field(field_id)
    if not fid:
        return None
    key = rk.fileplay_points_key(path_hash, channel=channel)
    return points_from_chunk_value(_hget_bytes(redis, key, curve_chunk_field(chunk)), fid)


def curve_chunk_ready(
    redis, path_hash: str, chunk: int, field_id: str | None = None, *, channel: str = 'curve'
) -> bool:
    """块字段存在即已解析（空包也算）。field_id 已废弃。"""
    _ = field_id
    key = rk.fileplay_points_key(path_hash, channel=channel)
    return _hget_bytes(redis, key, curve_chunk_field(chunk)) is not None


def delete_session(redis, path_hash: str, *, channel: str = 'history') -> None:
    """只删本频道该文件 Hash / 点列 / meta / ctrl / worker / touch。不动其它文件。"""
    ch = rk.fileplay_channel(channel)
    h = _norm_hash(path_hash)
    if not h:
        return
    prefix = rk.fileplay_file_prefix(h, ch)
    keys = [
        *_scan_keys(redis, f'{prefix}*'),
        rk.fileplay_hash_key(h, ch),
        rk.fileplay_meta_key(h, ch),
        rk.fileplay_ctrl_key(h, ch),
        rk.fileplay_worker_status_key(h, ch),
        rk.fileplay_touch_key(h, ch),
    ]
    _delete_keys(redis, keys)


def iter_parsed_frames(
    redis, path_hash: str, start: int, end: int, *, channel: str = 'history'
) -> list[tuple[int, dict[str, Any]]]:
    """读取已解析帧 [start, end]（1-based，含端）。"""
    key = rk.fileplay_hash_key(path_hash, channel)
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


def clear_channel(redis, channel: str = 'history') -> int:
    """进程启动时清掉本频道全部残余（含各 hash 的 meta/ctrl/worker）。不动另一频道。"""
    ch = rk.fileplay_channel(channel)
    pattern = f'{rk.fileplay_channel_prefix(ch)}*'
    keys = _scan_keys(redis, pattern)
    return _delete_keys(redis, keys)
