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
SRC_KIND_HTTP = 'http'

# 解释器 ID（注册表键）
PARSER_TM_CAN_YC = 'tm_can_yc'


def infer_src_kind(src_param: str, fallback: str = SRC_KIND_CAN) -> str:
    p = (src_param or '').lower()
    if p.startswith('can:') or p.startswith('can'):
        return SRC_KIND_CAN
    if p.startswith('serial:') or p.startswith('com'):
        return SRC_KIND_SERIAL
    if p.startswith('udp:') or p.startswith('udp'):
        return SRC_KIND_UDP
    if p.startswith('http:') or p.startswith('http'):
        return SRC_KIND_HTTP
    return fallback or SRC_KIND_CAN
