"""曲线列式压缩：实时 ZSet 与文件回放 Hash 共用。

编解码只在 ``encode_payload`` / ``decode_payload``（msgpack + zstd-1）。
换序列化或压缩算法只改这两处，与 Redis 键、采集、HTTP 无关。

实时 ZSet member 另加明文前缀 ``{last_ts}|{n_frames}|{seq}|``，见 ``pack_frames``。
文件回放 Hash 字段只存 ``encode_payload`` 的字节。
"""

from __future__ import annotations

from itertools import count
from typing import Any

import msgpack
import zstandard

CURVE_BLOB_VERSION = 1

_ZSTD_C = zstandard.ZstdCompressor(level=1)
_ZSTD_D = zstandard.ZstdDecompressor()
_SEQ = count(1)


def next_blob_seq() -> int:
    """进程内递增序号，避免同毫秒末时间戳撞 member。"""
    return next(_SEQ)


def ts_token(ts: int | float) -> str:
    """前缀 / 列里用的时间戳字面量：整毫秒不带小数。"""
    f = float(ts)
    if f.is_integer():
        return str(int(f))
    return repr(f)


def _ts_value(ts: int | float) -> int | float:
    f = float(ts)
    return int(f) if f.is_integer() else f


def as_member_bytes(member: Any) -> bytes:
    """ZSET member → bytes（兼容 decode_responses / 测试替身）。"""
    if isinstance(member, bytes):
        return member
    if isinstance(member, bytearray):
        return bytes(member)
    if isinstance(member, memoryview):
        return member.tobytes()
    if isinstance(member, str):
        return member.encode('latin-1', errors='surrogateescape')
    return bytes(member)


def parse_prefix(member: Any) -> tuple[float, int, int, bytes] | None:
    """拆 ``last_ts|n|seq|blob``。前缀不够三段则返回 None。"""
    raw = as_member_bytes(member)
    start = 0
    parts: list[bytes] = []
    for _ in range(3):
        i = raw.find(b'|', start)
        if i < 0:
            return None
        parts.append(raw[start:i])
        start = i + 1
    blob = raw[start:]
    try:
        last_ts = float(parts[0])
        n_frames = int(parts[1])
        seq = int(parts[2])
    except (TypeError, ValueError):
        return None
    if n_frames < 0:
        return None
    return last_ts, n_frames, seq, blob


def drop_oldest_count(members: list[Any], max_frames: int) -> int:
    """``ZRANGE 0 -1`` 最旧在前。丢掉最旧若干 member，使剩余前缀帧数 ≤ max_frames。"""
    cap = max(0, int(max_frames))
    ns: list[int] = []
    for member in members:
        parsed = parse_prefix(member)
        ns.append(parsed[1] if parsed is not None else 1)
    total = sum(ns)
    drop = 0
    i = 0
    while total > cap and i < len(ns):
        total -= ns[i]
        drop += 1
        i += 1
    return drop


def columns_from_rows(
    rows: list[tuple[dict[str, float], int | float]],
) -> tuple[list[int | float], dict[str, list[float | None]]]:
    """``(points, ts)`` 行 → 时间列 + 字段列（缺测为 None）。"""
    timestamps = [_ts_value(ts) for _pts, ts in rows]
    fids: set[str] = set()
    for pts, _ts in rows:
        fids.update(str(fid) for fid in pts)
    columns: dict[str, list[float | None]] = {}
    for fid in sorted(fids):
        if fid in ('v', 't'):
            continue
        columns[fid] = [pts.get(fid) if fid in pts else None for pts, _ts in rows]
    return timestamps, columns


def encode_payload(
    timestamps: list[int | float],
    columns: dict[str, list[float | None]],
) -> bytes:
    """列式 dict → 压缩字节。msgpack / zstd 只出现在这里。"""
    if not timestamps:
        raise ValueError('empty curve blob')
    payload: dict[str, Any] = {
        'v': CURVE_BLOB_VERSION,
        't': [_ts_value(x) for x in timestamps],
    }
    for fid, col in columns.items():
        if not fid or fid in ('v', 't'):
            continue
        payload[str(fid)] = list(col)
    packed = msgpack.packb(payload, use_bin_type=True)
    return _ZSTD_C.compress(packed)


def decode_payload(blob: Any) -> dict[str, Any] | None:
    """``encode_payload`` 的逆；坏包返回 None。"""
    raw = as_member_bytes(blob) if blob else b''
    if not raw:
        return None
    try:
        data = msgpack.unpackb(_ZSTD_D.decompress(raw), raw=False)
    except Exception:
        return None
    if not isinstance(data, dict) or int(data.get('v') or 0) != CURVE_BLOB_VERSION:
        return None
    t_col = data.get('t')
    if not isinstance(t_col, list):
        return None
    return data


def pack_frames(
    timestamps: list[int | float],
    columns: dict[str, list[float | None]],
    *,
    seq: int | None = None,
) -> tuple[bytes, float]:
    """实时 ZSet member：明文前缀 + ``encode_payload``；score=last_ts。"""
    n = len(timestamps)
    if n <= 0:
        raise ValueError('empty curve blob')
    last = timestamps[-1]
    use_seq = next_blob_seq() if seq is None else int(seq)
    blob = encode_payload(timestamps, columns)
    member = f'{ts_token(last)}|{n}|{use_seq}|'.encode('ascii') + blob
    return member, float(last)


def unpack_member(member: Any) -> dict[str, Any] | None:
    """解压实时 ZSet member；坏包返回 None。"""
    parsed = parse_prefix(member)
    if parsed is None:
        return None
    _last, _n, _seq, blob = parsed
    return decode_payload(blob)


def extract_field(data: dict[str, Any], field: str) -> list[dict[str, Any]]:
    """从一包里抽出某字段的 ``{t,v}``，跳过 null。"""
    t_col = data.get('t')
    if not isinstance(t_col, list):
        return []
    col = data.get(str(field))
    if not isinstance(col, list):
        return []
    out: list[dict[str, Any]] = []
    n = min(len(t_col), len(col))
    for i in range(n):
        v = col[i]
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        try:
            tf = float(t_col[i])
        except (TypeError, ValueError):
            continue
        out.append({'t': int(tf) if tf.is_integer() else tf, 'v': fv})
    return out


def points_from_blobs(
    blobs: list[dict[str, Any]],
    field: str,
    *,
    limit: int,
    since_t: int | float | None = None,
    until_t: int | float | None = None,
    newest: bool = False,
) -> list[dict[str, Any]]:
    """多包展开某字段；since_t 开区间；newest 时取末尾 limit 个点。"""
    cap = max(0, int(limit))
    points: list[dict[str, Any]] = []
    for data in blobs:
        for pt in extract_field(data, field):
            t = pt['t']
            if since_t is not None and not (float(t) > float(since_t)):
                continue
            if until_t is not None and float(t) > float(until_t):
                continue
            points.append(pt)
    if cap and len(points) > cap:
        points = points[-cap:] if newest else points[:cap]
    return points


def zrange_all_sync(client: Any, key: str) -> list[Any]:
    """同步客户端读出 ZSET 全部 member（二进制，不解码 UTF-8）。"""
    pool = getattr(client, 'connection_pool', None)
    exec_cmd = getattr(client, 'execute_command', None)
    if pool is not None and callable(exec_cmd):
        from redis.client import NEVER_DECODE

        raw = exec_cmd('ZRANGE', key, 0, -1, **{NEVER_DECODE: []})
        return list(raw or [])
    fn = getattr(client, 'zrange', None)
    if not callable(fn):
        return []
    return list(fn(key, 0, -1) or [])


__all__ = [
    'CURVE_BLOB_VERSION',
    'as_member_bytes',
    'columns_from_rows',
    'decode_payload',
    'drop_oldest_count',
    'encode_payload',
    'extract_field',
    'next_blob_seq',
    'pack_frames',
    'parse_prefix',
    'points_from_blobs',
    'ts_token',
    'unpack_member',
    'zrange_all_sync',
]
