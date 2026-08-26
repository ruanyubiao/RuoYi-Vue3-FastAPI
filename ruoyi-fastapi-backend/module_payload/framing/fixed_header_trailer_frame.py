"""固定帧头 + 固定帧尾（变长正文）的流式组帧缓冲。"""

from __future__ import annotations

from module_payload.framing.base import StreamByteBuffer


class FixedHeaderTrailerFrameBuffer(StreamByteBuffer):
    """固定头 + 固定尾；中间长度不固定，靠搜尾定界。

    用法::

        buf = FixedHeaderTrailerFrameBuffer(b'\\xAA\\x55', b'\\x0D\\x0A', max_frame_size=4096)
        buf.write(chunk)
        frame = buf.read_frame()
    """

    __slots__ = ('_header', '_trailer', '_min_frame_size', '_max_frame_size')

    def __init__(
        self,
        header: bytes | bytearray | memoryview,
        trailer: bytes | bytearray | memoryview,
        *,
        max_frame_size: int = 1 << 16,
        min_frame_size: int | None = None,
        max_buffer: int = 1 << 20,
        compact_at: int = 4096,
    ) -> None:
        """靠搜尾定界；min/max_frame_size 限制合法帧长。"""
        hdr = bytes(header)
        trl = bytes(trailer)
        if not trl:
            raise ValueError('帧尾不能为空')
        min_size = len(hdr) + len(trl) if min_frame_size is None else int(min_frame_size)
        if min_size < len(hdr) + len(trl):
            raise ValueError('min_frame_size 过小')
        if max_frame_size < min_size:
            raise ValueError('max_frame_size 必须 >= min_frame_size')
        if max_buffer < max_frame_size:
            raise ValueError('max_buffer 必须 >= max_frame_size')
        super().__init__(sync_header=hdr, max_buffer=max_buffer, compact_at=compact_at)
        self._header = hdr
        self._trailer = trl
        self._min_frame_size = min_size
        self._max_frame_size = int(max_frame_size)

    @property
    def header(self) -> bytes:
        """同步帧头。"""
        return self._header

    @property
    def trailer(self) -> bytes:
        """定界帧尾。"""
        return self._trailer

    def read_frame(self) -> bytes | None:
        """搜头后在 max_frame_size 内搜尾；半截等下次，超长当伪头滑 1 字节。"""
        hdr = self._header
        trl = self._trailer
        hdr_len = len(hdr)
        trl_len = len(trl)
        min_size = self._min_frame_size
        max_size = self._max_frame_size
        buf = self._buf
        start = self._start

        while True:
            available = len(buf) - start
            if available < hdr_len:
                self._start = start
                return None  # 半截帧头

            idx = buf.find(hdr, start)
            if idx < 0:
                self._start = start
                self._trim_partial_header()
                return None
            if idx > start:
                start = idx
                available = len(buf) - start

            # 在 [header后, max_size) 范围内搜尾
            search_from = start + hdr_len
            search_to = start + max_size
            view_end = len(buf)
            if search_from >= view_end:
                self._start = start
                return None

            trl_idx = buf.find(trl, search_from, min(search_to, view_end))
            if trl_idx < 0:
                # 已超最大帧长仍无尾：伪帧头，滑过 1 字节重搜
                if available >= max_size:
                    start += 1
                    continue
                self._start = start
                return None

            end = trl_idx + trl_len
            frame_len = end - start
            if frame_len < min_size:
                # 尾过近，从 header 后继续找下一个尾
                # 简化：滑过 1 字节重搜（避免死循环在同一伪头）
                start += 1
                continue

            frame = bytes(buf[start:end])
            start = end
            self._start = start
            if start >= self._compact_at:
                self._compact()
            return frame
