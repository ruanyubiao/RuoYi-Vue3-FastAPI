"""COBS 定界流式组帧缓冲（对应 commfw cobs）。"""

from __future__ import annotations

from module_payload.framing.base import StreamByteBuffer


def cobs_encode(data: bytes) -> bytes:
    """COBS 编码：消除 data 中的 0x00。"""
    if not data:
        return b'\x01'
    out = bytearray()
    index = 0
    while index < len(data):
        block_start = len(out)
        out.append(0)
        code = 1
        while index < len(data) and data[index] != 0 and code < 255:
            out.append(data[index])
            index += 1
            code += 1
        out[block_start] = code
        if index < len(data) and data[index] == 0:
            index += 1
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    """COBS 解码：还原被消除的 0x00。"""
    out = bytearray()
    index = 0
    while index < len(data):
        code = data[index]
        if code == 0:
            raise ValueError('COBS 解码遇到非法零字节')
        index += 1
        for _ in range(code - 1):
            if index >= len(data):
                raise ValueError('COBS 解码长度不足')
            out.append(data[index])
            index += 1
        if code < 255 and index < len(data):
            out.append(0)
    if out and out[-1] == 0:
        out.pop()
    return bytes(out)


class CobsFrameBuffer(StreamByteBuffer):
    """以 delimiter（默认 0x00）切块，再对每块做 COBS 还原。

    对应 commfw ``CobsDecoder``。``read_frame`` 返回**还原后的载荷**。
    """

    __slots__ = ('_delimiter', '_max_frame_size')

    def __init__(
        self,
        *,
        delimiter: bytes | bytearray | memoryview | int = 0x00,
        max_frame_size: int = 1 << 16,
        max_buffer: int = 1 << 20,
        compact_at: int = 4096,
    ) -> None:
        if isinstance(delimiter, int):
            delim = bytes((delimiter & 0xFF,))
        else:
            delim = bytes(delimiter)
        if len(delim) != 1:
            raise ValueError('delimiter 必须是单字节')
        if max_frame_size < 1:
            raise ValueError('max_frame_size 必须 >= 1')
        if max_buffer < max_frame_size:
            raise ValueError('max_buffer 必须 >= max_frame_size')
        super().__init__(sync_header=delim, max_buffer=max_buffer, compact_at=compact_at)
        self._delimiter = delim[0]
        self._max_frame_size = int(max_frame_size)

    def read_frame(self) -> bytes | None:
        """搜 delimiter，对前一块做 COBS 解码。"""
        buf = self._buf
        delim = self._delimiter
        max_size = self._max_frame_size
        pos = self._start

        while True:
            try:
                idx = buf.index(delim, pos)
            except ValueError:
                self._start = pos
                return None
            block_len = idx - pos
            if block_len == 0:
                pos = idx + 1
                continue
            if block_len > max_size:
                pos = idx + 1
                continue
            encoded = bytes(buf[pos:idx])
            try:
                payload = cobs_decode(encoded)
            except ValueError:
                pos = idx + 1
                continue
            if len(payload) > max_size:
                pos = idx + 1
                continue
            self._start = idx + 1
            if self._start >= self._compact_at:
                self._compact()
            return payload
