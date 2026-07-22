"""组装器单元测试：透传与工程遥测子包拼装。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from module_payload.assemblers import (
    EngTmSubpktAssembler,
    PassthroughAssembler,
    create_assembler,
    list_assemblers,
    normalize_assembler_id,
)
from module_payload.assemblers.eng_tm_subpkt import ENG_FRAME_SIZE
from module_payload.constants import ASSEMBLER_ENG_TM_SUBPKT, ASSEMBLER_PASSTHROUGH

_DATA_CAP = 1024


def _build_eng_frame(
    *,
    data: bytes,
    src: int = 0x91,
    dst: int = 0x90,
    sub_count: int = 1,
    sub_index: int = 1,
) -> bytes:
    assert len(data) <= _DATA_CAP
    body = bytearray(ENG_FRAME_SIZE)
    body[0:2] = (0x1ACF).to_bytes(2, 'big')
    body[2:4] = len(data).to_bytes(2, 'big')
    body[4:6] = src.to_bytes(2, 'big')
    body[6:8] = dst.to_bytes(2, 'big')
    body[8:10] = sub_count.to_bytes(2, 'big')
    body[10:12] = sub_index.to_bytes(2, 'big')
    body[12 : 12 + len(data)] = data
    checksum = sum(body[0:1036]) & 0xFFFF
    body[1036:1038] = checksum.to_bytes(2, 'big')
    body[1038:1040] = (0x0A0D).to_bytes(2, 'big')
    return bytes(body)


def test_normalize_and_list() -> None:
    assert normalize_assembler_id(None) == ASSEMBLER_PASSTHROUGH
    assert normalize_assembler_id('') == ASSEMBLER_PASSTHROUGH
    ids = {a['id'] for a in list_assemblers()}
    assert ASSEMBLER_PASSTHROUGH in ids
    assert ASSEMBLER_ENG_TM_SUBPKT in ids


def test_passthrough_feed() -> None:
    asm = PassthroughAssembler()
    out = asm.feed(b'abc')
    assert len(out) == 1
    assert out[0].data == b'abc'


def test_eng_single_packet() -> None:
    payload = b'HELLO-ENG'
    frame = _build_eng_frame(data=payload, sub_count=1, sub_index=1)
    asm = EngTmSubpktAssembler()
    out = asm.feed(frame)
    assert len(out) == 1
    assert out[0].data == payload
    assert out[0].meta['srcAddr'] == 0x91
    assert out[0].meta['destAddr'] == 0x90


def test_eng_multi_packet_assemble() -> None:
    p1 = b'A' * 100
    p2 = b'B' * 50
    f1 = _build_eng_frame(data=p1, sub_count=2, sub_index=1)
    f2 = _build_eng_frame(data=p2, sub_count=2, sub_index=2)
    asm = create_assembler(ASSEMBLER_ENG_TM_SUBPKT)
    assert asm.feed(f1) == []
    out = asm.feed(f2)
    assert len(out) == 1
    assert out[0].data == p1 + p2
    assert out[0].meta['subCount'] == 2


def test_eng_out_of_order_rejected() -> None:
    """乱序不再拼装：先到 2 无缓存则丢；再 1→2 才成功。"""
    p1 = b'1111'
    p2 = b'2222'
    f1 = _build_eng_frame(data=p1, sub_count=2, sub_index=1)
    f2 = _build_eng_frame(data=p2, sub_count=2, sub_index=2)
    asm = EngTmSubpktAssembler()
    assert asm.feed(f2) == []
    errs = asm.take_errors()
    assert any('非首帧' in e for e in errs)
    assert asm.feed(f1) == []
    out = asm.feed(f2)
    assert len(out) == 1
    assert out[0].data == p1 + p2


def test_eng_gap_discards_cache_and_current() -> None:
    """1 之后直接 3：丢缓存与当前帧。"""
    f1 = _build_eng_frame(data=b'A', sub_count=3, sub_index=1)
    f3 = _build_eng_frame(data=b'C', sub_count=3, sub_index=3)
    asm = EngTmSubpktAssembler()
    assert asm.feed(f1) == []
    assert asm.feed(f3) == []
    errs = asm.take_errors()
    assert any('不连续' in e for e in errs)
    # 缓存已空，再来完整 1+2+3 应能重新组装
    f2 = _build_eng_frame(data=b'B', sub_count=3, sub_index=2)
    assert asm.feed(f1) == []
    assert asm.feed(f2) == []
    out = asm.feed(_build_eng_frame(data=b'C', sub_count=3, sub_index=3))
    assert len(out) == 1
    assert out[0].data == b'ABC'


def test_eng_single_discards_incomplete_cache() -> None:
    """多包未完成时来单包：丢缓存，单包直接产出。"""
    f1 = _build_eng_frame(data=b'PART', sub_count=2, sub_index=1)
    single = _build_eng_frame(data=b'ONLY', sub_count=1, sub_index=1)
    asm = EngTmSubpktAssembler()
    assert asm.feed(f1) == []
    out = asm.feed(single)
    assert len(out) == 1
    assert out[0].data == b'ONLY'
    assert any('单包' in e for e in asm.take_errors())


def test_eng_new_first_discards_incomplete() -> None:
    """未完成时又收到首帧：丢旧缓存，从新首帧开始。"""
    old1 = _build_eng_frame(data=b'OLD', sub_count=2, sub_index=1)
    new1 = _build_eng_frame(data=b'N1', sub_count=2, sub_index=1)
    new2 = _build_eng_frame(data=b'N2', sub_count=2, sub_index=2)
    asm = EngTmSubpktAssembler()
    assert asm.feed(old1) == []
    assert asm.feed(new1) == []
    out = asm.feed(new2)
    assert len(out) == 1
    assert out[0].data == b'N1N2'


def test_eng_bad_checksum_ignored() -> None:
    frame = bytearray(_build_eng_frame(data=b'X', sub_count=1, sub_index=1))
    frame[1036] ^= 0xFF
    asm = EngTmSubpktAssembler()
    assert asm.feed(bytes(frame)) == []
    assert any('校验失败' in e for e in asm.take_errors())


def test_eng_sticky_two_subframes_one_datagram() -> None:
    """一包 UDP 粘连 1/2+2/2：应拆成两帧并一次组装完成。"""
    p1 = b'A' * 16
    p2 = b'B' * 50
    glued = _build_eng_frame(data=p1, sub_count=2, sub_index=1) + _build_eng_frame(
        data=p2, sub_count=2, sub_index=2
    )
    assert len(glued) == ENG_FRAME_SIZE * 2
    asm = EngTmSubpktAssembler()
    out = asm.feed(glued)
    assert len(out) == 1
    assert out[0].data == p1 + p2
    assert len(asm._buf) == 0


def test_eng_sticky_two_complete_messages() -> None:
    """一包粘连两组完整多包：应产出两条组装结果。"""
    a = _build_eng_frame(data=b'A1', sub_count=2, sub_index=1) + _build_eng_frame(
        data=b'A2', sub_count=2, sub_index=2
    )
    b = _build_eng_frame(data=b'B1', sub_count=2, sub_index=1) + _build_eng_frame(
        data=b'B2', sub_count=2, sub_index=2
    )
    asm = EngTmSubpktAssembler()
    out = asm.feed(a + b)
    assert len(out) == 2
    assert out[0].data == b'A1A2'
    assert out[1].data == b'B1B2'


def test_eng_sticky_after_aligned_bad_frame() -> None:
    """对齐的坏帧整帧丢弃后，仍能拆出后续粘包好帧。"""
    bad = bytearray(_build_eng_frame(data=b'BAD', sub_count=1, sub_index=1))
    bad[20] ^= 0xFF
    good = _build_eng_frame(data=b'OK', sub_count=1, sub_index=1)
    asm = EngTmSubpktAssembler()
    out = asm.feed(bytes(bad) + good)
    assert len(out) == 1
    assert out[0].data == b'OK'


def test_assembled_redis_keys() -> None:
    from module_payload import redis_keys as rk

    assert rk.assembled_latest_key('net:udp:127.0.0.1:9000') == (
        'payload:net:udp:127.0.0.1:9000:assembled:latest'
    )
    assert rk.assembled_log_key('serial:COM1') == 'payload:serial:COM1:assembled'
