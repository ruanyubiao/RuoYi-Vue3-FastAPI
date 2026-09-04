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


def test_parse_type_byte_variants() -> None:
    from module_payload.demux.stream_demux import _parse_type_byte

    assert _parse_type_byte(None) is None
    assert _parse_type_byte('') is None
    assert _parse_type_byte(0xD6) == 0xD6
    assert _parse_type_byte('0xD6') == 0xD6
    assert _parse_type_byte('D6') == 0xD6
    assert _parse_type_byte('214') == 0xD6  # decimal


def test_demux_route_validation_and_roundtrip() -> None:
    import pytest

    from module_payload.demux.stream_demux import DemuxRoute, normalize_routes, routes_fingerprint

    with pytest.raises(ValueError, match='未知 framing'):
        DemuxRoute.from_dict({'id': 'x', 'framing': 'weird', 'header': 'EB90', 'assemblerId': 'p'})
    with pytest.raises(ValueError, match='assemblerId'):
        DemuxRoute.from_dict({'id': 'x', 'framing': 'header_len', 'header': 'EB90', 'frameSize': 8})
    with pytest.raises(ValueError, match='frameSize'):
        DemuxRoute.from_dict(
            {'id': 'x', 'framing': 'header_len', 'header': 'EB90', 'assemblerId': 'p'}
        )
    with pytest.raises(ValueError, match='trailers'):
        DemuxRoute.from_dict(
            {
                'id': 'x',
                'framing': 'header_len_trailer',
                'header': '1BCF',
                'frameSize': 844,
                'assemblerId': 'eng',
            }
        )
    with pytest.raises(ValueError, match='长度须一致'):
        DemuxRoute.from_dict(
            {
                'id': 'x',
                'framing': 'header_len_trailer',
                'header': '1BCF',
                'frameSize': 8,
                'trailers': ['0A0D', '0A'],
                'assemblerId': 'eng',
            }
        )
    with pytest.raises(ValueError, match='frameSize 过小'):
        DemuxRoute.from_dict(
            {
                'id': 'x',
                'framing': 'header_len_trailer',
                'header': 'EB90',
                'frameSize': 3,
                'trailers': ['0A0D'],
                'assemblerId': 'eng',
            }
        )
    with pytest.raises(ValueError, match='trailer'):
        DemuxRoute.from_dict(
            {'id': 'x', 'framing': 'header_trailer', 'header': 'AA55', 'assemblerId': 'p'}
        )
    # 多尾变长：只保留第一个
    r = DemuxRoute.from_dict(
        {
            'id': 'ht',
            'framing': 'fixed_header_trailer',
            'header': 'AA55',
            'trailers': ['0D0A', '0A0D'],
            'assemblerId': 'passthrough',
            'typeAt': 2,
            'type': '01',
            'minFrameSize': 6,
        }
    )
    assert len(r.trailers) == 1
    d = r.to_dict()
    assert d['typeAt'] == 2 and d['type'] == '01' and d['minFrameSize'] == 6
    assert r.type_matches(b'\xaa\x55\x01\x0d\x0a') is True
    assert r.type_matches(b'\xaa\x55') is False  # type_at 越界
    assert normalize_routes(None) == []
    with pytest.raises(ValueError, match='数组'):
        normalize_routes({})
    with pytest.raises(ValueError, match='对象'):
        normalize_routes(['x'])
    assert '"id"' in routes_fingerprint([d])


def test_demux_header_trailer_and_type_mismatch_skip() -> None:
    demux = StreamDemux(
        [
            {
                'id': 'ht',
                'framing': 'header_trailer',
                'header': 'AA55',
                'trailer': '0D0A',
                'assemblerId': 'passthrough',
                'maxFrameSize': 32,
            }
        ]
    )
    demux.write(b'\x00\xaa\x55hello\x0d\x0a')
    hits = demux.drain()
    assert len(hits) == 1
    assert hits[0].frame == b'\xaa\x55hello\x0d\x0a'
    assert demux.routes[0].id == 'ht'

    # 定长 type 不匹配：消费掉避免死循环
    demux2 = StreamDemux(
        [
            {
                'id': 'img',
                'framing': 'header_len',
                'header': 'EB90',
                'frameSize': 8,
                'typeAt': 2,
                'type': 'D6',
                'assemblerId': 'camera_image_d6',
            }
        ]
    )
    bad = bytes([0xEB, 0x90, 0xD8, 1, 2, 3, 4, 5])
    good = bytes([0xEB, 0x90, 0xD6, 9, 8, 7, 6, 5])
    demux2.write(bad + good)
    hits2 = demux2.drain()
    assert len(hits2) == 1
    assert hits2[0].frame[2] == 0xD6


def test_demux_overflow_clear_partial_and_empty_write() -> None:
    import pytest

    with pytest.raises(ValueError, match='不能为空'):
        StreamDemux([])
    demux = StreamDemux(
        [
            {
                'id': 'a',
                'framing': 'header_len',
                'header': 'EB90',
                'frameSize': 8,
                'assemblerId': 'passthrough',
            }
        ],
        max_buffer=12,
        compact_at=4,
    )
    demux.write(b'')
    demux.write(b'\xff' * 20)
    assert demux.pending <= 1
    demux.clear()
    assert demux.pending == 0
    # 无头噪声 → trim
    demux.write(b'\x11\x22\x33')
    assert demux.drain() == []
    # 半截帧头前缀保留
    demux.write(b'\xeb')
    assert demux.pending == 1


def test_demux_bad_trailer_skip_and_eng_route_object() -> None:
    route = DemuxRoute.from_dict(
        {
            'id': 'eng',
            'framing': 'header_len_trailer',
            'header': '1BCF',
            'frameSize': 844,
            'trailers': ['0A0D'],
            'assemblerId': 'eng_tm_subpkt',
        }
    )
    demux = StreamDemux([route])
    bad = bytearray(_build_eng_frame(data=b'Z'))
    bad[-2:] = b'\xff\xff'
    good = _build_eng_frame(data=b'G')
    demux.write(bytes(bad) + good)
    hits = demux.drain()
    assert len(hits) == 1
    assert hits[0].frame == good


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('pass', name)
    print('all ok')
