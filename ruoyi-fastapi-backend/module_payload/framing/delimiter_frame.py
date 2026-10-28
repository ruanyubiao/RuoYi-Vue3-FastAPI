"""分隔符定界流式组帧缓冲（对应 commfw delimiter）。"""

from __future__ import annotations

from module_payload.framing.base import StreamByteBuffer


class DelimiterFrameBuffer(StreamByteBuffer):
    """用分隔符切分字节流；返回的帧默认含分隔符。

    对应 commfw ``DelimiterDecoder``。min/max_frame_size 约束的是
    **含分隔符的整帧长度**（与本仓库 FixedHeaderTrailer 约定一致）。
    """

    __slots__ = ('_delimiter', '_min_frame_size', '_max_frame_size', '_include_delimiter')

    def __init__(
        self,
        delimiter: bytes | bytearray | memoryview,
        *,
        min_frame_size: int = 1,
        max_frame_size: int = 1 << 16,
        include_delimiter: bool = True,
        max_buffer: int = 1 << 20,
        compact_at: int = 4096,
    ) -> None:
        """delimiter 为定界字节序列。"""
        delim = bytes(delimiter)
        if not delim:
            raise ValueError('delimiter 不能为空')
        min_size = max(int(min_frame_size), len(delim))
        if max_frame_size < min_size:
            raise ValueError('max_frame_size 必须 >= min_frame_size')
        if max_buffer < max_frame_size:
            raise ValueError('max_buffer 必须 >= max_frame_size')
        super().__init__(sync_header=delim, max_buffer=max_buffer, compact_at=compact_at)
        self._delimiter = delim
        self._min_frame_size = min_size
        self._max_frame_size = int(max_frame_size)
        self._include_delimiter = bool(include_delimiter)

    @property
    def delimiter(self) -> bytes:
        """定界分隔符。"""
        return self._delimiter

    def read_frame(self) -> bytes | None:
        """搜分隔符切帧；过短跳过假分隔符，过长滑 1 字节。"""
        delim = self._delimiter
        dlen = len(delim)
        min_size = self._min_frame_size
        max_size = self._max_frame_size
        buf = self._buf
        start = self._start

        while True:
            available = len(buf) - start
            if available < dlen:
                self._start = start
                return None

            search_to = min(len(buf), start + max_size)
            idx = buf.find(delim, start, search_to)
            if idx < 0:
                if available >= max_size:
                    start += 1
                    continue
                self._start = start
                return None

            end = idx + dlen
            frame_len = end - start
            if frame_len < min_size:
                start = idx + 1
                continue

            raw = bytes(buf[start:end])
            start = end
            self._start = start
            if start >= self._compact_at:
                self._compact()
            if self._include_delimiter:
                return raw
            return raw[:-dlen] if dlen else raw
