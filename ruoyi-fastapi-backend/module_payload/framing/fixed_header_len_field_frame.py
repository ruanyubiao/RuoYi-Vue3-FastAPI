"""固定帧头 + 帧内长度字段（可变总长）的流式组帧缓冲。"""

from __future__ import annotations

from module_payload.framing.base import StreamByteBuffer


class FixedHeaderLenFieldFrameBuffer(StreamByteBuffer):
    """固定帧头 + 帧内长度字段；总长由长度字段换算，可随帧变化。

    对应 commfw ``LengthFieldDecoder``；与 ``FixedHeaderLenFrameBuffer``
    （构造时定死 ``frame_size``）不同，不要混用。

    length_base:
        - ``payload`` — 长度字段 = 纯载荷字节数（载荷后固定开销用 length_adjust）
        - ``total`` — 长度字段 = 整帧总长
        - ``after_length`` — 长度字段 = 长度字段之后剩余字节数

    用法（YJ216 RS422：EB90 AA | lenBE | 数据(序号+字段) | sum16(数据区)）::

        buf = FixedHeaderLenFieldFrameBuffer(
            b'\xEB\x90\x3A',
            length_offset=3,
            length_width=2,
            endian='big',
            length_base='payload',
            length_adjust=3,  # 序号(1) + 校验(2)
            min_frame_size=8,
            max_frame_size=65543,
        )
    """

    __slots__ = (
        '_header',
        '_length_offset',
        '_length_width',
        '_endian',
        '_length_base',
        '_length_adjust',
        '_min_frame_size',
        '_max_frame_size',
    )

    def __init__(
        self,
        header: bytes | bytearray | memoryview,
        *,
        length_offset: int,
        length_width: int = 2,
        endian: str = 'big',
        length_base: str = 'payload',
        length_adjust: int = 0,
        min_frame_size: int = 0,
        max_frame_size: int = 65536,
        max_buffer: int = 1 << 20,
        compact_at: int = 4096,
    ) -> None:
        """header 同步；length_* 描述帧内长度字段；min/max 约束整帧总长。"""
        hdr = bytes(header)
        if not hdr:
            raise ValueError('header 不能为空')
        if endian not in ('big', 'little'):
            raise ValueError(f"endian 必须是 'big' 或 'little'，当前为 {endian!r}")
        if length_width not in (1, 2, 4):
            raise ValueError(f'length_width 不受支持：{length_width}')
        if length_offset < len(hdr):
            raise ValueError('length_offset 必须 >= 帧头长度')
        if length_base not in ('payload', 'total', 'after_length'):
            raise ValueError(f'length_base 不受支持：{length_base!r}')
        min_need = length_offset + length_width
        min_size = max(int(min_frame_size), min_need)
        if max_frame_size < min_size:
            raise ValueError('max_frame_size 必须 >= min_frame_size')
        if max_buffer < max_frame_size:
            raise ValueError('max_buffer 必须 >= max_frame_size')
        super().__init__(sync_header=hdr, max_buffer=max_buffer, compact_at=compact_at)
        self._header = hdr
        self._length_offset = int(length_offset)
        self._length_width = int(length_width)
        self._endian = endian
        self._length_base = length_base
        self._length_adjust = int(length_adjust)
        self._min_frame_size = min_size
        self._max_frame_size = int(max_frame_size)

    @property
    def header(self) -> bytes:
        """同步帧头。"""
        return self._header

    @property
    def length_offset(self) -> int:
        """长度字段相对帧起点的偏移。"""
        return self._length_offset

    @property
    def length_width(self) -> int:
        """长度字段字节数。"""
        return self._length_width

    @property
    def min_frame_size(self) -> int:
        """合法整帧最短字节数。"""
        return self._min_frame_size

    @property
    def max_frame_size(self) -> int:
        """合法整帧最长字节数。"""
        return self._max_frame_size

    def _frame_size_from_declared(self, declared: int) -> int:
        """把长度字段声明值换算为整帧字节数。"""
        if self._length_base == 'total':
            return declared + self._length_adjust
        # payload / after_length：从长度字段末尾起算
        return self._length_offset + self._length_width + declared + self._length_adjust

    def read_frame(self) -> bytes | None:
        """搜头 → 读长度字段 → 按换算总长切开；半截等下次，非法长度滑 1 字节。"""
        hdr = self._header
        hdr_len = len(hdr)
        length_off = self._length_offset
        length_w = self._length_width
        min_need = length_off + length_w
        min_size = self._min_frame_size
        max_size = self._max_frame_size
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

            if available < min_need:
                self._start = start
                return None

            declared = int.from_bytes(
                buf[start + length_off : start + length_off + length_w],
                self._endian,
            )
            frame_size = self._frame_size_from_declared(declared)
            if frame_size < min_size or frame_size > max_size:
                start += 1
                continue

            if available < frame_size:
                self._start = start
                return None

            end = start + frame_size
            if bytes(buf[start : start + hdr_len]) != hdr:
                start += 1
                continue

            frame = bytes(buf[start:end])
            start = end
            self._start = start
            if start >= self._compact_at:
                self._compact()
            return frame
