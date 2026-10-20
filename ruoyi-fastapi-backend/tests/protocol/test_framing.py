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


def test_base_rejects_bad_max_buffer() -> None:
    with pytest.raises(ValueError, match='max_buffer'):
        StreamByteBuffer(sync_header=b'\xaa', max_buffer=0)


def test_base_read_frame_not_implemented() -> None:
    buf = StreamByteBuffer(sync_header=b'\xaa')
    with pytest.raises(NotImplementedError):
        buf.read_frame()


def test_base_compact_clears_when_fully_consumed() -> None:
    buf = FixedHeaderLenFrameBuffer(b'\xaa', 2, compact_at=2)
    buf.write(b'\xaa\x01\xaa\x02')
    assert buf.read_frame() == b'\xaa\x01'
    # 再读触发 compact：_start 可能已越过整段缓冲
    assert buf.read_frame() == b'\xaa\x02'
    assert buf.pending == 0


def test_base_trim_single_byte_header_clears() -> None:
    """单字节帧头 overflow 时 keep=0，走 clear 分支。"""
    buf = FixedHeaderLenFrameBuffer(b'\xaa', 2, max_buffer=4, compact_at=2)
    buf.write(b'\x11\x22\x33\x44\x55')
    assert buf.pending == 0


def test_base_overflow_keeps_partial_header_prefix() -> None:
    buf = FixedHeaderLenFrameBuffer(b'\xeb\x90', 4, max_buffer=6, compact_at=2)
    buf.write(b'\xff' * 8 + b'\xeb')
    assert buf.pending <= 1
    buf.write(b'\x90\x01\x02')
    assert buf.read_frame() == b'\xeb\x90\x01\x02'


def test_fixed_header_len_properties_and_no_header() -> None:
    buf = FixedHeaderLenFrameBuffer(b'\xeb\x90', 6)
    assert buf.header == b'\xeb\x90'
    assert buf.frame_size == 6
    buf.write(b'\x00\x11\x22\x33\x44')
    assert buf.read_frame() is None
    assert buf.pending == 0  # 无头：trim 清空


def test_fixed_header_trailer_properties_and_validation() -> None:
    with pytest.raises(ValueError, match='min_frame_size'):
        FixedHeaderTrailerFrameBuffer(b'\xaa\x55', b'\x0d\x0a', min_frame_size=2)
    with pytest.raises(ValueError, match='max_frame_size'):
        FixedHeaderTrailerFrameBuffer(b'\xaa\x55', b'\x0d\x0a', max_frame_size=3)
    with pytest.raises(ValueError, match='max_buffer'):
        FixedHeaderTrailerFrameBuffer(b'\xaa\x55', b'\x0d\x0a', max_frame_size=16, max_buffer=8)
    buf = FixedHeaderTrailerFrameBuffer(b'\xaa\x55', b'\x0d\x0a', min_frame_size=6, compact_at=4)
    assert buf.header == b'\xaa\x55'
    assert buf.trailer == b'\x0d\x0a'
    # 半截帧头
    buf.write(b'\xaa')
    assert buf.read_frame() is None
    # 无头 → trim
    buf.clear()
    buf.write(b'\x00\x11\x22')
    assert buf.read_frame() is None
    # 尾过近：min_frame_size=6 时 AA55+0D0A=4 < 6，滑过再找
    buf.clear()
    buf.write(b'\xaa\x55\x0d\x0a\xaa\x55ok\x0d\x0a')
    assert buf.read_frame() == b'\xaa\x55ok\x0d\x0a'
    # 仅有头、无尾且未超 max → 等待
    buf2 = FixedHeaderTrailerFrameBuffer(b'\xaa\x55', b'\x0d\x0a', max_frame_size=32)
    buf2.write(b'\xaa\x55abc')
    assert buf2.read_frame() is None
    # search_from >= view_end：只有帧头
    buf3 = FixedHeaderTrailerFrameBuffer(b'\xaa\x55', b'\x0d\x0a')
    buf3.write(b'\xaa\x55')
    assert buf3.read_frame() is None


def test_header_len_trailer_properties_and_validation() -> None:
    with pytest.raises(ValueError, match='帧尾不能为空'):
        FixedHeaderLenTrailerFrameBuffer(b'\xeb\x90', 8, trailers=(b'',))
    with pytest.raises(ValueError, match='frame_size'):
        FixedHeaderLenTrailerFrameBuffer(b'\xeb\x90', 3, trailer=b'\x0a\x0d')
    with pytest.raises(ValueError, match='max_buffer'):
        FixedHeaderLenTrailerFrameBuffer(b'\xeb\x90', 8, trailer=b'\x0a\x0d', max_buffer=4)
    buf = FixedHeaderLenTrailerFrameBuffer(b'\xeb\x90', 6, trailer=b'\x0a\x0d')
    assert buf.header == b'\xeb\x90'
    assert buf.frame_size == 6
    assert buf.trailers == (b'\x0a\x0d',)
    # 半截 / 无头 / 未凑满
    buf.write(b'\xeb')
    assert buf.read_frame() is None
    buf.clear()
    buf.write(b'\x00\x11\x22')
    assert buf.read_frame() is None
    buf.clear()
    buf.write(b'\xeb\x90\x01')
    assert buf.read_frame() is None
    buf.write(b'\x02\x0a\x0d')
    assert buf.read_frame() == b'\xeb\x90\x01\x02\x0a\x0d'


def test_base_skip_bytes_and_empty_trim() -> None:
    buf = FixedHeaderLenFrameBuffer(b'\xeb\x90', 4, compact_at=2)
    buf.write(b'\xeb\x90\x01\x02')
    assert buf.read_frame() == b'\xeb\x90\x01\x02'
    buf._skip_bytes(0)
    # 单字节头 overflow 已覆盖 clear；此处触发 _trim 空缓冲早退
    buf2 = FixedHeaderLenFrameBuffer(b'\xaa', 2)
    buf2._trim_partial_header()
    assert buf2.pending == 0
    # write 时 _start>=compact_at 触发 _compact（line 44）
    buf3 = FixedHeaderLenFrameBuffer(b'\xaa', 2, compact_at=2)
    buf3.write(b'\xaa\x01\xaa\x02')
    assert buf3.read_frames() == [b'\xaa\x01', b'\xaa\x02']
    buf3.write(b'\xaa\x03')
    assert buf3.read_frame() == b'\xaa\x03'
