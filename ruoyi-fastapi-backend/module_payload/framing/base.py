"""流式组帧缓冲公共底座：单块 bytearray + 读偏移。"""

from __future__ import annotations


class StreamByteBuffer:
    """高速字节流缓存；子类负责同步与拆帧策略。"""

    __slots__ = ('_buf', '_start', '_max_buffer', '_compact_at', '_sync_header')

    def __init__(
        self,
        *,
        sync_header: bytes,
        max_buffer: int = 1 << 20,
        compact_at: int = 4096,
    ) -> None:
        """sync_header 用于超限裁切时保留可能跨块的帧头前缀。"""
        if not sync_header:
            raise ValueError('sync_header 不能为空')
        if max_buffer < 1:
            raise ValueError('max_buffer 必须 >= 1')
        self._sync_header = bytes(sync_header)
        self._buf = bytearray()  # 粘包共享缓冲
        self._start = 0  # 已消费偏移
        self._max_buffer = int(max_buffer)
        self._compact_at = max(int(compact_at), len(self._sync_header))

    @property
    def pending(self) -> int:
        """尚未拆出的缓冲字节数。"""
        return len(self._buf) - self._start

    def clear(self) -> None:
        """丢掉未拆完的粘包缓冲。"""
        self._buf.clear()
        self._start = 0

    def write(self, data: bytes | bytearray | memoryview) -> None:
        """追加字节；超上限只留帧头前缀，避免粘包缓冲无限涨。"""
        if not data:
            return
        if self._start >= self._compact_at:
            self._compact()
        self._buf.extend(data)
        if self.pending > self._max_buffer:
            keep = len(self._sync_header) - 1
            self._buf = self._buf[-keep:] if keep > 0 else bytearray()
            self._start = 0
            self._trim_partial_header()

    def read_frames(self, limit: int | None = None) -> list[bytes]:
        """连续拆帧直到半截或达到 limit。"""
        out: list[bytes] = []
        while limit is None or len(out) < limit:
            frame = self.read_frame()
            if frame is None:
                break
            out.append(frame)
        return out

    def read_frame(self) -> bytes | None:
        """拆出一帧完整帧；半截返回 None。子类实现同步策略。"""
        raise NotImplementedError

    def _compact(self) -> None:
        """丢掉已消费前缀，把未拆完数据挪到缓冲头。"""
        if self._start <= 0:
            return
        if self._start >= len(self._buf):
            self._buf.clear()
            self._start = 0
            return
        del self._buf[: self._start]
        self._start = 0

    def _trim_partial_header(self) -> None:
        """找不到完整帧头时，只保留可能跨块的帧头前缀。"""
        hdr = self._sync_header
        keep_max = len(hdr) - 1
        if keep_max <= 0:
            self.clear()
            return
        self._compact()
        data = self._buf
        n = len(data)
        if n == 0:
            return
        keep = 0
        for k in range(min(keep_max, n), 0, -1):
            if data.endswith(hdr[:k]):
                keep = k
                break
        if keep == 0:
            data.clear()
        elif keep < n:
            del data[:-keep]

    def _skip_bytes(self, n: int) -> None:
        """滑过 n 字节（伪起始），必要时 compact。"""
        self._start += max(0, n)
        if self._start >= self._compact_at:
            self._compact()
