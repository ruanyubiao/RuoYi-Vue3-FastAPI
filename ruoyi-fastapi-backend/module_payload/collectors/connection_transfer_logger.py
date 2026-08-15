"""连接级收发落盘：按 tag 双文件（_recv / _send），懒创建、切卷、异步写。"""

from __future__ import annotations

import queue
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

# 非 CAN 接收（裸 bin）切卷：满 1 分钟且 ≥100MB
ROTATE_MIN_AGE_S = 60.0
ROTATE_MIN_BYTES = 100 * 1024 * 1024
_QUEUE_MAX = 8192
_STOP = object()

Policy = Literal['daily', 'burst']


def default_log_root() -> Path:
    from config.paths import get_logs_data_dir

    return get_logs_data_dir()


def sanitize_tag(tag: str) -> str:
    s = (tag or '').strip() or 'unknown'
    s = s.replace(':', '_').replace('/', '_').replace('\\', '_').replace(' ', '_')
    s = re.sub(r'[^0-9A-Za-z._\-]+', '_', s)
    return s[:120] or 'unknown'


def infer_xfer_kind(device_id: str) -> str:
    """仅区分 can / 非 can；非 can 一律走裸 bin 收 + txt 发。"""
    d = (device_id or '').lower()
    if d.startswith('can:') or d.startswith('can'):
        return 'can'
    return 'other'


def tag_from_device_id(device_id: str) -> str:
    """home / 无 source 时用设备 id 净化名。"""
    return sanitize_tag(device_id or 'unknown')


def format_hex_bytes(data: bytes) -> str:
    return ' '.join(f'{b:02X}' for b in (data or b''))


def format_can_id(frame_id: int | None) -> str:
    if frame_id is None:
        return ' ' * 8
    return f'{int(frame_id) & 0x1FFFFFFF:08X}'


class _ChannelState:
    __slots__ = ('fp', 'path', 'opened_at', 'bytes_written', 'mode', 'day', 'policy')

    def __init__(self) -> None:
        self.fp = None
        self.path: Path | None = None
        self.opened_at = 0.0
        self.bytes_written = 0
        self.mode = ''  # 'bin' | 'txt'
        self.day = ''  # YYYYMMDD，日切卷用
        self.policy: Policy = 'burst'


class ConnectionTransferLogger:
    """一连接双通道落盘。kind=can → 收发均为 txt；其它一律 → recv 裸 bin、send txt。

    命名/切卷：
    - 所有 send、以及 CAN recv：一天一个文件 ``{tag}_{YYYYMMDD}_{dir}.txt``，隔日切换
    - 非 CAN recv：``{tag}_{YYYYMMDD_HHMMSS_mmm}_recv.bin``，满 1 分钟且 ≥100MB 切卷
    """

    def __init__(
        self,
        tag: str,
        *,
        kind: str = 'other',
        root_dir: Path | str | None = None,
    ) -> None:
        self.tag = sanitize_tag(tag)
        k = (kind or '').strip().lower()
        # 只认 can；其余硬件统一非 can 流程
        self.is_can = k == 'can'
        self.kind = 'can' if self.is_can else 'other'
        self.root_dir = Path(root_dir) if root_dir else default_log_root()
        self._q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
        self._recv = _ChannelState()
        self._send = _ChannelState()
        self._closed = False
        self._thread = threading.Thread(
            target=self._writer_loop,
            name=f'xfer-log-{self.tag}',
            daemon=True,
        )
        self._thread.start()

    def append_recv(self, data: bytes, *, frame_id: int | None = None) -> None:
        if self._closed or not data:
            return
        self._enqueue(('recv', bytes(data), frame_id, False))

    def append_send(self, data: bytes, *, frame_id: int | None = None) -> None:
        if self._closed:
            return
        if not data and frame_id is None:
            return
        self._enqueue(('send', bytes(data or b''), frame_id, False))

    def append_can_assembled(self, payload: bytes) -> None:
        """CAN 组包完成行：id 列 8 空格。"""
        if self._closed or not payload:
            return
        if not self.is_can:
            return
        self._enqueue(('recv', bytes(payload), None, True))

    def close(self, flush: bool = True) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._q.put(_STOP, timeout=2.0 if flush else 0.05)
        except Exception:
            pass
        if flush:
            self._thread.join(timeout=8.0)
        else:
            self._thread.join(timeout=0.5)
        self._close_channel(self._recv)
        self._close_channel(self._send)

    def _enqueue(self, item: tuple[Any, ...]) -> None:
        try:
            self._q.put_nowait(item)
        except queue.Full:
            try:
                self._q.get_nowait()
            except Exception:
                pass
            try:
                self._q.put_nowait(item)
            except Exception:
                pass

    def _writer_loop(self) -> None:
        while True:
            try:
                item = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is _STOP:
                while True:
                    try:
                        nxt = self._q.get_nowait()
                    except queue.Empty:
                        break
                    if nxt is _STOP:
                        continue
                    try:
                        self._write_item(nxt)
                    except Exception:
                        pass
                break
            try:
                self._write_item(item)
            except Exception:
                pass

    def _write_item(self, item: tuple[Any, ...]) -> None:
        direction, data, frame_id, assembled = item
        if direction == 'recv':
            self._write_recv(data, frame_id=frame_id, assembled=assembled)
        else:
            self._write_send(data, frame_id=frame_id)

    def _write_recv(self, data: bytes, *, frame_id: int | None, assembled: bool) -> None:
        if self.is_can:
            line = self._format_can_line(data, frame_id=frame_id, assembled=assembled)
            self._write_txt(self._recv, 'recv', line, policy='daily')
        else:
            self._write_bin(self._recv, 'recv', data, policy='burst')

    def _write_send(self, data: bytes, *, frame_id: int | None) -> None:
        if self.is_can:
            line = self._format_can_line(data, frame_id=frame_id, assembled=False)
            self._write_txt(self._send, 'send', line, policy='daily')
        else:
            line = self._format_plain_send_line(data)
            self._write_txt(self._send, 'send', line, policy='daily')

    @staticmethod
    def _format_can_line(data: bytes, *, frame_id: int | None, assembled: bool) -> str:
        ts = datetime.now().strftime('%Y%m%d%H%M%S')
        id_part = ' ' * 8 if assembled else format_can_id(frame_id)
        return f'{ts} {id_part} [{format_hex_bytes(data)}]\n'

    @staticmethod
    def _format_plain_send_line(data: bytes) -> str:
        ts = datetime.now().strftime('%Y%m%d%H%M%S')
        return f'{ts} [{format_hex_bytes(data)}]\n'

    def _write_bin(self, ch: _ChannelState, direction: str, data: bytes, *, policy: Policy) -> None:
        if not data:
            return
        self._ensure_file(ch, direction, 'bin', policy)
        self._rotate_if_needed(ch, direction, 'bin', policy)
        if not ch.fp:
            return
        ch.fp.write(data)
        ch.bytes_written += len(data)

    def _write_txt(self, ch: _ChannelState, direction: str, line: str, *, policy: Policy) -> None:
        raw = line.encode('utf-8')
        self._ensure_file(ch, direction, 'txt', policy)
        self._rotate_if_needed(ch, direction, 'txt', policy)
        if not ch.fp:
            return
        ch.fp.write(raw)
        ch.bytes_written += len(raw)

    def _ensure_file(self, ch: _ChannelState, direction: str, mode: str, policy: Policy) -> None:
        if ch.fp is not None:
            return
        now = datetime.now()
        day = now.strftime('%Y%m%d')
        folder = self.root_dir / day
        folder.mkdir(parents=True, exist_ok=True)
        ext = 'bin' if mode == 'bin' else 'txt'
        if policy == 'daily':
            # 一天一个：{tag}_{YYYYMMDD}_{recv|send}.txt ；同日重连追加
            name = f'{self.tag}_{day}_{direction}.{ext}'
            path = folder / name
            existed = path.exists()
            ch.fp = open(path, 'ab')
            ch.bytes_written = path.stat().st_size if existed else 0
        else:
            stamp = now.strftime('%Y%m%d_%H%M%S_%f')[:-3]  # ms
            name = f'{self.tag}_{stamp}_{direction}.{ext}'
            path = folder / name
            ch.fp = open(path, 'wb')
            ch.bytes_written = 0
        ch.path = path
        ch.opened_at = time.monotonic()
        ch.mode = mode
        ch.day = day
        ch.policy = policy

    def _rotate_if_needed(self, ch: _ChannelState, direction: str, mode: str, policy: Policy) -> None:
        if ch.fp is None:
            return
        today = datetime.now().strftime('%Y%m%d')
        if policy == 'daily':
            # 隔日切换到新日期文件（同时换到新日目录）
            if ch.day and ch.day != today:
                self._close_channel(ch)
                self._ensure_file(ch, direction, mode, policy)
            return
        age = time.monotonic() - ch.opened_at
        if age >= ROTATE_MIN_AGE_S and ch.bytes_written >= ROTATE_MIN_BYTES:
            self._close_channel(ch)
            self._ensure_file(ch, direction, mode, policy)

    @staticmethod
    def _close_channel(ch: _ChannelState) -> None:
        if ch.fp is None:
            return
        try:
            ch.fp.flush()
            ch.fp.close()
        except Exception:
            pass
        ch.fp = None
        ch.path = None
        ch.opened_at = 0.0
        ch.bytes_written = 0
        ch.mode = ''
        ch.day = ''
        ch.policy = 'burst'
