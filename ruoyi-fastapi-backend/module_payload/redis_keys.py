"""
采集进程 ⇄ 主进程 的 Redis Key 命名规范（集中定义）。

规则：``payload:{功能}:{细分}:…``。Insight 第一层只有功能名。
禁止同名内容键与目录并存（有子键就把内容放进目录；目录里只有一把钥则压平）。

``{device_id}`` 为设备唯一标识（``dev`` 下实例在前）：
- CAN 卡:    ``can:{vendor}:{dev_index}``
- CAN 通道:  ``can:{vendor}:{dev_index}:{can_index}``（含厂商）
- 串口:      ``serial:{port}``
- 网络:      ``{proto}:{ip}:{port}``（``udp:...`` / ``tcp:...``）
- 功能来源:  ``source:{source}``（如 ``source:camera_ctrl``；单板传输信息按来源聚合）

预览收发日志只写来源键（传输信息）；调试页走 ``io:stream:log``：
- ``payload:dev:source:{source}:io:log`` — 单板/相机页按打开来源查看（换 COM 口仍接续）
- home / 无 source 不写预览 Redis

详见 doc/02-数据采集层设计.md。
"""

from __future__ import annotations

PREFIX = 'payload'


def _dev(device_id: str, suffix: str) -> str:
    """设备键：``payload:dev:{deviceId}:{suffix}``。"""
    return f'{PREFIX}:dev:{device_id}:{suffix}'


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
    """网络连接唯一标识：udp:{ip}:{port} / tcp:{ip}:{port}。

    只含本机绑定地址与端口。UDP 远程对端（remote_host/remote_port）
    仅作默认发送目标，不进入 deviceId。
    """
    p = (proto or 'udp').strip().lower() or 'udp'
    return f'{p}:{ip}:{port}'


def source_id(source: str) -> str:
    """功能来源标识（单板页传输信息按来源聚合，与具体串口号解耦）。"""
    return f'source:{(source or "").strip()}'


# --------------------------------------------------------------- 设备 Key（payload:dev:{id}:…）
def status_key(device_id: str) -> str:
    """设备/通道状态(JSON)。"""
    return _dev(device_id, 'status')


def heartbeat_key(device_id: str) -> str:
    """进程心跳(时间戳，设 TTL)。"""
    return _dev(device_id, 'heartbeat')


def cmd_queue_key(device_id: str) -> str:
    """指令下发队列(List, LPUSH/BRPOP)。``cmd`` 只做目录。"""
    return _dev(device_id, 'cmd:queue')


def collector_ctrl_id(device_id: str) -> str:
    """控制队列用的进程键：CAN 通道落到卡 id，串口/网口即 device_id。"""
    parts = str(device_id or '').split(':')
    if len(parts) >= 4 and parts[0] == 'can':
        return ':'.join(parts[:3])
    return str(device_id or '')


def ctrl_queue_key(device_id: str) -> str:
    """采集进程控制队列(开/关通道、停止)。"""
    return _dev(device_id, 'ctrl')


def cmd_result_key(device_id: str, cmd_id: str) -> str:
    """单条指令执行结果(JSON, 设 TTL)。"""
    return _dev(device_id, f'cmd:result:{cmd_id}')


def history_key(device_id: str) -> str:
    """旧的按硬件键的发送历史。新写入走 ``source_history_key``。"""
    return _dev(device_id, 'history')


def source_history_key(source: str) -> str:
    """按页面来源的发送历史：``payload:dev:source:{source}:history``。"""
    name = (source or '').strip()
    if name.startswith('source:'):
        name = name[len('source:'):]
    return _dev(source_id(name), 'history')


def io_log_key(device_id: str) -> str:
    """原始收发日志(List, JSON；控制页助手显示)。``io`` 只做目录。"""
    return _dev(device_id, 'io:log')


def io_log_seq_key(device_id: str) -> str:
    """原始收发日志序号。"""
    return _dev(device_id, 'io:seq')


def io_stream_key(device_id: str) -> str:
    """调试页全量收发流(List, JSON；内存环缓，请求/退出时刷入)。``stream`` 只做目录。"""
    return _dev(device_id, 'io:stream:log')


def io_stream_seq_key(device_id: str) -> str:
    """调试页全量收发流序号。"""
    return _dev(device_id, 'io:stream:seq')


def io_stream_flush_ack_key(device_id: str, req_id: str) -> str:
    """调试页 stream 刷 Redis 完成应答。"""
    return _dev(device_id, f'io:stream:flush:{req_id}')


def io_stream_on_key(device_id: str) -> str:
    """调试页 recv 是否写入 stream：``1`` / ``0``。采集进程为真值。"""
    return _dev(device_id, 'io:stream:on')


# --------------------------------------------------------------- 指令序列执行
def seq_run_key(run_id: str) -> str:
    """单次序列执行进度/详情(JSON)。"""
    return f'{PREFIX}:seq:run:{run_id}'


def seq_run_history_key(seq_id: int) -> str:
    """某序列最近执行 runId 列表(List)。"""
    return f'{PREFIX}:seq:runs:{seq_id}'


# --------------------------------------------------------------- 遥测 / 曲线
def telemetry_latest_key(data_sub: str) -> str:
    """按子类型的最新一帧(跨来源，后写覆盖)。"""
    return f'{PREFIX}:tm:{(data_sub or "").upper()}:latest'


def telemetry_latest_ts_key(data_sub: str) -> str:
    """最新一帧对应的时间戳 Redis key。"""
    return f'{PREFIX}:tm:{(data_sub or "").upper()}:latestts'


def telemetry_fps_key(data_sub: str) -> str:
    """该表类型近 1s 接收帧率（SETEX，独立于 latest）。"""
    return f'{PREFIX}:tm:{(data_sub or "").upper()}:fps'


def curve_latest_key(data_sub: str, field: str | None = None) -> str:
    """整表曲线 ZSet ``payload:tm:{type}:curve``。field 已废弃，保留形参兼容旧调用。"""
    _ = field
    return f'{PREFIX}:tm:{(data_sub or "").upper()}:curve'


def archive_queue_key() -> str:
    """遥测帧归档异步队列(List)。"""
    return f'{PREFIX}:mysql:archive'


def tx_queue_key() -> str:
    """遥控发送记录异步队列(List)。"""
    return f'{PREFIX}:mysql:tx'


def session_key(src_kind: str, src_param: str) -> str:
    """设备会话。src_param 已带种类前缀时不再叠一层。

    ``serial`` + ``serial:COM3`` → ``payload:session:serial:COM3``
    ``can`` + ``can:3:0:0`` → ``payload:session:can:3:0:0``
    """
    kind = (src_kind or '').strip()
    param = (src_param or '').strip()
    if kind and (param == kind or param.startswith(f'{kind}:')):
        return f'{PREFIX}:session:{param}'
    if kind:
        return f'{PREFIX}:session:{kind}:{param}'
    return f'{PREFIX}:session:{param}'


# --------------------------------------------------------------- 图像 / 工程遥测 / 组装
def image_key(device_id: str) -> str:
    """串口图像占位键（本体在磁盘；元数据见 ``image_meta_key``）。``image`` 只做目录。"""
    return _dev(device_id, 'image:data')


def image_meta_key(device_id: str) -> str:
    """相机图像元数据（含相对路径）。"""
    return _dev(device_id, 'image:meta')


def lvds_key(device_id: str, signal: str) -> str:
    """工程遥测(LVDS)高速信号点序列(Stream，限频/限量)。``lvds`` 只做目录。"""
    return _dev(device_id, f'lvds:{signal}')


def assembled_latest_key(device_id: str) -> str:
    """组装器产出的最新完整载荷(JSON：hex/meta/ts/assemblerId)。调试查此键。"""
    return _dev(device_id, 'assembled:latest')


def assembled_log_key(device_id: str) -> str:
    """组装完成历史(List，最近 N 条 JSON)。与 latest / error 同级。"""
    return _dev(device_id, 'assembled:log')


def assembled_error_key(device_id: str) -> str:
    """最近一次组装/校验失败(JSON)。兼容旧键；优先查 payload:error:assembler:log。"""
    return _dev(device_id, 'assembled:error')


def error_type_key(error_type: str) -> str:
    """按类型区分的错误数组(List)：payload:error:{type}:log。"""
    return f'{PREFIX}:error:{error_type}:log'


def error_type_latest_key(error_type: str) -> str:
    """某类型最近一次错误(JSON)：payload:error:{type}:latest。"""
    return f'{PREFIX}:error:{error_type}:latest'


def tm_calc_history_key() -> str:
    """遥测计算调试历史(List, 最近 N 条 JSON)。"""
    return f'{PREFIX}:tm:calc:history'


def fileplay_path_hash(path: str) -> str:
    """文件回放会话哈希：规范化绝对路径的 SHA1 前 16 位。

    normcase 避免 Windows 盘符大小写导致同一文件两个 Hash。
    """
    import hashlib
    import os

    norm = os.path.normcase(os.path.abspath(str(path or '').strip()))
    return hashlib.sha1(norm.encode('utf-8')).hexdigest()[:16]


FILEPLAY_CHANNELS = ('history', 'curve')


def fileplay_channel(channel: str | None) -> str:
    """history=历史文件数据，curve=历史文件曲线。非法值落到 history。"""
    c = (channel or '').strip().lower()
    return c if c in FILEPLAY_CHANNELS else 'history'


def fileplay_channel_prefix(channel: str | None = 'history') -> str:
    """该频道全部 key 的前缀：``payload:play:file:{history|curve}:``。"""
    return f'{PREFIX}:play:file:{fileplay_channel(channel)}:'


def fileplay_file_prefix(path_hash: str, channel: str | None = 'history') -> str:
    """某文件全部叶子键前缀：``payload:play:file:{ch}:{hash}:``。"""
    h = (path_hash or '').strip().lower()
    return f'{fileplay_channel_prefix(channel)}{h}:'


def _fileplay_leaf(path_hash: str, channel: str | None, leaf: str) -> str:
    return f'{fileplay_file_prefix(path_hash, channel)}{leaf}'


def fileplay_hash_from_leaf_key(key: str) -> str:
    """``payload:play:file:{ch}:{hash}:{leaf}`` → hash。对不上返回空串。"""
    parts = str(key or '').split(':')
    if len(parts) >= 6 and parts[0] == PREFIX and parts[1] == 'play' and parts[2] == 'file':
        return parts[4].strip().lower()
    return ''


def fileplay_hash_key(path_hash: str, channel: str | None = 'history') -> str:
    """某频道下该文件的数据 Hash，禁止与 ``payload:tm:*`` 混用。

    history：``payload:play:file:history:{pathHash}:data``，字段为帧序号 ``{n}``。
    curve：``payload:play:file:curve:{pathHash}:data``，字段为万帧压缩块序号 ``0`` / ``1`` / …。
    同文件的 meta / worker / ctrl / touch 挂在同一 ``{hash}`` 目录下。
    """
    return _fileplay_leaf(path_hash, channel, 'data')


def fileplay_points_key(path_hash: str, field_id: str | None = None, channel: str | None = 'curve') -> str:
    """整表万帧压缩块所在 Hash。field_id 已废弃。

    curve 频道与 ``fileplay_hash_key`` 同一把钥匙：``payload:play:file:curve:{pathHash}:data``。
    其它频道用 ``…:{hash}:pts``，避免和帧序号字段撞车。
    """
    _ = field_id
    ch = fileplay_channel(channel)
    if ch == 'curve':
        return fileplay_hash_key(path_hash, 'curve')
    return _fileplay_leaf(path_hash, ch, 'pts')


def fileplay_job_key(channel: str | None = 'curve') -> str:
    """当前抽点任务完成标记（STRING），不进文件 Hash。"""
    return f'{PREFIX}:play:file:{fileplay_channel(channel)}:job'


def fileplay_meta_key(path_hash: str, channel: str | None = 'history') -> str:
    """该文件会话 meta（JSON）：``payload:play:file:{ch}:{hash}:meta``。"""
    return _fileplay_leaf(path_hash, channel, 'meta')


def fileplay_ctrl_key(path_hash: str, channel: str | None = 'history') -> str:
    """该文件子进程控制队列(List, LPUSH/BRPOP)。"""
    return _fileplay_leaf(path_hash, channel, 'ctrl')


def fileplay_worker_status_key(path_hash: str, channel: str | None = 'history') -> str:
    """该文件子进程心跳(JSON)。"""
    return _fileplay_leaf(path_hash, channel, 'worker')


def fileplay_touch_key(path_hash: str, channel: str | None = 'history') -> str:
    """该文件最后访问时间（unix 秒 STRING），与 meta 分开以免打架。"""
    return _fileplay_leaf(path_hash, channel, 'touch')


def canplay_hash_key(session: str) -> str:
    """历史 CAN 表回放会话 Hash（MySQL 供数，不经文件进程）。

    子字段：``meta`` + 帧序号 ``{n}``。TTL 由服务层 expire 1h。
    """
    s = (session or '').strip()
    return f'{PREFIX}:play:can:{s}'
