"""无头定长流式组帧缓冲（对应 commfw fixed_length）。"""

from __future__ import annotations

from module_payload.framing.base import StreamByteBuffer


class FixedLenFrameBuffer(StreamByteBuffer):
    """无同步头、固定步进切帧。

    对应 commfw ``FixedLengthDecoder``。有同步头的定长请用
    ``FixedHeaderLenFrameBuffer``。
    """

    __slots__ = ('_frame_size',)

    def __init__(
        self,
        frame_size: int,
        *,
        max_buffer: int = 1 << 20,
        compact_at: int = 4096,
    ) -> None:
        """frame_size 为每帧固定字节数。"""
        if frame_size < 1:
            raise ValueError('frame_size 必须 >= 1')
        if max_buffer < frame_size:
            raise ValueError('max_buffer 必须 >= frame_size')
        super().__init__(sync_header=b'', max_buffer=max_buffer, compact_at=compact_at)
        self._frame_size = int(frame_size)

    @property
    def frame_size(self) -> int:
        """固定帧长。"""
        return self._frame_size

    def write(self, data: bytes | bytearray | memoryview) -> None:
        """追加字节；超限时保留不足一帧的尾部。"""
        if not data:
            return
        if self._start >= self._compact_at:
            self._compact()
        self._buf.extend(data)
        if self.pending > self._max_buffer:
            keep = self._frame_size - 1
            self._compact()
            if keep <= 0:
                self._buf.clear()
            elif len(self._buf) > keep:
                del self._buf[:-keep]
            self._start = 0

    def read_frame(self) -> bytes | None:
        """按定长切出一帧；不足则等下次。"""
        frame_size = self._frame_size
        available = len(self._buf) - self._start
        if available < frame_size:
            return None
        start = self._start
        end = start + frame_size
        frame = bytes(self._buf[start:end])
        self._start = end
        if self._start >= self._compact_at:
            self._compact()
        return frame
