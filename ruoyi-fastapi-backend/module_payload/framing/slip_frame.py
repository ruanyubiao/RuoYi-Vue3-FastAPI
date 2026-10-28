"""SLIP 流式组帧缓冲（RFC 1055，对应 commfw slip）。"""

from __future__ import annotations

from module_payload.framing.base import StreamByteBuffer

END = 0xC0
ESC = 0xDB
ESC_END = 0xDC
ESC_ESC = 0xDD


def slip_encode(data: bytes) -> bytes:
    """SLIP 编码：首尾加 END，载荷内 END/ESC 转义。"""
    out = bytearray((END,))
    for byte in data:
        if byte == END:
            out.extend((ESC, ESC_END))
        elif byte == ESC:
            out.extend((ESC, ESC_ESC))
        else:
            out.append(byte)
    out.append(END)
    return bytes(out)


def slip_decode(data: bytes) -> bytes:
    """SLIP 解码：还原两 END 之间的转义载荷。"""
    out = bytearray()
    i = 0
    while i < len(data):
        byte = data[i]
        if byte == END:
            i += 1
            continue
        if byte == ESC:
            if i + 1 >= len(data):
                raise ValueError('SLIP 转义序列不完整')
            second = data[i + 1]
            if second == ESC_END:
                out.append(END)
            elif second == ESC_ESC:
                out.append(ESC)
            else:
                raise ValueError(f'SLIP 非法转义字节 0x{second:02X}')
            i += 2
            continue
        out.append(byte)
        i += 1
    return bytes(out)


class SlipFrameBuffer(StreamByteBuffer):
    """以 0xC0 定界，对中间段做 SLIP 还原。

    对应 commfw ``SlipDecoder``。``read_frame`` 返回**还原后的载荷**。
    """

    __slots__ = ('_max_frame_size',)

    def __init__(
        self,
        *,
        max_frame_size: int = 1 << 16,
        max_buffer: int = 1 << 20,
        compact_at: int = 4096,
    ) -> None:
        if max_frame_size < 1:
            raise ValueError('max_frame_size 必须 >= 1')
        if max_buffer < max_frame_size:
            raise ValueError('max_buffer 必须 >= max_frame_size')
        super().__init__(sync_header=bytes((END,)), max_buffer=max_buffer, compact_at=compact_at)
        self._max_frame_size = int(max_frame_size)

    def read_frame(self) -> bytes | None:
        """搜 END…END，解码中间段。"""
        buf = self._buf
        max_size = self._max_frame_size
        pos = self._start

        while True:
            try:
                start = buf.index(END, pos)
            except ValueError:
                # 无 END：清空噪声（单字节前缀由 trim 保留）
                self._start = pos
                self._trim_partial_header()
                return None
            body_start = start + 1
            try:
                end = buf.index(END, body_start)
            except ValueError:
                self._start = start
                return None
            encoded_len = end - body_start
            if encoded_len > max_size:
                pos = start + 1
                continue
            encoded = bytes(buf[body_start:end])
            try:
                payload = slip_decode(encoded)
            except ValueError:
                pos = end + 1
                continue
            if len(payload) > max_size:
                pos = end + 1
                continue
            self._start = end + 1
            if self._start >= self._compact_at:
                self._compact()
            return payload
