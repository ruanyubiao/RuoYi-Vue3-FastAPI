# -*- coding: utf-8 -*-
"""遥控组帧 wire hex 黄金：固定指令 + 参数 → 整帧 hex 字节级锁定。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager

_GOLDEN = Path(__file__).resolve().parent / 'data' / 'telecontrol_wire_goldens.json'


@pytest.fixture(scope='module')
def wire_cases() -> dict:
    assert _GOLDEN.is_file(), f'缺少 {_GOLDEN}'
    return json.loads(_GOLDEN.read_text(encoding='utf-8'))


@pytest.mark.parametrize(
    'case_id',
    [
        'biu_k1501_defaults',
        'camera_cam_a0_seq0',
        'xl_rkdj_d1503_defaults',
        'xl_rkdj_d1503_formula',
    ],
)
def test_telecontrol_wire_hex_golden(wire_cases: dict, case_id: str) -> None:
    case = wire_cases[case_id]
    cid = case['cfgId']
    TeleControlCfgManager.reload(cid)
    result = TeleControlCfgManager.assemble(
        cid,
        case['orderId'],
        case.get('values') or [],
        **(case.get('kwargs') or {}),
    )
    got = (result.get('hex') or '').upper().replace('  ', ' ').strip()
    expect = (case['hex'] or '').upper().replace('  ', ' ').strip()
    assert got == expect, f'{case_id}: {got!r} != {expect!r}'
    assert int(result.get('length') or 0) == int(case['length'])


def test_telecontrol_wire_golden_file_complete(wire_cases: dict) -> None:
    required = {
        'biu_k1501_defaults',
        'camera_cam_a0_seq0',
        'xl_rkdj_d1503_defaults',
        'xl_rkdj_d1503_formula',
    }
    assert required <= set(wire_cases)
    for case_id, case in wire_cases.items():
        assert case.get('cfgId') and case.get('orderId') and case.get('hex'), case_id
