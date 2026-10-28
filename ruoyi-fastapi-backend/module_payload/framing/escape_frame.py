"""起止标志 + 转义流式组帧缓冲（对应 commfw escape）。"""

from __future__ import annotations

from collections.abc import Mapping

from module_payload.framing.base import StreamByteBuffer


class EscapeFrameBuffer(StreamByteBuffer):
    """帧格式：start_flag + 转义载荷 + end_flag。

    对应 commfw ``EscapeDecoder``。``escape_map`` 缺省时按 HDLC 风格
    （转义后字节 xor 0x20 还原）。返回**还原后的载荷**（不含起止标志）。
    """

    __slots__ = ('_start_b', '_end_b', '_escape', '_reverse_map', '_max_frame_size', '_default_xor')

    def __init__(
        self,
        start_flag: bytes | bytearray | memoryview | int,
        end_flag: bytes | bytearray | memoryview | int,
        escape_byte: bytes | bytearray | memoryview | int,
        *,
        escape_map: Mapping[int, int] | None = None,
        max_frame_size: int = 1 << 16,
        max_buffer: int = 1 << 20,
        compact_at: int = 4096,
    ) -> None:
        """start/end/escape 均为单字节；escape_map 为 原值→转义后值。"""

        def _one(spec: bytes | bytearray | memoryview | int, name: str) -> int:
            if isinstance(spec, int):
                return spec & 0xFF
            b = bytes(spec)
            if len(b) != 1:
                raise ValueError(f'{name} 必须是单字节')
            return b[0]

        start_b = _one(start_flag, 'start_flag')
        end_b = _one(end_flag, 'end_flag')
        esc = _one(escape_byte, 'escape_byte')
        if max_frame_size < 1:
            raise ValueError('max_frame_size 必须 >= 1')
        if max_buffer < max_frame_size:
            raise ValueError('max_buffer 必须 >= max_frame_size')
        reverse = {v: k for k, v in escape_map.items()} if escape_map else {}
        super().__init__(sync_header=bytes((start_b,)), max_buffer=max_buffer, compact_at=compact_at)
        self._start_b = start_b
        self._end_b = end_b
        self._escape = esc
        self._reverse_map = reverse
        self._max_frame_size = int(max_frame_size)
        self._default_xor = escape_map is None

    def read_frame(self) -> bytes | None:
        """搜起始标志，累积到结束标志；遇转义字节立即还原。"""
        buf = self._buf
        start_b = self._start_b
        end_b = self._end_b
        esc = self._escape
        max_size = self._max_frame_size
        pos = self._start

        while True:
            if len(buf) - pos < 2:
                self._start = pos
                return None
            try:
                idx = buf.index(start_b, pos)
            except ValueError:
                self._start = pos
                self._trim_partial_header()
                return None

            i = idx + 1
            out = bytearray()
            escaped = False
            bad = False
            while i < len(buf):
                b = buf[i]
                if escaped:
                    if self._default_xor:
                        out.append(b ^ 0x20)
                    else:
                        out.append(self._reverse_map.get(b, b))
                    escaped = False
                    i += 1
                elif b == esc:
                    escaped = True
                    i += 1
                elif b == end_b:
                    if len(out) > max_size:
                        pos = idx + 1
                        bad = True
                        break
                    self._start = i + 1
                    if self._start >= self._compact_at:
                        self._compact()
                    return bytes(out)
                else:
                    out.append(b)
                    i += 1
                if len(out) > max_size:
                    pos = idx + 1
                    bad = True
                    break
            else:
                self._start = idx
                return None
            if bad:
                continue
