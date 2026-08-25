"""流式组帧缓冲：定头定长 / 定头定尾 / 定头定长定尾。"""

from __future__ import annotations

import pytest

from module_payload.framing import (
    FixedHeaderLenFrameBuffer,
    FixedHeaderLenTrailerFrameBuffer,
    FixedHeaderTrailerFrameBuffer,
)
from module_payload.framing.base import StreamByteBuffer


def test_base_rejects_empty_header() -> None:
    with pytest.raises(ValueError, match='sync_header'):
        StreamByteBuffer(sync_header=b'')


def test_base_write_empty_is_noop() -> None:
    buf = FixedHeaderLenFrameBuffer(b'\xeb\x90', 8)
    buf.write(b'')
    assert buf.pending == 0
    assert buf.read_frame() is None


def test_fixed_header_len_split_across_writes() -> None:
    buf = FixedHeaderLenFrameBuffer(b'\xeb\x90', 6)
    buf.write(b'\x00\xeb')
    assert buf.read_frame() is None
    buf.write(b'\x90\x01\x02\x03\x04')
    frame = buf.read_frame()
    assert frame == b'\xeb\x90\x01\x02\x03\x04'
    assert buf.read_frame() is None
    assert buf.pending == 0


def test_fixed_header_len_skips_noise_and_sticky() -> None:
    hdr = b'\xeb\x90'
    f1 = hdr + b'\xaa\xbb'
    f2 = hdr + b'\xcc\xdd'
    buf = FixedHeaderLenFrameBuffer(hdr, 4)
    buf.write(b'\x11\x22' + f1 + f2)
    frames = buf.read_frames()
    assert frames == [f1, f2]


def test_fixed_header_len_keeps_partial_header() -> None:
    buf = FixedHeaderLenFrameBuffer(b'\xeb\x90', 4)
    buf.write(b'\xff\xeb')
    assert buf.read_frame() is None
    buf.write(b'\x90\x01\x02')
    assert buf.read_frame() == b'\xeb\x90\x01\x02'


def test_fixed_header_len_rejects_undersize() -> None:
    with pytest.raises(ValueError, match='frame_size'):
        FixedHeaderLenFrameBuffer(b'\xeb\x90', 1)
    with pytest.raises(ValueError, match='max_buffer'):
        FixedHeaderLenFrameBuffer(b'\xeb\x90', 8, max_buffer=4)


def test_fixed_header_trailer_variable_body() -> None:
    buf = FixedHeaderTrailerFrameBuffer(b'\xaa\x55', b'\x0d\x0a', max_frame_size=32)
    buf.write(b'\x00\xaa\x55hello\x0d\x0a\xaa\x55x\x0d\x0a')
    assert buf.read_frame() == b'\xaa\x55hello\x0d\x0a'
    assert buf.read_frame() == b'\xaa\x55x\x0d\x0a'


def test_fixed_header_trailer_waits_for_trailer() -> None:
    buf = FixedHeaderTrailerFrameBuffer(b'\xaa\x55', b'\x0d\x0a')
    buf.write(b'\xaa\x55abc')
    assert buf.read_frame() is None
    buf.write(b'\x0d\x0a')
    assert buf.read_frame() == b'\xaa\x55abc\x0d\x0a'


def test_fixed_header_trailer_slides_on_too_long() -> None:
    buf = FixedHeaderTrailerFrameBuffer(b'\xaa\x55', b'\x0d\x0a', max_frame_size=8)
    # 伪头后无尾，超长后滑过 1 字节，后续真帧可取出
    buf.write(b'\xaa\x55XXXXXX\xaa\x55ok\x0d\x0a')
    assert buf.read_frame() == b'\xaa\x55ok\x0d\x0a'


def test_fixed_header_trailer_rejects_empty_trailer() -> None:
    with pytest.raises(ValueError, match='帧尾'):
        FixedHeaderTrailerFrameBuffer(b'\xaa', b'')


def test_header_len_trailer_accepts_alternate_tails() -> None:
    hdr = b'\x1a\xcf'
    body = b'\x00' * 4
    f_ok = hdr + body + b'\x0a\x0d'
    f_alt = hdr + body + b'\x0d\x0a'
    buf = FixedHeaderLenTrailerFrameBuffer(hdr, 8, trailers=(b'\x0a\x0d', b'\x0d\x0a'))
    buf.write(f_ok + f_alt)
    assert buf.read_frames() == [f_ok, f_alt]


def test_header_len_trailer_skips_bad_tail() -> None:
    hdr = b'\xeb\x90'
    bad = hdr + b'\x01\x02\xff\xff'
    good = hdr + b'\x03\x04\x0a\x0d'
    buf = FixedHeaderLenTrailerFrameBuffer(hdr, 6, trailer=b'\x0a\x0d')
    buf.write(bad + good)
    assert buf.read_frame() == good


def test_header_len_trailer_requires_trailer() -> None:
    with pytest.raises(ValueError, match='至少提供一个帧尾'):
        FixedHeaderLenTrailerFrameBuffer(b'\xeb\x90', 8)
    with pytest.raises(ValueError, match='长度必须一致'):
        FixedHeaderLenTrailerFrameBuffer(b'\xeb\x90', 8, trailers=(b'\x0a\x0d', b'\x0a'))


def test_overflow_drops_to_partial_header() -> None:
    buf = FixedHeaderLenFrameBuffer(b'\xeb\x90', 8, max_buffer=16, compact_at=4)
    buf.write(b'\x11' * 20 + b'\xeb')
    assert buf.pending <= 2
    buf.write(b'\x90' + b'\x00' * 6)
    assert buf.read_frame() == b'\xeb\x90' + b'\x00' * 6


def test_clear_and_read_frames_limit() -> None:
    buf = FixedHeaderLenFrameBuffer(b'\xaa', 2)
    buf.write(b'\xaa\x01\xaa\x02\xaa\x03')
    assert buf.read_frames(limit=2) == [b'\xaa\x01', b'\xaa\x02']
    buf.clear()
    assert buf.pending == 0
    assert buf.read_frame() is None
