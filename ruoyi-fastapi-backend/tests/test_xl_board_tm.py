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
    # EB90 | 0F | len=000B | 93 0072 + 8*00 | chk（类型在长度前）
    raw = bytes.fromhex('EB900F000B93007200000000000000001F')
    assert classify_xl_tc_frame(raw) == 'complex'
    assert _xl_tc_checksum(raw) == raw[-1]


def test_extract_tm_by_src():
    """源 0x33→RKDJ、0x44→ZK、0x77→DJ；目的任意（单板调试可中途拦截）。"""
    payload = bytes(20)
    fr33 = _build_tm_frame(src=0x33, dst=0x11, payload=payload)
    fr44 = _build_tm_frame(src=0x44, dst=0x22, payload=payload)  # 目的非星务也可
    fr77 = _build_tm_frame(src=0x77, dst=0x11, payload=payload)
    blob = b'\x00\x01' + fr33 + fr44 + fr77 + b'\xff'
    frames = XlBoardTmIngest.extract_frames(blob)
    assert len(frames) == 3
    assert frames[0][4] == 0x33
    assert frames[1][4] == 0x44
    assert frames[2][4] == 0x77
    assert XlBoardTmIngest.io_preview_frames(blob) == frames
    assert XlBoardTmIngest.table_key_for_src(0x33) == 'RKDJ'
    assert XlBoardTmIngest.table_key_for_src(0x44) == 'ZK'
    assert XlBoardTmIngest.table_key_for_src(0x77) == 'DJ'


def test_reject_unknown_src():
    fr = _build_tm_frame(src=0x91, dst=0x11, payload=bytes(8))
    assert XlBoardTmIngest.extract_frames(fr) == []


def test_any_dst_accepted():
    """不对目的地址校验：截获给通信板等中间节点的帧也应能按源分表。"""
    fr = _build_tm_frame(src=0x33, dst=0x22, payload=bytes(8))
    assert len(XlBoardTmIngest.extract_frames(fr)) == 1
    parsed = XlBoardTmIngest.parse_frame(fr)
    assert parsed.table_key == 'RKDJ'
    assert parsed.dst == 0x22


def test_bad_checksum_reports_mismatch_not_missing_frame():
    """改末字节校验和：流式 extract 会跳过；数据模拟应报校验和错误而不是「未找到帧」。"""
    import pytest

    fr = _build_tm_frame(src=0x33, dst=0x11, payload=bytes(20))
    bad = bytearray(fr)
    bad[-1] = (bad[-1] ^ 0x01) & 0xFF
    blob = bytes(bad)
    assert XlBoardTmIngest.extract_frames(blob) == []
    with pytest.raises(ValueError, match='校验和错误'):
        XlBoardTmIngest.parse_bytes(blob)


def test_assemble_corrects_complex_length():
    from module_payload.cfg.xl_board_telecontrol_assembler import assemble_xl_board_order

    # 故意写错长度 0x0005；实际 body=92AA01 + AA + float4 → 0x0008（不含类型）
    order = {
        'check': 'yes',
        'component': [
            {'componentType': 'fixed', 'defaultVal': '0xEB90'},
            {'componentType': 'fixed', 'defaultVal': '0x0F'},
            {'componentType': 'fixed', 'defaultVal': '0x0005'},
            {'componentType': 'fixed', 'defaultVal': '0x92AA01'},
            {'componentType': 'select', 'defaultVal': '0xAA', 'options': {'0xAA': '方位'}},
            {'componentType': 'number', 'dataType': 'FLOAT', 'defaultVal': '0'},
        ],
    }
    result = assemble_xl_board_order(order, [None, None, None, None, '0xAA', 0.0])
    raw = bytes.fromhex(result['hex'].replace(' ', ''))
    assert raw[0:2] == bytes([0xEB, 0x90])
    assert raw[2] == 0x0F
    assert ((raw[3] << 8) | raw[4]) == len(raw) - 6 == 0x0008
    assert result['lengthCorrected'] is True
    assert '0x0005' in result['tip'] and '0x0008' in result['tip']
    assert _calc_checksum(raw[2:-1]) == raw[-1]


def test_assemble_applies_formula_then_data_type():
    from module_payload.cfg.xl_board_telecontrol_assembler import assemble_xl_board_order
    import struct

    order = {
        'check': 'yes',
        'component': [
            {'componentType': 'fixed', 'defaultVal': '0xEB90'},
            {'componentType': 'fixed', 'defaultVal': '0x0F'},
            {'componentType': 'fixed', 'defaultVal': '0x0008'},
            {'componentType': 'fixed', 'defaultVal': '0x92AA03'},
            {'componentType': 'select', 'defaultVal': '0xAA', 'options': {'0xAA': '方位'}},
            {
                'componentType': 'number',
                'dataType': 'INT32',
                'dataTypeUI': 'FLOAT',
                'formula': 'D*100000',
                'defaultVal': '',
            },
        ],
    }
    # UI 输入 1.5 → formula 150000.0 → INT32 big-endian
    result = assemble_xl_board_order(order, [None, None, None, None, '0xAA', 1.5])
    raw = bytes.fromhex(result['hex'].replace(' ', ''))
    assert raw[0:5] == bytes([0xEB, 0x90, 0x0F, 0x00, 0x08])
    assert raw[5:8] == bytes([0x92, 0xAA, 0x03])
    assert raw[8] == 0xAA
    assert raw[9:13] == struct.pack('>i', 150000)
    assert _calc_checksum(raw[2:-1]) == raw[-1]


def test_ingest_bytes_sync_serial_does_not_archive():
    from unittest.mock import MagicMock

    from module_payload.parsers.tm_ingest_batch import flush_pending

    fr = _build_tm_frame(src=0x33, dst=0x11, payload=bytes(20))
    redis = MagicMock()
    pipe = MagicMock()
    redis.pipeline.return_value = pipe
    pipe.zadd.return_value = pipe
    pipe.zremrangebyrank.return_value = pipe
    pipe.set.return_value = pipe
    pipe.execute.return_value = []
    XlBoardTmIngest.ingest_bytes_sync(redis, fr, src_param='serial:COM5')
    flush_pending(redis)
    redis.lpush.assert_not_called()
