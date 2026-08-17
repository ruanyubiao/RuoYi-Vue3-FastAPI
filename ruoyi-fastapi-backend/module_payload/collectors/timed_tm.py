"""BIU / XL 定时遥测请求轮询顺序（与 Demo 规则一致，无硬件依赖）。"""

from __future__ import annotations

# BIU 手动下拉 1~5：FF / FD / FB / F9 / F7（FE、FC 仅手动）
BIU_TM_CODE_1 = 0xFF
BIU_TM_CODES_2_TO_5 = (0xFD, 0xFB, 0xF9, 0xF7, 0xFE, 0xFC)

XL_TM_FAST = 0x01
XL_TM_SLOW = 0x02


def next_biu_tm_data_code(tick: int) -> int:
    """0.5s 一次。1-based 奇数次发类型1(FF)，偶数次轮流类型 2~5。"""
    n = int(tick) + 1
    if n % 2 == 1:
        return BIU_TM_CODE_1
    return BIU_TM_CODES_2_TO_5[(n // 2 - 1) % len(BIU_TM_CODES_2_TO_5)]


def next_xl_tm_sec_header(tick: int) -> int:
    """1s 一次。第 5、10、15… 秒发缓变 0x02，其余发速变 0x01。"""
    n = int(tick) + 1
    if n % 5 == 0:
        return XL_TM_SLOW
    return XL_TM_FAST
