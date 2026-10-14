"""BIU 定时遥测请求轮询顺序（与 Demo 规则一致，无硬件依赖）。"""

from __future__ import annotations

from typing import Any

# BIU 手动下拉 1~5：FF / FD / FB / F9 / F7（FE、FC 仅手动）
BIU_TM_CODE_1 = 0xFF
BIU_TM_CODES_2_TO_5 = (0xFD, 0xFB, 0xF9, 0xF7, 0xFE, 0xFC)
BIU_TM_INTERVAL_S = 0.5


def next_biu_tm_data_code(tick: int) -> int:
    """0.5s 一次。1-based 奇数次发类型1(FF)，偶数次轮流类型 2~5。"""
    n = int(tick) + 1
    if n % 2 == 1:
        return BIU_TM_CODE_1
    return BIU_TM_CODES_2_TO_5[(n // 2 - 1) % len(BIU_TM_CODES_2_TO_5)]


def timed_tm(tick: int) -> tuple[float, dict[str, Any]]:
    """第 tick 次定时遥测请求：间隔与 data_code。"""
    return BIU_TM_INTERVAL_S, {'data_code': next_biu_tm_data_code(tick)}
