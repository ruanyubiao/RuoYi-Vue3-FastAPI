"""固定帧头 + 固定帧长 + 固定帧尾的流式组帧缓冲。"""

from __future__ import annotations

from collections.abc import Iterable

from module_payload.framing.base import StreamByteBuffer


class FixedHeaderLenTrailerFrameBuffer(StreamByteBuffer):
    """固定头、定长、定尾（可多个合法尾）。

    流程：搜帧头 → 凑满 frame_size → 校验尾部 → 吐帧；
    尾不匹配则滑过帧头，继续重搜（伪起始）。

    用法（工程遥测 1040B）::

        buf = FixedHeaderLenTrailerFrameBuffer(
            b'\\x1A\\xCF', 1040,
            trailers=(b'\\x0A\\x0D', b'\\x0D\\x0A'),
        )
    """

    __slots__ = ('_header', '_frame_size', '_trailers', '_trailer_len')

    def __init__(
        self,
        header: bytes | bytearray | memoryview,
        frame_size: int,
        trailer: bytes | bytearray | memoryview | None = None,
        *,
        trailers: Iterable[bytes | bytearray | memoryview] | None = None,
        max_buffer: int = 1 << 20,
        compact_at: int = 4096,
    ) -> None:
        hdr = bytes(header)
        ends: list[bytes] = []
        if trailer is not None:
            ends.append(bytes(trailer))
        if trailers is not None:
            ends.extend(bytes(t) for t in trailers)
        if not ends:
            raise ValueError('至少提供一个帧尾')
        tlen = len(ends[0])
        if tlen < 1:
            raise ValueError('帧尾不能为空')
        for t in ends:
            if len(t) != tlen:
                raise ValueError('所有帧尾长度必须一致')
        if frame_size < len(hdr) + tlen:
            raise ValueError('frame_size 过小')
        if max_buffer < frame_size:
            raise ValueError('max_buffer 必须 >= frame_size')
        super().__init__(sync_header=hdr, max_buffer=max_buffer, compact_at=compact_at)
        self._header = hdr
        self._frame_size = int(frame_size)
        self._trailers = tuple(ends)
        self._trailer_len = tlen

    @property
    def header(self) -> bytes:
        return self._header

    @property
    def frame_size(self) -> int:
        return self._frame_size

    @property
    def trailers(self) -> tuple[bytes, ...]:
        return self._trailers

    def read_frame(self) -> bytes | None:
        hdr = self._header
        hdr_len = len(hdr)
        frame_size = self._frame_size
        tlen = self._trailer_len
        trailers = self._trailers
        buf = self._buf
        start = self._start

        while True:
            available = len(buf) - start
            if available < hdr_len:
                self._start = start
                return None

            idx = buf.find(hdr, start)
            if idx < 0:
                self._start = start
                self._trim_partial_header()
                return None
            if idx > start:
                start = idx
                available = len(buf) - start

            if available < frame_size:
                self._start = start
                return None

            end = start + frame_size
            tail = bytes(buf[end - tlen : end])
            if tail not in trailers:
                # 伪起始：滑过帧头，继续找下一个
                start += hdr_len
                continue

            frame = bytes(buf[start:end])
            start = end
            self._start = start
            if start >= self._compact_at:
                self._compact()
            return frame
