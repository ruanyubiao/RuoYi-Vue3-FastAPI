"""
采集进程 ⇄ 主进程 的 Redis Key 命名规范（集中定义）。

所有 Key 统一前缀 ``payload:``，``{device_id}`` 为设备唯一标识：
- CAN 卡:    ``can:{vendor}:{dev_index}``
- CAN 通道:  ``can:{vendor}:{dev_index}:{can_index}``
- 串口:      ``serial:{port}``
- 网络:      ``net:{proto}:{ip}:{port}``

详见 doc/02-数据采集层设计.md。
"""

from __future__ import annotations

PREFIX = 'payload'


# --------------------------------------------------------------- 设备唯一标识
def can_card_id(vendor: int, dev_index: int) -> str:
    """CAN 卡唯一标识（进程粒度：同卡共用一个采集进程）。"""
    return f'can:{vendor}:{dev_index}'


def can_channel_id(vendor: int, dev_index: int, can_index: int) -> str:
    """CAN 通道唯一标识。"""
    return f'can:{vendor}:{dev_index}:{can_index}'


def serial_id(port: str) -> str:
    """串口唯一标识。"""
    return f'serial:{port}'


def net_id(proto: str, ip: str, port: int) -> str:
    """网络连接唯一标识。"""
    return f'net:{proto}:{ip}:{port}'


# --------------------------------------------------------------- 通用 Key
def status_key(device_id: str) -> str:
    """设备/通道状态(JSON)。"""
    return f'{PREFIX}:{device_id}:status'


def heartbeat_key(device_id: str) -> str:
    """进程心跳(时间戳，设 TTL)。"""
    return f'{PREFIX}:{device_id}:heartbeat'


def cmd_queue_key(device_id: str) -> str:
    """指令下发队列(List, LPUSH/BRPOP)。"""
    return f'{PREFIX}:{device_id}:cmd'


def cmd_result_key(device_id: str, cmd_id: str) -> str:
    """单条指令执行结果(JSON, 设 TTL)。"""
    return f'{PREFIX}:{device_id}:cmd:result:{cmd_id}'


def history_key(device_id: str) -> str:
    """发送历史(List, 保留最近 N 条)。"""
    return f'{PREFIX}:{device_id}:history'


# --------------------------------------------------------------- 遥测 / 曲线
def telemetry_key(device_id: str, table_type: str) -> str:
    """某遥测表(type=FF…)最新一帧解析结果(JSON)。"""
    return f'{PREFIX}:{device_id}:tm:{table_type}'


def telemetry_ts_key(device_id: str, table_type: str) -> str:
    """某遥测表最近更新时间。"""
    return f'{PREFIX}:{device_id}:tm:{table_type}:ts'


def curve_key(device_id: str, table_type: str, field: str) -> str:
    """遥测量曲线时间序列(ZSet/Stream，限量)。"""
    return f'{PREFIX}:{device_id}:curve:{table_type}:{field}'


def curve_subscribe_key(device_id: str) -> str:
    """曲线订阅集合(采集进程据此决定记录哪些遥测量)。"""
    return f'{PREFIX}:{device_id}:curve:subscribe'


# --------------------------------------------------------------- 图像 / 工程遥测
def image_key(device_id: str) -> str:
    """串口最新整帧图像(二进制 + 元数据)。"""
    return f'{PREFIX}:{device_id}:image'


def lvds_key(device_id: str, signal: str) -> str:
    """工程遥测(LVDS)高速信号点序列(Stream，限频/限量)。"""
    return f'{PREFIX}:{device_id}:lvds:{signal}'
