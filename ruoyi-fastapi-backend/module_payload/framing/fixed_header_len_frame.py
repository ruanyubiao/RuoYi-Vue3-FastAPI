"""固定帧头 + 固定帧长的流式组帧缓冲。"""

from __future__ import annotations

from module_payload.framing.base import StreamByteBuffer


class FixedHeaderLenFrameBuffer(StreamByteBuffer):
    """固定帧头、固定长度帧。

    用法::

        buf = FixedHeaderLenFrameBuffer(b'\\xEB\\x90', 266)
        buf.write(chunk)
        frame = buf.read_frame()  # bytes | None
    """

    __slots__ = ('_header', '_frame_size')

    def __init__(
        self,
        header: bytes | bytearray | memoryview,
        frame_size: int,
        *,
        max_buffer: int = 1 << 20,
        compact_at: int = 4096,
    ) -> None:
        """header 为同步头；frame_size 含帧头的固定总长。"""
        hdr = bytes(header)
        if frame_size < len(hdr):
            raise ValueError(f'frame_size({frame_size}) 必须 >= 帧头长度({len(hdr)})')
        if max_buffer < frame_size:
            raise ValueError('max_buffer 必须 >= frame_size')
        super().__init__(sync_header=hdr, max_buffer=max_buffer, compact_at=compact_at)
        self._header = hdr
        self._frame_size = int(frame_size)

    @property
    def header(self) -> bytes:
        """同步帧头。"""
        return self._header

    @property
    def frame_size(self) -> int:
        """含帧头的固定总长。"""
        return self._frame_size

    def read_frame(self) -> bytes | None:
        """搜帧头后按定长切开；半截帧留缓冲，找不到头则只留前缀。"""
        hdr = self._header
        hdr_len = len(hdr)
        frame_size = self._frame_size
        buf = self._buf
        start = self._start

        while True:
            available = len(buf) - start
            if available < hdr_len:
                self._start = start
                return None  # 半截帧头，等下次 write

            idx = buf.find(hdr, start)
            if idx < 0:
                self._start = start
                self._trim_partial_header()
                return None

            if idx > start:
                start = idx  # 丢掉帧头前的噪声
                available = len(buf) - start

            if available < frame_size:
                self._start = start
                return None  # 已对齐但未凑满定长

            end = start + frame_size
            frame = bytes(buf[start:end])
            start = end
            self._start = start
            if start >= self._compact_at:
                self._compact()
            return frame
