"""遥测解析字段公共工具：calc_val 优先的数值提取。"""

from __future__ import annotations

from typing import Any


def line_to_field_dict(ln: Any, *, unit: str | None = None) -> dict[str, Any]:
    """TeleMetryLine → 落库/展示用字段 dict（含 calc_val）。"""
    num = getattr(ln, 'val', None)
    raw = num.value() if num is not None and hasattr(num, 'value') else None
    calc = getattr(ln, 'calc_val', None)
    u = unit if unit is not None else (getattr(ln, 'unit', '') or '')
    return {
        'id': getattr(ln, 'id', '') or '',
        'name': getattr(ln, 'name', '') or '',
        'value': raw,
        'calc_val': calc if calc is not None else raw,
        'show': getattr(ln, 'show', '') or '',
        'hex': getattr(ln, 'hex', '') or '',
        'unit': u,
    }


def curve_numeric(row: dict[str, Any]) -> float | None:
    """
    曲线/归档数值：优先 calc_val（公式后、值映射前），其次 value，再次 show。
    无法数值化则返回 None（跳过该点）。
    """
    for key in ('calc_val', 'value', 'show'):
        if key not in row:
            continue
        v = row.get(key)
        if v is None or v == '':
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None
