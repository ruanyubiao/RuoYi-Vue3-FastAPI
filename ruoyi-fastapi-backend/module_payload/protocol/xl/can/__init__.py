"""XL 总线协议：遥测校验与解释、遥控组帧、定时遥测请求。CAN 拼帧用 gpcan XL。

相机、单板、CPA 指向在同级子包，由各自模块登记，不走这里。
"""

from __future__ import annotations

from module_payload.protocol.hooks import ProtocolBindings
from module_payload.protocol.xl.can.tc import assemble
from module_payload.protocol.xl.can.tm import TM_CFG_FILE, XlCanTmIngest, reset_tm_mgr, verify_tm
from module_payload.protocol.xl.can.tm_timed import timed_tm

# 未填的钩子走框架默认：发送用 gpcan build_telecommand / build_broadcast，线缆地址用请求值，
# 文件回放按 verify_tm 滑动扫描、表号取 frame[3]
BINDINGS = ProtocolBindings(
    # 遥测解释器类（prepare_bytes / parse_bytes / ingest_*），解释器 id tm_can_xl
    ingest=XlCanTmIngest,
    # 清遥测配置缓存
    reset_tm=reset_tm_mgr,
    # reset_tm 读的配置文件；热重载这个文件时才清
    tm_cfg_files=(TM_CFG_FILE,),
    # 遥控组帧 (order, values, **kwargs) → {'hex', ...}
    assemble=assemble,
    # 遥测内容校验 (raw) → (ok, message, frame)：2 字节长度 + 帧类型 3A + 表号 … 末字节累加和
    verify_tm=verify_tm,
    # 定时遥测请求 (tick) → (间隔秒, build_telemetry_request 参数)：1 秒，第 5、10… 次发缓变 02，其余速变 01
    timed_tm=timed_tm,
)
