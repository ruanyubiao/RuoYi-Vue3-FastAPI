"""文件回放 Redis 读写（同步客户端；禁止碰 ``payload:tm:*``）。

频道 ``history`` / ``curve`` 互不删除：

    payload:fileplay:{channel}:meta     当前会话 JSON（在文件 Hash 外面）
    payload:fileplay:{channel}:worker   子进程心跳
    payload:fileplay:{channel}:ctrl     控制队列
    payload:fileplay:{channel}:job      抽点完成标记（STRING，可选）
    payload:fileplay:history:{hash}     帧 Hash，字段为序号
    payload:fileplay:curve:{hash}:{id}  点列 Hash，字段为万点块序号
"""

from __future__ import annotations

import json
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
    """JSON 序列化，保留中文。"""
    return json.dumps(data, ensure_ascii=False)


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


def write_meta(redis, path_hash: str, meta: dict[str, Any], *, channel: str = 'history') -> None:
    """写频道当前会话 meta（SET，不进文件 Hash）。"""
    ch = rk.fileplay_channel(channel)
    payload = {
        **meta,
        'pathHash': (path_hash or '').strip().lower(),
        'channel': ch,
    }
    redis.set(rk.fileplay_meta_key(ch), dumps(payload))


def read_meta(redis, path_hash: str, *, channel: str = 'history') -> dict[str, Any] | None:
    """读频道 meta；path_hash 非空且与当前会话不一致则视为已失效。"""
    ch = rk.fileplay_channel(channel)
    data = loads(redis.get(rk.fileplay_meta_key(ch)))
    if not isinstance(data, dict):
        return None
    want = (path_hash or '').strip().lower()
    got = str(data.get('pathHash') or '').strip().lower()
    if want and got and want != got:
        return None
    return data


def read_channel_meta(redis, *, channel: str = 'history') -> dict[str, Any] | None:
    """读该频道当前会话，不校验 pathHash。"""
    return read_meta(redis, '', channel=channel)


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


def write_curve_chunk(
    redis,
    path_hash: str,
    field_id: str,
    chunk: int,
    points: list,
    *,
    channel: str = 'curve',
) -> None:
    """写入一块点列。Hash 字段存在即表示该块已解析。"""
    fid = curve_field(field_id)
    if not fid:
        return
    key = rk.fileplay_points_key(path_hash, fid, channel)
    assert_not_live_tm_key(key)
    redis.hset(key, curve_chunk_field(chunk), dumps(points or []))


def read_curve_chunk(redis, path_hash: str, field_id: str, chunk: int, *, channel: str = 'curve'):
    """读一块点列；没有该字段表示未解析。"""
    fid = curve_field(field_id)
    if not fid:
        return None
    key = rk.fileplay_points_key(path_hash, fid, channel)
    return loads(redis.hget(key, curve_chunk_field(chunk)))


def curve_chunk_ready(redis, path_hash: str, field_id: str, chunk: int, *, channel: str = 'curve') -> bool:
    """块字段存在即已解析（空数组也算）。"""
    fid = curve_field(field_id)
    if not fid:
        return False
    key = rk.fileplay_points_key(path_hash, fid, channel)
    return redis.hget(key, curve_chunk_field(chunk)) is not None


def delete_session(redis, path_hash: str, *, channel: str = 'history') -> None:
    """只删本频道该文件 Hash 及点列；若它是当前会话则清掉 meta。不动另一频道。"""
    ch = rk.fileplay_channel(channel)
    base = rk.fileplay_hash_key(path_hash, ch)
    keys = [base, *_scan_keys(redis, f'{base}:*')]
    _delete_keys(redis, keys)
    current = read_channel_meta(redis, channel=ch)
    want = (path_hash or '').strip().lower()
    if current and str(current.get('pathHash') or '').strip().lower() == want:
        redis.delete(rk.fileplay_meta_key(ch))


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
    """进程启动时清掉本频道残余 Hash / meta，不动另一频道。

    不删 ``ctrl`` / ``worker``：空 ctrl 列表 Redis 会自行去掉；启动时只丢掉过期命令。
    """
    ch = rk.fileplay_channel(channel)
    pattern = f'{rk.fileplay_channel_prefix(ch)}*'
    skip = {rk.fileplay_ctrl_key(ch), rk.fileplay_worker_status_key(ch)}
    keys = [k for k in _scan_keys(redis, pattern) if k not in skip]
    dropped = _delete_keys(redis, keys)
    ctrl = rk.fileplay_ctrl_key(ch)
    try:
        while redis.lpop(ctrl):
            pass
    except Exception:
        pass
    return dropped
