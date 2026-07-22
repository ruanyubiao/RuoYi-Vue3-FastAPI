"""
采集进程 ⇄ 主进程 的 Redis Key 命名规范（集中定义）。

所有 Key 统一前缀 ``payload:``，``{device_id}`` 为设备唯一标识：
- CAN 卡:    ``can:{vendor}:{dev_index}``
- CAN 通道:  ``can:{vendor}:{dev_index}:{can_index}``（含厂商）
- 串口:      ``serial:{port}``
- 网络:      ``net:{proto}:{ip}:{port}``

详见 doc/02-数据采集层设计.md。
"""

from __future__ import annotations

PREFIX = 'payload'


# --------------------------------------------------------------- 设备唯一标识
def can_card_id(vendor: int, dev_index: int) -> str:
    """CAN 卡唯一标识（进程粒度：同厂商+设备索引共用一个采集进程）。"""
    return f'can:{vendor}:{dev_index}'


def can_channel_id(vendor: int, dev_index: int, can_index: int) -> str:
    """CAN 通道唯一标识：can:{厂商}:{设备索引}:{通道号}。"""
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


def ctrl_queue_key(device_id: str) -> str:
    """采集进程控制队列(开/关通道、停止)。"""
    return f'{PREFIX}:{device_id}:ctrl'


def cmd_result_key(device_id: str, cmd_id: str) -> str:
    """单条指令执行结果(JSON, 设 TTL)。"""
    return f'{PREFIX}:{device_id}:cmd:result:{cmd_id}'


def history_key(device_id: str) -> str:
    """发送历史(List, 保留最近 N 条)。"""
    return f'{PREFIX}:{device_id}:history'


def io_log_key(device_id: str) -> str:
    """原始收发日志(List, JSON；控制页助手显示)。"""
    return f'{PREFIX}:{device_id}:io'


def io_log_seq_key(device_id: str) -> str:
    """原始收发日志序号。"""
    return f'{PREFIX}:{device_id}:io:seq'


# --------------------------------------------------------------- 指令序列执行
def seq_run_key(run_id: str) -> str:
    """单次序列执行进度/详情(JSON)。"""
    return f'{PREFIX}:seq:run:{run_id}'


def seq_run_history_key(seq_id: int) -> str:
    """某序列最近执行 runId 列表(List)。"""
    return f'{PREFIX}:seq:{seq_id}:runs'


# --------------------------------------------------------------- 遥测 / 曲线
def telemetry_latest_key(data_sub: str) -> str:
    """按子类型的最新一帧(跨来源，后写覆盖)。"""
    return f'{PREFIX}:tm:{(data_sub or "").upper()}:latest'


def telemetry_latest_ts_key(data_sub: str) -> str:
    return f'{PREFIX}:tm:{(data_sub or "").upper()}:latest:ts'


def curve_latest_key(data_sub: str, field: str) -> str:
    """按子类型共享曲线 ZSet。"""
    return f'{PREFIX}:tm:{(data_sub or "").upper()}:curve:{field}'


def archive_queue_key() -> str:
    """遥测帧归档异步队列(List)。"""
    return f'{PREFIX}:archive:queue'


def tx_queue_key() -> str:
    """遥控发送记录异步队列(List)。"""
    return f'{PREFIX}:tx:queue'


def session_key(src_kind: str, src_param: str) -> str:
    """设备会话（打开状态 + 解释器绑定）。"""
    return f'{PREFIX}:session:{src_kind}:{src_param}'


# --------------------------------------------------------------- 图像 / 工程遥测 / 组装
def image_key(device_id: str) -> str:
    """串口最新整帧图像(二进制 + 元数据)。"""
    return f'{PREFIX}:{device_id}:image'


def lvds_key(device_id: str, signal: str) -> str:
    """工程遥测(LVDS)高速信号点序列(Stream，限频/限量)。"""
    return f'{PREFIX}:{device_id}:lvds:{signal}'


def assembled_latest_key(device_id: str) -> str:
    """组装器产出的最新完整载荷(JSON：hex/meta/ts/assemblerId)。调试查此键。"""
    return f'{PREFIX}:{device_id}:assembled:latest'


def assembled_log_key(device_id: str) -> str:
    """组装完成历史(List，最近 N 条 JSON)。"""
    return f'{PREFIX}:{device_id}:assembled'


def assembled_error_key(device_id: str) -> str:
    """最近一次组装/校验失败(JSON)。兼容旧键；优先查 payload:error:assembler。"""
    return f'{PREFIX}:{device_id}:assembled:error'


def error_type_key(error_type: str) -> str:
    """按类型区分的错误数组(List)：payload:error:assembler / payload:error:tm / …"""
    return f'{PREFIX}:error:{error_type}'


def error_type_latest_key(error_type: str) -> str:
    """某类型最近一次错误(JSON)：payload:error:latest:{type}。"""
    return f'{PREFIX}:error:latest:{error_type}'
