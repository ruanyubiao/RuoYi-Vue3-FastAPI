# -*- coding: utf-8 -*-
"""归档 points_json（calc_val）与解析字段对照。"""
from __future__ import annotations

from typing import Any

import pytest


def field_calc_map(fields: list[dict[str, Any]] | None) -> dict[str, Any]:
    """字段列表 → {id: calc_val 优先}。"""
    out: dict[str, Any] = {}
    for f in fields or []:
        fid = f.get('id')
        if not fid:
            continue
        out[str(fid)] = f.get('calc_val', f.get('value'))
    return out


def assert_points_match_calc(
    points: dict[str, Any],
    fields: list[dict[str, Any]] | None,
    *,
    rel: float = 1e-6,
    abs_: float = 1e-9,
) -> None:
    """points_json 与解析 calc_val 全键对拍（浮点 approx）。"""
    assert points, 'points_json 为空'
    got = field_calc_map(fields)
    missing = [k for k in points if k not in got]
    assert not missing, f'解析缺字段: {missing[:8]}'
    for key, expected in points.items():
        actual = got[key]
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            assert actual == pytest.approx(expected, rel=rel, abs=abs_), key
        else:
            assert actual == expected, key
