"""透传流式缓冲（对应 commfw identity）：不拆帧，原样吐出已写入字节。"""

from __future__ import annotations

from module_payload.framing.base import StreamByteBuffer


class IdentityFrameBuffer(StreamByteBuffer):
    """透传：``read_frame`` 返回当前全部 pending 字节；空则 None。

    对应 commfw ``IdentityDecoder``。用于不需要拆帧的通道。
    """

    def __init__(
        self,
        *,
        max_buffer: int = 1 << 20,
        compact_at: int = 4096,
    ) -> None:
        super().__init__(sync_header=b'', max_buffer=max_buffer, compact_at=compact_at)

    def read_frame(self) -> bytes | None:
        """取出并清空当前全部未读字节。"""
        n = self.pending
        if n <= 0:
            return None
        start = self._start
        frame = bytes(self._buf[start:])
        self._start = len(self._buf)
        self.clear()
        return frame
