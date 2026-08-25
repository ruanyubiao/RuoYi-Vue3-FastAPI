"""地检平台业务常量（不建类型字典表，代码侧枚举）。"""

from __future__ import annotations

# 数据大类 data_kind
DATA_KIND_TM = 'tm'
DATA_KIND_TC = 'tc'
DATA_KIND_ENG = 'eng'
DATA_KIND_IMAGE = 'image'

# 通道来源 src_kind
SRC_KIND_CAN = 'can'
SRC_KIND_SERIAL = 'serial'
SRC_KIND_UDP = 'udp'
SRC_KIND_TCP = 'tcp'
SRC_KIND_HTTP = 'http'

# 解释器 ID（注册表键）
PARSER_TM_CAN_BIU = 'tm_can_biu'  # BIU-CAN 遥测复合帧
PARSER_TM_CAN_XL = 'tm_can_xl'  # XL-CAN 遥测复合帧
PARSER_CAMERA_SC_LINK41EP = 'camera_sc_link41ep'
PARSER_XL_BOARD_TM = 'xl_board_tm'

# 组装器 ID（注册表键）；空 / passthrough = 透传（收什么交什么）
ASSEMBLER_PASSTHROUGH = 'passthrough'
ASSEMBLER_ENG_TM_SUBPKT = 'eng_tm_subpkt'
ASSEMBLER_CAMERA_IMAGE_D6 = 'camera_image_d6'
ASSEMBLER_CAN_BIU = 'can_biu'
ASSEMBLER_CAN_XL = 'can_xl'

# 仅 CAN 连接可选的组装器
CAN_ONLY_ASSEMBLERS = frozenset({ASSEMBLER_CAN_BIU, ASSEMBLER_CAN_XL})

# 总线遥测表存储键前缀（BIU-TeleMetryCfg / XL-TeleMetryCfg）；Redis/归档用 BIU:FF / XL:FF
TM_BUS_FAMILY_BIU = 'BIU'
TM_BUS_FAMILY_XL = 'XL'


def make_bus_tm_key(family: str | None, local_key: str) -> str:
    """拼总线遥测存储键：BIU:FF / XL:FF。"""
    fam = TM_BUS_FAMILY_XL if (family or '').strip().lower() == 'xl' else TM_BUS_FAMILY_BIU
    return f'{fam}:{(local_key or "").strip().upper()}'


def split_tm_table_key(table_key: str) -> tuple[str | None, str]:
    """拆存储键。BIU:FF → ('biu','FF')；无前缀则 (None, KEY)（单板/相机等）。"""
    s = (table_key or '').strip().upper()
    if ':' in s:
        fam, local = s.split(':', 1)
        if fam in (TM_BUS_FAMILY_BIU, TM_BUS_FAMILY_XL) and local:
            return fam.lower(), local
    return None, s


def tm_parse_key(table_key: str) -> str:
    """TeleMetryCfgManager 用的文件内本地 key。"""
    return split_tm_table_key(table_key)[1]

# Redis 热层 / 采集侧限额（各模块统一引用，避免漂移）
CURVE_MAX_POINTS = 50000
HISTORY_MAX = 100
IO_LOG_MAX = 1000
# 收发日志 HEX 最多展示的原始字节数（超长截断，len 仍记真实长度）
IO_LOG_HEX_MAX_BYTES = 256
# Redis 预览 IO 日志最小间隔（文件落盘不节流）
IO_LOG_MIN_INTERVAL_S = 0.5
ERROR_LOG_MAX = 100
HEARTBEAT_TTL = 15
CMD_RESULT_TTL = 120


def infer_src_kind(src_param: str, fallback: str = SRC_KIND_CAN) -> str:
    p = (src_param or '').lower()
    if p.startswith('can:') or p.startswith('can'):
        return SRC_KIND_CAN
    if p.startswith('serial:') or p.startswith('com'):
        return SRC_KIND_SERIAL
    if p.startswith('udp:') or p.startswith('udp'):
        return SRC_KIND_UDP
    if p.startswith('tcp:') or p.startswith('tcp'):
        return SRC_KIND_TCP
    if p.startswith('http:') or p.startswith('http'):
        return SRC_KIND_HTTP
    return fallback


_CAN_TM_PARSERS = frozenset({PARSER_TM_CAN_BIU, PARSER_TM_CAN_XL})


def should_archive_tm_mysql(
    src_kind: str | None = None,
    src_param: str = '',
    parser_id: str | None = None,
) -> bool:
    """仅 CAN 遥测写 MySQL。串口/UDP/TCP 不归档；HTTP 注入只归档 CAN 解释器。"""
    kind = (src_kind or '').strip().lower()
    if not kind:
        kind = infer_src_kind(src_param, fallback='')
    if kind in (SRC_KIND_SERIAL, SRC_KIND_UDP, SRC_KIND_TCP):
        return False
    if kind == SRC_KIND_CAN:
        return True
    if kind == SRC_KIND_HTTP:
        return (parser_id or '') in _CAN_TM_PARSERS
    return False
