"""YJ216 定时遥测请求：每秒一次，只发 data_code=0xFF。"""

from __future__ import annotations

from typing import Any

TM_DATA_CODE = 0xFF
TM_INTERVAL_S = 1.0


def timed_tm(_tick: int) -> tuple[float, dict[str, Any]]:
    """第 tick 次定时遥测请求：间隔与 data_code。"""
    return TM_INTERVAL_S, {'data_code': TM_DATA_CODE}
