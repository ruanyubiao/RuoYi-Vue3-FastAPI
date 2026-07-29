"""XL 单板遥测帧解析 / 遥控帧分类单元测试。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from module_payload.cfg.xl_board_telecontrol_assembler import classify_xl_tc_frame
from module_payload.parsers.xl_board_tm import FRAME_HEADER, XlBoardTmIngest, _calc_checksum


def _build_tm_frame(*, src: int, dst: int, payload: bytes) -> bytes:
    body = bytes([src & 0xFF, dst & 0xFF]) + payload
    body_len = len(body)
    frame = FRAME_HEADER + body_len.to_bytes(2, 'big') + body
    return frame + bytes([_calc_checksum(frame)])


def test_classify_single_frame():
    # EB90 0A 93 0072 8A
    raw = bytes.fromhex('EB900A9300728A')
    assert classify_xl_tc_frame(raw) == 'single'


def test_classify_complex_frame():
    raw = bytes.fromhex('EB90000C0F93007200000000000000009B')
    assert classify_xl_tc_frame(raw) == 'complex'
    assert _calc_checksum(raw[:-1]) == raw[-1]


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
