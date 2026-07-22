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
        if not sync_header:
            raise ValueError('sync_header 不能为空')
        if max_buffer < 1:
            raise ValueError('max_buffer 必须 >= 1')
        self._sync_header = bytes(sync_header)
        self._buf = bytearray()
        self._start = 0
        self._max_buffer = int(max_buffer)
        self._compact_at = max(int(compact_at), len(self._sync_header))

    @property
    def pending(self) -> int:
        return len(self._buf) - self._start

    def clear(self) -> None:
        self._buf.clear()
        self._start = 0

    def write(self, data: bytes | bytearray | memoryview) -> None:
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
        out: list[bytes] = []
        while limit is None or len(out) < limit:
            frame = self.read_frame()
            if frame is None:
                break
            out.append(frame)
        return out

    def read_frame(self) -> bytes | None:
        raise NotImplementedError

    def _compact(self) -> None:
        if self._start <= 0:
            return
        if self._start >= len(self._buf):
            self._buf.clear()
            self._start = 0
            return
        del self._buf[: self._start]
        self._start = 0

    def _trim_partial_header(self) -> None:
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
        self._start += max(0, n)
        if self._start >= self._compact_at:
            self._compact()
