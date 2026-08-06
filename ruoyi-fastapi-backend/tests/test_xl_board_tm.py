"""XL 单板遥测帧解析 / 遥控帧分类单元测试。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from module_payload.cfg.xl_board_telecontrol_assembler import classify_xl_tc_frame
from module_payload.cfg.telecontrol_assembler import calc_checksum
from module_payload.parsers.xl_board_tm import FRAME_HEADER, XlBoardTmIngest, _calc_checksum


def _xl_tc_checksum(buf: bytes) -> int:
    """遥控/遥测 EB90 帧：校验和不含帧头。"""
    return calc_checksum(buf[2:-1]) if len(buf) >= 4 else calc_checksum(buf)


def _build_tm_frame(*, src: int, dst: int, payload: bytes) -> bytes:
    body = bytes([src & 0xFF, dst & 0xFF]) + payload
    body_len = len(body)
    frame = FRAME_HEADER + body_len.to_bytes(2, 'big') + body
    return frame + bytes([_calc_checksum(frame[2:])])


def test_classify_single_frame():
    # EB90 0A 93 0072 0F（校验不含 EB90）
    raw = bytes.fromhex('EB900A9300720F')
    assert classify_xl_tc_frame(raw) == 'single'
    assert _xl_tc_checksum(raw) == raw[-1]


def test_classify_complex_frame():
    raw = bytes.fromhex('EB90000C0F930072000000000000000020')
    assert classify_xl_tc_frame(raw) == 'complex'
    assert _xl_tc_checksum(raw) == raw[-1]


def test_extract_tm_by_src():
    payload = bytes(20)
    fr93 = _build_tm_frame(src=0x93, dst=0x90, payload=payload)
    fr92 = _build_tm_frame(src=0x92, dst=0x96, payload=payload)
    blob = b'\x00\x01' + fr93 + fr92 + b'\xff'
    frames = XlBoardTmIngest.extract_frames(blob)
    assert len(frames) == 2
    assert frames[0][4] == 0x93
    assert frames[1][4] == 0x92
    assert XlBoardTmIngest.table_key_for_src(0x93) == 'RKDJ'
    assert XlBoardTmIngest.table_key_for_src(0x92) == 'ZK'


def test_reject_unknown_src():
    fr = _build_tm_frame(src=0x91, dst=0x90, payload=bytes(8))
    assert XlBoardTmIngest.extract_frames(fr) == []


def test_assemble_corrects_complex_length():
    from module_payload.cfg.xl_board_telecontrol_assembler import assemble_xl_board_order

    # 故意写错长度 0x0005；实际 body=0F92AA01 + AA + float4 → 0x0009
    order = {
        'check': 'yes',
        'component': [
            {'componentType': 'fixed', 'defaultVal': '0xEB90'},
            {'componentType': 'fixed', 'defaultVal': '0x0005'},
            {'componentType': 'fixed', 'defaultVal': '0x0F92AA01'},
            {'componentType': 'select', 'defaultVal': '0xAA', 'options': {'0xAA': '方位'}},
            {'componentType': 'number', 'dataType': 'FLOAT', 'defaultVal': '0'},
        ],
    }
    result = assemble_xl_board_order(order, [None, None, None, '0xAA', 0.0])
    raw = bytes.fromhex(result['hex'].replace(' ', ''))
    assert raw[0:2] == bytes([0xEB, 0x90])
    assert raw[4] == 0x0F
    assert ((raw[2] << 8) | raw[3]) == len(raw) - 5 == 0x0009
    assert result['lengthCorrected'] is True
    assert '0x0005' in result['tip'] and '0x0009' in result['tip']
    assert _calc_checksum(raw[2:-1]) == raw[-1]
