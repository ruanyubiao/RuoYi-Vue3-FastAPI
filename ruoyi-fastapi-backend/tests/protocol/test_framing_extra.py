"""新增 framing 模式单测（长度字段/定长/分隔符/转义/COBS/SLIP/透传）。"""

from __future__ import annotations

import pytest

from module_payload.framing import (
    CobsFrameBuffer,
    DelimiterFrameBuffer,
    EscapeFrameBuffer,
    FixedHeaderLenFieldFrameBuffer,
    FixedLenFrameBuffer,
    IdentityFrameBuffer,
    SlipFrameBuffer,
    cobs_encode,
    slip_encode,
)


def test_len_field_split_across_writes_and_multi_size() -> None:
    """半截粘包 + 同流多帧长（模拟 RS422 3649/1551/1040 结构）。"""
    hdr = b'\xeb\x90\x3a'

    def make(payload: bytes, seq: int = 1) -> bytes:
        length = len(payload).to_bytes(2, 'big')
        body = hdr + length + bytes((seq,)) + payload
        # 校验占位 2B（拆帧不验）
        return body + b'\x00\x00'

    f1 = make(b'\x11' * 10, 1)
    f2 = make(b'\x22' * 3, 2)
    f3 = make(b'\x33' * 20, 3)
    assert len(f1) == 8 + 10
    buf = FixedHeaderLenFieldFrameBuffer(
        hdr,
        length_offset=3,
        length_width=2,
        endian='big',
        length_base='payload',
        length_adjust=3,
        min_frame_size=8,
        max_frame_size=100,
    )
    # 半截
    buf.write(f1[:5])
    assert buf.read_frame() is None
    buf.write(f1[5:] + f2 + f3[:4])
    assert buf.read_frame() == f1
    assert buf.read_frame() == f2
    assert buf.read_frame() is None
    buf.write(f3[4:])
    assert buf.read_frame() == f3


def test_len_field_skips_noise_and_bad_length() -> None:
    hdr = b'\xaa\x55'
    # payload len=2, adjust=0 → total = 2+2+2+0 = 6
    good = hdr + b'\x00\x02\x11\x22'
    buf = FixedHeaderLenFieldFrameBuffer(
        hdr,
        length_offset=2,
        length_width=2,
        length_base='payload',
        length_adjust=0,
        min_frame_size=6,
        max_frame_size=32,
    )
    # 噪声 + 离谱长度声明 + 真帧
    bad_len = hdr + b'\xff\xff'
    buf.write(b'\x00\x11' + bad_len + good)
    assert buf.read_frame() == good


def test_len_field_total_base() -> None:
    hdr = b'\xeb\x90'
    # total=6 声明
    frame = hdr + b'\x00\x06\x01\x02'
    buf = FixedHeaderLenFieldFrameBuffer(
        hdr,
        length_offset=2,
        length_width=2,
        length_base='total',
        min_frame_size=6,
        max_frame_size=32,
    )
    buf.write(frame)
    assert buf.read_frame() == frame


def test_len_field_validation() -> None:
    with pytest.raises(ValueError, match='header'):
        FixedHeaderLenFieldFrameBuffer(b'', length_offset=0)
    with pytest.raises(ValueError, match='endian'):
        FixedHeaderLenFieldFrameBuffer(b'\xaa', length_offset=1, endian='mid')
    with pytest.raises(ValueError, match='length_offset'):
        FixedHeaderLenFieldFrameBuffer(b'\xaa\x55', length_offset=1)
    with pytest.raises(ValueError, match='length_base'):
        FixedHeaderLenFieldFrameBuffer(b'\xaa', length_offset=1, length_base='nope')


def test_fixed_len_chunks() -> None:
    buf = FixedLenFrameBuffer(4)
    buf.write(b'\x01\x02\x03')
    assert buf.read_frame() is None
    buf.write(b'\x04\x05\x06\x07\x08')
    assert buf.read_frames() == [b'\x01\x02\x03\x04', b'\x05\x06\x07\x08']


def test_delimiter_sticky() -> None:
    buf = DelimiterFrameBuffer(b'\n', min_frame_size=2, max_frame_size=16)
    buf.write(b'ab')
    assert buf.read_frame() is None
    buf.write(b'\ncd\n')
    assert buf.read_frame() == b'ab\n'
    assert buf.read_frame() == b'cd\n'


def test_escape_hdlc_style() -> None:
    # start 7E, end 7E, escape 7D；载荷 01 7E → 7D 5E
    buf = EscapeFrameBuffer(0x7E, 0x7E, 0x7D, max_frame_size=32)
    wire = bytes([0x7E, 0x01, 0x7D, 0x5E, 0x02, 0x7E])
    buf.write(wire[:3])
    assert buf.read_frame() is None
    buf.write(wire[3:])
    assert buf.read_frame() == b'\x01\x7e\x02'


def test_cobs_roundtrip_sticky() -> None:
    payload = b'hello\x00world'
    encoded = cobs_encode(payload) + b'\x00'
    buf = CobsFrameBuffer(max_frame_size=64)
    buf.write(encoded[:4])
    assert buf.read_frame() is None
    buf.write(encoded[4:])
    assert buf.read_frame() == payload


def test_slip_roundtrip_sticky() -> None:
    payload = bytes([0x01, 0xC0, 0xDB, 0x02])
    wire = slip_encode(payload)
    buf = SlipFrameBuffer(max_frame_size=64)
    buf.write(wire[:3])
    assert buf.read_frame() is None
    buf.write(wire[3:])
    assert buf.read_frame() == payload


def test_identity_passthrough() -> None:
    buf = IdentityFrameBuffer()
    assert buf.read_frame() is None
    buf.write(b'abc')
    assert buf.read_frame() == b'abc'
    assert buf.read_frame() is None
