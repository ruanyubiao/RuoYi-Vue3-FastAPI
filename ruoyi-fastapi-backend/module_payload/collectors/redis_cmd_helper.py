"""Redis 批量命令生成器：纯函数，不持有连接。

采集侧业务只调这里的函数拿到 ``RedisOp`` 列表，再交
:class:`~module_payload.collectors.collector_redis.CollectorRedis` 的
``write_batch``；业务不写 ``lpush`` / ``zadd`` 等原生动词。

序列化：每个函数最后一个参数 ``dumps`` 为回调，生成命令时就把 dict/list 编码成
字符串；str / bytes / 数字原样透传。默认 :func:`dumps_json`。
"""

from __future__ import annotations

from typing import Any, Callable, NamedTuple

from module_payload import redis_keys as rk
from module_payload.constants import (
    ASSEMBLED_LOG_MAX,
    CMD_RESULT_TTL,
    CURVE_MAX_POINTS,
    ERROR_LOG_MAX,
    HEARTBEAT_TTL,
    HISTORY_MAX,
    IO_LOG_MAX,
    STREAM_FLUSH_ACK_TTL,
    TM_FPS_TTL_S,
)
from module_payload.store.jsonutil import dumps_json

Dumps = Callable[[Any], str]


class RedisOp(NamedTuple):
    """一条待执行的 Redis 命令：``cmd`` 为 redis-py 方法名，``args`` 为位置参数。"""

    cmd: str
    args: tuple[Any, ...]


def _enc(value: Any, dumps: Dumps | None) -> Any:
    """dict / list 走回调序列化；str / bytes / 数字原样透传。"""
    if isinstance(value, (str, bytes, bytearray, int, float)):
        return value
    return (dumps or dumps_json)(value)


def resolve_list_cap(key: str) -> int | None:
    """有长度上限的 List 返回上限，其它（队列等）返回 None。

    定时裁剪按此判断；写入路径不做长度校验。
    """
    k = str(key or '')
    if k.endswith(':io') or k.endswith(':io:stream'):
        return IO_LOG_MAX
    if k.endswith(':history'):
        return HISTORY_MAX
    if k.endswith(':assembled'):
        return ASSEMBLED_LOG_MAX
    if k.startswith(f'{rk.PREFIX}:error:') and not k.startswith(f'{rk.PREFIX}:error:latest:'):
        return ERROR_LOG_MAX
    return None


def resolve_zset_cap(key: str) -> int | None:
    """曲线 ZSet 返回点数上限；其它返回 None。写入路径不裁，由封装 1s 定时裁。"""
    k = str(key or '')
    if k.startswith(f'{rk.PREFIX}:tm:') and ':curve:' in k:
        return CURVE_MAX_POINTS
    return None


# --------------------------------------------------------------- 预览 / 调试流
def io_log(device_id: str, entries: list[dict[str, Any]], *, dumps: Dumps | None = None) -> list[RedisOp]:
    """预览收发日志：逐条 LPUSH 到 ``payload:{id}:io``（裁剪交定时器）。"""
    key = rk.io_log_key(device_id)
    return [RedisOp('lpush', (key, _enc(entry, dumps))) for entry in entries or []]


def io_log_seq(device_id: str, seq: int) -> list[RedisOp]:
    """修复预览日志序号（本地水位超前 Redis 时）。"""
    return [RedisOp('set', (rk.io_log_seq_key(device_id), str(int(seq))))]


def io_stream(
    device_id: str,
    entries: list[dict[str, Any]],
    *,
    last_seq: int | None = None,
    dumps: Dumps | None = None,
) -> list[RedisOp]:
    """调试页全量流：逐条 LPUSH，并可同时更新已刷序号。"""
    key = rk.io_stream_key(device_id)
    ops = [RedisOp('lpush', (key, _enc(entry, dumps))) for entry in entries or []]
    if last_seq is not None:
        ops.append(RedisOp('set', (rk.io_stream_seq_key(device_id), str(int(last_seq)))))
    return ops


def io_stream_ack(device_id: str, req_id: str, *, ttl: int = STREAM_FLUSH_ACK_TTL) -> list[RedisOp]:
    """调试页刷/清完成应答。"""
    return [RedisOp('setex', (rk.io_stream_flush_ack_key(device_id, str(req_id)), int(ttl), '1'))]


# --------------------------------------------------------------- 遥测
def curves(
    rows: list[tuple[str, dict[str, float], int]],
    *,
    max_points: int = CURVE_MAX_POINTS,
    dumps: Dumps | None = None,
) -> list[RedisOp]:
    """曲线点数组 → 命令数组。

    ``rows`` 为 ``(表键, {字段ID: 数值}, ts_ms)``；各行 ts_ms 须已互不相同。
    同一字段多帧合并成一条 ``ZADD``（mapping 含全部 member），不在写入路径裁剪。
    ``max_points`` 保留给调用方/测试对照，实际裁剪由封装按 ``resolve_zset_cap`` 定时做。
    """
    grouped: dict[str, dict[str, float]] = {}
    for tkey, points, ts_ms in rows or []:
        if not points:
            continue
        table = (tkey or '').upper()
        for fid, val in points.items():
            key = rk.curve_latest_key(table, fid)
            grouped.setdefault(key, {})[f'{ts_ms}|{val}'] = float(ts_ms)
    _ = max_points
    _ = dumps
    return [RedisOp('zadd', (key, mapping)) for key, mapping in grouped.items()]


def latest(table_key: str, payload: dict[str, Any], ts: str, *, dumps: Dumps | None = None) -> list[RedisOp]:
    """遥测表格最新一帧：整表一份 JSON + 时间戳。"""
    tkey = (table_key or '').upper()
    return [
        RedisOp('set', (rk.telemetry_latest_key(tkey), _enc(payload, dumps))),
        RedisOp('set', (rk.telemetry_latest_ts_key(tkey), ts)),
    ]


def tm_fps(table_key: str, fps: float, *, ttl: int = TM_FPS_TTL_S) -> list[RedisOp]:
    """按表类型写入接收帧率（近 1s 滑窗，带 TTL）。"""
    tkey = (table_key or '').upper()
    if not tkey:
        return []
    return [RedisOp('setex', (rk.telemetry_fps_key(tkey), int(ttl), f'{float(fps):.1f}'))]


def archive_queue(event: dict[str, Any], *, dumps: Dumps | None = None) -> list[RedisOp]:
    """遥测帧归档队列（无上限，不裁剪）。"""
    return [RedisOp('lpush', (rk.archive_queue_key(), _enc(event, dumps)))]


# --------------------------------------------------------------- 组装 / 错误
def assembled(device_id: str, entry: dict[str, Any], *, dumps: Dumps | None = None) -> list[RedisOp]:
    """组装完成：latest + 历史 List。"""
    dumped = _enc(entry, dumps)
    return [
        RedisOp('set', (rk.assembled_latest_key(device_id), dumped)),
        RedisOp('lpush', (rk.assembled_log_key(device_id), dumped)),
    ]


def error(
    error_type: str,
    entry: dict[str, Any],
    *,
    device_id: str = '',
    dumps: Dumps | None = None,
) -> list[RedisOp]:
    """流水线错误：latest + 按类型 List（组装错误再写设备兼容键）。"""
    etype = (error_type or 'session').strip() or 'session'
    dumped = _enc(entry, dumps)
    ops = [
        RedisOp('set', (rk.error_type_latest_key(etype), dumped)),
        RedisOp('lpush', (rk.error_type_key(etype), dumped)),
    ]
    if device_id and etype == 'assembler':
        ops.append(RedisOp('set', (rk.assembled_error_key(device_id), dumped)))
    return ops


# --------------------------------------------------------------- 设备状态 / 历史
def history(device_id: str, entry: dict[str, Any], *, dumps: Dumps | None = None) -> list[RedisOp]:
    """发送历史 List。"""
    return [RedisOp('lpush', (rk.history_key(device_id), _enc(entry, dumps)))]


def tx_queue(event: dict[str, Any], *, dumps: Dumps | None = None) -> list[RedisOp]:
    """遥控发送记录归档队列（无上限，不裁剪）。"""
    return [RedisOp('lpush', (rk.tx_queue_key(), _enc(event, dumps)))]


def heartbeat(device_id: str, ts: str, *, ttl: int = HEARTBEAT_TTL) -> list[RedisOp]:
    """进程心跳（带 TTL）。"""
    return [RedisOp('setex', (rk.heartbeat_key(device_id), int(ttl), ts))]


def status(device_id: str, payload: dict[str, Any], *, dumps: Dumps | None = None) -> list[RedisOp]:
    """设备 / 通道状态。"""
    return [RedisOp('set', (rk.status_key(device_id), _enc(payload, dumps)))]


def cmd_result(
    device_id: str,
    cmd_id: str,
    result: dict[str, Any],
    *,
    ttl: int = CMD_RESULT_TTL,
    dumps: Dumps | None = None,
) -> list[RedisOp]:
    """单条指令执行结果（带 TTL）。"""
    return [RedisOp('setex', (rk.cmd_result_key(device_id, str(cmd_id)), int(ttl), _enc(result, dumps)))]


def image_meta(device_id: str, meta: dict[str, Any], *, dumps: Dumps | None = None) -> list[RedisOp]:
    """相机图像元数据（含相对路径；图像本体在磁盘）。"""
    return [RedisOp('set', (f'{rk.PREFIX}:{device_id}:image:meta', _enc(meta, dumps)))]


def delete(keys: list[str]) -> list[RedisOp]:
    """删除若干 key（与写入同一 FIFO，不会被后到的写入插队）。"""
    real = [k for k in keys or [] if k]
    return [RedisOp('delete', tuple(real))] if real else []


def set_value(key: str, value: Any, *, dumps: Dumps | None = None) -> list[RedisOp]:
    """单个 key 写入（无对应领域函数时用）。"""
    return [RedisOp('set', (key, _enc(value, dumps)))]


__all__ = [
    'RedisOp',
    'archive_queue',
    'assembled',
    'cmd_result',
    'curves',
    'delete',
    'error',
    'heartbeat',
    'history',
    'image_meta',
    'io_log',
    'io_log_seq',
    'io_stream',
    'io_stream_ack',
    'latest',
    'resolve_list_cap',
    'resolve_zset_cap',
    'set_value',
    'status',
    'tm_fps',
    'tx_queue',
]
