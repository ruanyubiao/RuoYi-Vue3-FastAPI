"""XL 定时遥测请求轮询顺序（与 Demo 规则一致，无硬件依赖）。"""

from __future__ import annotations

from typing import Any

XL_TM_FAST = 0x01
XL_TM_SLOW = 0x02
XL_TM_INTERVAL_S = 1.0


def next_xl_tm_sec_header(tick: int) -> int:
    """1s 一次。第 5、10、15… 秒发缓变 0x02，其余发速变 0x01。"""
    n = int(tick) + 1
    if n % 5 == 0:
        return XL_TM_SLOW
    return XL_TM_FAST


def timed_tm(tick: int) -> tuple[float, dict[str, Any]]:
    """第 tick 次定时遥测请求：间隔与次头。"""
    return XL_TM_INTERVAL_S, {'sec_header': next_xl_tm_sec_header(tick)}
