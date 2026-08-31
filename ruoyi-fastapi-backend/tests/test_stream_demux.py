"""StreamDemux 混流拆帧分流单元测试。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from module_payload.assemblers.eng_tm_subpkt import (
    ENG_CHK_OFF,
    ENG_END_OFF,
    ENG_FRAME_SIZE,
    ENG_HEADER,
    ENG_TRAILERS,
    EngTmSubpktAssembler,
)
from module_payload.demux import DemuxRoute, StreamDemux, normalize_routes


def _build_eng_frame(
    *,
    data: bytes,
    src: int = 0x91,
    dst: int = 0x90,
    sub_count: int = 1,
    sub_index: int = 1,
) -> bytes:
    body = bytearray(ENG_FRAME_SIZE)
    body[0:2] = ENG_HEADER
    body[2:4] = len(data).to_bytes(2, 'big')
    body[4:6] = src.to_bytes(2, 'big')
    body[6:8] = dst.to_bytes(2, 'big')
    body[8:10] = sub_count.to_bytes(2, 'big')
    body[10:12] = sub_index.to_bytes(2, 'big')
    body[12 : 12 + len(data)] = data
    checksum = sum(body[0:ENG_CHK_OFF]) & 0xFFFF
    body[ENG_CHK_OFF:ENG_END_OFF] = checksum.to_bytes(2, 'big')
    body[ENG_END_OFF:ENG_FRAME_SIZE] = ENG_TRAILERS[0]
    return bytes(body)


def _d6_frame(type_byte: int = 0xD6, payload_tag: int = 0x11) -> bytes:
    # EB 90 | type | ... 凑满 266
    hdr = bytes([0xEB, 0x90, type_byte & 0xFF])
    body = bytes([payload_tag & 0xFF]) * (266 - 3)
    return hdr + body


def test_normalize_routes_roundtrip() -> None:
    raw = [
        {
            'id': 'eng',
            'framing': 'header_len_trailer',
            'header': '1BCF',
            'frameSize': 844,
            'trailers': ['0A0D', '0D0A'],
            'assemblerId': 'eng_tm_subpkt',
            'parserId': '',
        }
    ]
    out = normalize_routes(raw)
    assert out[0]['header'] == '1BCF'
    assert out[0]['frameSize'] == 844
    assert DemuxRoute.from_dict(out[0]).assembler_id == 'eng_tm_subpkt'


def test_demux_eng_sticky_and_noise() -> None:
    f1 = _build_eng_frame(data=b'A', sub_count=1, sub_index=1)
    demux = StreamDemux(
        [
            {
                'id': 'eng',
                'framing': 'header_len_trailer',
                'header': '1BCF',
                'frameSize': 844,
                'trailers': ['0A0D', '0D0A'],
                'assemblerId': 'eng_tm_subpkt',
            }
        ]
    )
    demux.write(b'\x00\x11' + f1 + b'\x22')
    hits = demux.drain()
    assert len(hits) == 1
    assert hits[0].assembler_id == 'eng_tm_subpkt'
    assert hits[0].frame == f1


def test_demux_same_header_different_type() -> None:
    d6 = _d6_frame(0xD6, 0xAA)
    d8 = _d6_frame(0xD8, 0xBB)
    demux = StreamDemux(
        [
            {
                'id': 'img',
                'framing': 'header_len',
                'header': 'EB90',
                'frameSize': 266,
                'typeAt': 2,
                'type': 'D6',
                'assemblerId': 'camera_image_d6',
            },
            {
                'id': 'tm',
                'framing': 'header_len',
                'header': 'EB90',
                'frameSize': 266,
                'typeAt': 2,
                'type': 'D8',
                'assemblerId': 'passthrough',
                'parserId': 'tm_xl_camera',
            },
        ]
    )
    demux.write(d8 + d6)
    hits = demux.drain()
    assert len(hits) == 2
    assert hits[0].assembler_id == 'passthrough'
    assert hits[0].parser_id == 'tm_xl_camera'
    assert hits[0].frame[2] == 0xD8
    assert hits[1].assembler_id == 'camera_image_d6'
    assert hits[1].frame[2] == 0xD6


def test_demux_mixed_eng_and_eb90() -> None:
    eng = _build_eng_frame(data=b'X', sub_count=1, sub_index=1)
    d6 = _d6_frame(0xD6)
    demux = StreamDemux(
        [
            {
                'id': 'eng',
                'framing': 'header_len_trailer',
                'header': '1BCF',
                'frameSize': 844,
                'trailers': ['0A0D', '0D0A'],
                'assemblerId': 'eng_tm_subpkt',
            },
            {
                'id': 'img',
                'framing': 'header_len',
                'header': 'EB90',
                'frameSize': 266,
                'typeAt': 2,
                'type': 'D6',
                'assemblerId': 'camera_image_d6',
            },
        ]
    )
    demux.write(d6 + b'\xFF' + eng)
    hits = demux.drain()
    assert [h.assembler_id for h in hits] == ['camera_image_d6', 'eng_tm_subpkt']


def test_eng_accept_frame_from_demux() -> None:
    """demux 吐出的完整帧走 accept_frame，与单绑定 feed 结果一致。"""
    f1 = _build_eng_frame(data=b'HELLO', sub_count=1, sub_index=1)
    demux = StreamDemux(
        [
            {
                'id': 'eng',
                'framing': 'header_len_trailer',
                'header': '1BCF',
                'frameSize': 844,
                'trailers': ['0A0D', '0D0A'],
                'assemblerId': 'eng_tm_subpkt',
            }
        ]
    )
    demux.write(f1)
    hit = demux.drain()[0]
    asm = EngTmSubpktAssembler()
    done = asm.accept_frame(hit.frame)
    assert done is not None
    assert done.data == b'HELLO'

    asm2 = EngTmSubpktAssembler()
    out = asm2.feed(f1)
    assert len(out) == 1
    assert out[0].data == b'HELLO'


def test_single_assembler_path_unchanged() -> None:
    """无 routes 时 eng feed 粘包行为仍可用。"""
    p1 = b'A' * 16
    p2 = b'B' * 50
    glued = _build_eng_frame(data=p1, sub_count=2, sub_index=1) + _build_eng_frame(
        data=p2, sub_count=2, sub_index=2
    )
    asm = EngTmSubpktAssembler()
    out = asm.feed(glued)
    assert len(out) == 1
    assert out[0].data == p1 + p2


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('pass', name)
    print('all ok')
