# -*- coding: utf-8 -*-
"""工程遥测多包子包回归：合成拆包 → 组装 → 内层单板解析对齐。

数据直接写在本文件（无正式抓包），内层载荷取自黄金单板 DJ 帧。
"""
from __future__ import annotations

import json
from pathlib import Path

from module_payload.assemblers.eng_tm_subpkt import (
    ENG_CHK_OFF,
    ENG_DATA_CAPACITY,
    ENG_END_OFF,
    ENG_FRAME_SIZE,
    ENG_START,
    EngTmSubpktAssembler,
)
from module_payload.cfg.hex_text import hex_to_bytes
from module_payload.parsers.xl_board_tm import XlBoardTmIngest

_CASES = Path(__file__).resolve().parents[1] / 'assets' / 'data' / 'tm_golden_cases.json'


def _build_table4_frame(
    *,
    data: bytes,
    src: int = 0x33,
    dst: int = 0x22,
    sub_count: int = 1,
    sub_index: int = 1,
) -> bytes:
    assert len(data) <= ENG_DATA_CAPACITY
    body = bytearray(ENG_FRAME_SIZE)
    body[0:2] = ENG_START.to_bytes(2, 'big')
    body[2:4] = len(data).to_bytes(2, 'big')
    body[4:6] = src.to_bytes(2, 'big')
    body[6:8] = dst.to_bytes(2, 'big')
    body[8:10] = sub_count.to_bytes(2, 'big')
    body[10:12] = sub_index.to_bytes(2, 'big')
    body[12 : 12 + len(data)] = data
    checksum = sum(body[0:ENG_CHK_OFF]) & 0xFFFF
    body[ENG_CHK_OFF:ENG_END_OFF] = checksum.to_bytes(2, 'big')
    body[ENG_END_OFF:ENG_FRAME_SIZE] = (0x0A0D).to_bytes(2, 'big')
    return bytes(body)


def _dj_inner() -> bytes:
    """黄金地检板 EB90 帧（完整内层）。"""
    cases = json.loads(_CASES.read_text(encoding='utf-8'))
    return hex_to_bytes(cases['passthrough_board_dj']['hex'])


def _field_map(parsed) -> dict:
    return {f.get('id'): f.get('value') for f in (parsed.fields or [])}


def test_eng_multi_subpkt_joins_to_same_board_parse() -> None:
    """把 DJ 单板帧拆成 3 个子包；拼装后解析结果与整包一致。"""
    inner = _dj_inner()
    assert inner[:2] == b'\xeb\x90'
    # 拆成前/中/后三段（长度不等，覆盖 dataLen 按包变化）
    a, b, c = inner[:40], inner[40:80], inner[80:]
    assert a + b + c == inner

    asm = EngTmSubpktAssembler()
    assert asm.feed(_build_table4_frame(data=a, sub_count=3, sub_index=1)) == []
    assert asm.feed(_build_table4_frame(data=b, sub_count=3, sub_index=2)) == []
    out = asm.feed(_build_table4_frame(data=c, sub_count=3, sub_index=3))
    assert len(out) == 1
    assert out[0].data == inner
    assert out[0].meta['subCount'] == 3
    assert out[0].meta['srcAddr'] == 0x33
    assert out[0].meta['destAddr'] == 0x22
    assert out[0].meta.get('assemblerId') == 'eng_tm_subpkt'

    joined = XlBoardTmIngest.parse_bytes(out[0].data)
    whole = XlBoardTmIngest.parse_bytes(inner)
    assert joined.table_key == whole.table_key == 'DJ'
    assert joined.src == whole.src == 0x77
    assert _field_map(joined) == _field_map(whole)


def test_eng_multi_subpkt_midway_no_emit() -> None:
    """仅收到 1/3、2/3 时不得产出；3/3 才产出。"""
    inner = _dj_inner()
    chunks = [inner[:50], inner[50:90], inner[90:]]
    asm = EngTmSubpktAssembler()
    for i, chunk in enumerate(chunks[:-1], start=1):
        assert asm.feed(_build_table4_frame(data=chunk, sub_count=3, sub_index=i)) == []
    out = asm.feed(_build_table4_frame(data=chunks[-1], sub_count=3, sub_index=3))
    assert len(out) == 1 and out[0].data == inner
