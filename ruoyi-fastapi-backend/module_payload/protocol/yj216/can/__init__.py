"""YJ216 总线协议：遥测校验与解释、遥控组帧与 CAN 切片、线缆地址、定时遥测。CAN 拼帧用 gpcan YJ216。"""

from __future__ import annotations

from module_payload.protocol.hooks import ProtocolBindings
from module_payload.protocol.yj216.can.tc import assemble, build_can_command, node_addr
from module_payload.protocol.yj216.can.tm import FILEPLAY, TM_CFG_FILE, Yj216CanTmIngest, reset_tm_mgr, verify_tm
from module_payload.protocol.yj216.can.tm_timed import timed_tm

BINDINGS = ProtocolBindings(
    # 遥测解释器类（prepare_bytes / parse_bytes / ingest_*），解释器 id tm_can_yj216
    ingest=Yj216CanTmIngest,
    # 清遥测配置缓存
    reset_tm=reset_tm_mgr,
    # reset_tm 读的配置文件；热重载这个文件时才清
    tm_cfg_files=(TM_CFG_FILE,),
    # 遥控组帧 (order, values, **kwargs) → {'hex', ...}：短指令原样，check=是 时追加 SUM
    assemble=assemble,
    # 遥测内容校验 (raw) → (ok, message, frame)：3A + 表号 + 35 字节 + SUM，没有长度前缀
    verify_tm=verify_tm,
    # 总线表的文件回放规格：帧没有长度前缀，默认的滑动扫描不适用，按定长 38 字节扫、表号取 frame[1]
    fileplay=FILEPLAY,
    # 业务指令组 CAN 帧 (builder, raw, *, broadcast)：不超过 8 字节走 gpcan，更长的按 8 字节切，不另加长度
    build_can_command=build_can_command,
    # 定时遥测请求 (tick) → (间隔秒, build_telemetry_request 参数)：1 秒，只发 FF
    timed_tm=timed_tm,
    # 线缆目标地址 (请求值) → 实际地址：固定 Yj216NodeAddr.LCD_PAYLOAD，忽略请求值
    node_addr=node_addr,
)
