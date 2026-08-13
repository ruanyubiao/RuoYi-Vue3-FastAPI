"""相机传图串口模拟器（SC-LINK41EP 图像下传 D6）。

单独运行，不依赖后端进程。用虚拟串口对与地检平台「图像串口」相连后，
只应答传图请求帧（10 字节），其它数据丢弃；按序号切本地图像并回 266 字节应答。

用法（在 backend 目录、已装依赖的 venv）:
    pip install PyQt6
    python scripts/camera_image_serial_sim.py

串口参数与平台相机图像口一致：8 数据位 / 奇校验 / 1 停止位。
波特率仅 2000000、11000000。
"""

from __future__ import annotations

import math
import random
import sys
import threading
import time
from pathlib import Path

import numpy as np
import serial
from serial.tools import list_ports

try:
    from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
    from PyQt6.QtGui import QImage, QPixmap, QTextCursor
    from PyQt6.QtWidgets import (
        QApplication,
        QComboBox,
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSizePolicy,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise SystemExit('请先安装 PyQt6：pip install PyQt6') from exc

# ---- D6 协议（与 module_payload.assemblers.camera_image_d6 一致）----
FRAME_HEADER = bytes([0xEB, 0x90])
FRAME_TYPE = 0xD6
FRAME_ID_FIRST = 0x04
FRAME_ID_MID = 0x02
FRAME_ID_LAST = 0x01
REQ_SIZE = 10
RESP_SIZE = 266
DATA_CHUNK = 256
REQ_LEN = 0x0001
RESP_LEN = 0x0101

RESOLUTIONS = {
    '400×400': (400, 400),
    '256×256': (256, 256),
    '128×128': (128, 128),
    '64×64': (64, 64),
}
BAUDRATES = [2_000_000, 11_000_000]
FRAME_ID_NAMES = {
    FRAME_ID_FIRST: '首帧',
    FRAME_ID_MID: '中间帧',
    FRAME_ID_LAST: '尾帧',
}


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def _sip_ptr_to_uint8(ptr, nbytes: int) -> np.ndarray:
    """PyQt6 sip.voidptr 没有 size，numpy.frombuffer 会报 unknown size。"""
    asarray = getattr(ptr, 'asarray', None)
    if callable(asarray):
        view = asarray(nbytes)
        return np.frombuffer(view, dtype=np.uint8, count=nbytes).copy()
    setsize = getattr(ptr, 'setsize', None)
    if callable(setsize):
        setsize(nbytes)
        return np.frombuffer(ptr, dtype=np.uint8, count=nbytes).copy()
    try:
        from PyQt6 import sip

        wrapped = sip.voidptr(ptr, nbytes)
        return np.frombuffer(wrapped, dtype=np.uint8, count=nbytes).copy()
    except Exception:
        pass
    return np.fromiter((ptr[i] for i in range(nbytes)), dtype=np.uint8, count=nbytes)


def qimage_to_gray_array(qimg: QImage) -> np.ndarray:
    """QImage → 连续 uint8 灰度矩阵。按扫描行拷贝，去掉 bytesPerLine 对齐填充。"""
    gray = qimg.convertToFormat(QImage.Format.Format_Grayscale8)
    w, h = gray.width(), gray.height()
    if w <= 0 or h <= 0:
        raise ValueError('图片尺寸无效')
    bpl = gray.bytesPerLine()
    arr = np.empty((h, w), dtype=np.uint8)
    for y in range(h):
        row = _sip_ptr_to_uint8(gray.scanLine(y), bpl)
        arr[y, :] = row[:w]
    return arr


def scale_gray_array(arr: np.ndarray, w: int, h: int) -> np.ndarray:
    """缩放到发送分辨率（忽略宽高比，填满 n×n）。"""
    src_h, src_w = int(arr.shape[0]), int(arr.shape[1])
    if src_w == w and src_h == h:
        return np.ascontiguousarray(arr, dtype=np.uint8)
    qimg = QImage(
        np.ascontiguousarray(arr, dtype=np.uint8).tobytes(),
        src_w,
        src_h,
        src_w,
        QImage.Format.Format_Grayscale8,
    ).copy()
    scaled = qimg.scaled(
        w,
        h,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    return qimage_to_gray_array(scaled)


def take_row_major_chunk(arr: np.ndarray, start: int, count: int = DATA_CHUNK) -> bytes:
    """按行取连续像素：位置 i 对应 y,x = divmod(i, width)，再切 256 字节。"""
    out = np.zeros(count, dtype=np.uint8)
    if arr is None or arr.ndim != 2 or arr.size == 0 or start < 0:
        return out.tobytes()
    flat = np.ascontiguousarray(arr, dtype=np.uint8).ravel()
    if start >= flat.size:
        return out.tobytes()
    n = min(count, flat.size - start)
    out[:n] = flat[start : start + n]
    return out.tobytes()


def parse_request(buf: bytes) -> tuple[int, int, int] | None:
    """解析 10 字节传图请求，返回 (frame_id, seq, image_no)。"""
    if len(buf) < REQ_SIZE:
        return None
    if buf[0:2] != FRAME_HEADER or buf[2] != FRAME_TYPE:
        return None
    frame_id = buf[3]
    if frame_id not in FRAME_ID_NAMES:
        return None
    length = (buf[4] << 8) | buf[5]
    if length != REQ_LEN:
        return None
    seq = (buf[6] << 8) | buf[7]
    image_no = buf[8]
    if checksum(buf[2:9]) != buf[9]:
        return None
    return frame_id, seq, image_no


def build_response(frame_id: int, seq: int, image_no: int, chunk: bytes) -> bytes:
    if len(chunk) < DATA_CHUNK:
        chunk = chunk + bytes(DATA_CHUNK - len(chunk))
    elif len(chunk) > DATA_CHUNK:
        chunk = chunk[:DATA_CHUNK]
    body = bytes(
        [
            FRAME_TYPE,
            frame_id & 0xFF,
            (RESP_LEN >> 8) & 0xFF,
            RESP_LEN & 0xFF,
            (seq >> 8) & 0xFF,
            seq & 0xFF,
            image_no & 0xFF,
        ]
    ) + chunk
    return FRAME_HEADER + body + bytes([checksum(body)])


def infer_n_from_last_seq(seq: int) -> int | None:
    """尾帧反推正方形边长 n。

    已发送总和 = seq * 256（首帧+中间帧均为满数据）。
    总像素上限 = (seq+1)*256，n 最大为 floor(sqrt(上限))。
    从 1 遍历到 n_max，条件 n*n > seq*256 且剩余像素不超过 256，取最大 n。
    """
    if seq < 0:
        return None
    already = seq * DATA_CHUNK
    max_pixels = (seq + 1) * DATA_CHUNK
    n_max = math.isqrt(max_pixels)
    found: int | None = None
    for n in range(1, n_max + 1):
        area = n * n
        if area > already and (area - already) <= DATA_CHUNK:
            found = n
    return found


def fmt_hex(data: bytes, limit: int = 16) -> str:
    part = data[:limit]
    text = ' '.join(f'{b:02X}' for b in part)
    if len(data) > limit:
        text += ' …'
    return text


def diagnose_request(buf: bytes) -> str:
    if len(buf) < REQ_SIZE:
        return '长度不足 10 字节'
    if buf[0:2] != FRAME_HEADER:
        return '帧头不是 EB 90'
    if buf[2] != FRAME_TYPE:
        return f'非传图请求(类型 0x{buf[2]:02X})'
    if buf[3] not in FRAME_ID_NAMES:
        return f'帧标识无效 0x{buf[3]:02X}'
    length = (buf[4] << 8) | buf[5]
    if length != REQ_LEN:
        return f'长度字段 0x{length:04X} 不是 0x0001'
    if checksum(buf[2:9]) != buf[9]:
        return f'校验错误 expect={checksum(buf[2:9]):02X} got={buf[9]:02X}'
    return '格式错误'


def find_valid_request_offset(data: bytes) -> int:
    """在缓存中找第一条完整且校验通过的 10 字节传图请求。"""
    search = 0
    while True:
        idx = data.find(FRAME_HEADER, search)
        if idx < 0 or idx + REQ_SIZE > len(data):
            return -1
        if parse_request(data[idx : idx + REQ_SIZE]) is not None:
            return idx
        search = idx + 1


def looks_like_response_prefix(buf: bytearray) -> bool:
    if len(buf) < 6:
        return False
    return (
        buf[0] == FRAME_HEADER[0]
        and buf[1] == FRAME_HEADER[1]
        and buf[2] == FRAME_TYPE
        and ((buf[4] << 8) | buf[5]) == RESP_LEN
    )


def consume_rx(buf: bytearray) -> list[tuple]:
    """从接收缓存取出请求事件；应答帧和垃圾静默丢弃。

    返回 ('ok', (frame_id, seq, image_no), raw10) 或 ('bad', raw10, why)。
    半截帧留在 buf 里等后续字节，不把后面的合法请求吃掉。
    """
    events: list[tuple] = []
    while buf:
        if looks_like_response_prefix(buf):
            if len(buf) < RESP_SIZE:
                off = find_valid_request_offset(bytes(buf))
                if off >= 0:
                    del buf[:off]
                    continue
                return events
            del buf[:RESP_SIZE]
            continue

        off = find_valid_request_offset(bytes(buf))
        if off >= 0:
            if off > 0:
                del buf[:off]
            raw = bytes(buf[:REQ_SIZE])
            parsed = parse_request(raw)
            del buf[:REQ_SIZE]
            events.append(('ok', parsed, raw))
            continue

        try:
            eb = buf.index(0xEB)
        except ValueError:
            buf.clear()
            return events
        if eb > 0:
            del buf[:eb]
            continue
        if len(buf) < 3:
            return events
        if buf[1] != 0x90 or buf[2] != FRAME_TYPE:
            del buf[0]
            continue
        if len(buf) < 6:
            return events
        length = (buf[4] << 8) | buf[5]
        if length == REQ_LEN:
            if len(buf) < REQ_SIZE:
                return events
            raw = bytes(buf[:REQ_SIZE])
            events.append(('bad', raw, diagnose_request(raw)))
            del buf[0]
            continue
        del buf[0]
    return events


def clear_port_buffers(ser: serial.Serial) -> None:
    """打开串口或开始监听前清掉驱动收发缓存。"""
    for fn in (ser.reset_input_buffer, ser.reset_output_buffer):
        try:
            fn()
        except Exception:
            pass
    try:
        n = ser.in_waiting or 0
        if n:
            ser.read(n)
    except Exception:
        pass


class TransferState:
    """串口线程写、主线程读。是否在传只看 is_transferring()。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._busy = False
        self._pixels: np.ndarray | None = None

    def is_transferring(self) -> bool:
        with self._lock:
            return self._busy

    def current_pixels(self) -> np.ndarray | None:
        with self._lock:
            return self._pixels

    def on_request(self, snapshot: np.ndarray) -> np.ndarray | None:
        with self._lock:
            if self._busy:
                return self._pixels
            if snapshot is None or snapshot.size == 0:
                return None
            self._pixels = snapshot
            self._busy = True
            return self._pixels

    def on_last_frame(self) -> None:
        with self._lock:
            self._busy = False
            self._pixels = None


class SerialWorker(QThread):
    progress = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        ser: serial.Serial,
        pixels_lock: threading.Lock,
        get_arr,
        xfer: TransferState,
    ) -> None:
        super().__init__()
        self._ser = ser
        self._lock = pixels_lock
        self._get_arr = get_arr
        self._xfer = xfer
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        buf = bytearray()
        try:
            clear_port_buffers(self._ser)
        except Exception:
            pass
        while self._running:
            try:
                if not self._ser or not self._ser.is_open:
                    break
                waiting = self._ser.in_waiting or 0
                chunk = self._ser.read(waiting or 1)
                if not chunk:
                    continue
                buf.extend(chunk)
                if len(buf) > 8192:
                    keep = buf[-2048:]
                    eb = keep.find(b'\xeb')
                    buf[:] = keep[eb:] if eb >= 0 else keep[-1:]
                self._drain(buf)
            except Exception as e:
                if not self._running:
                    break
                alive = False
                try:
                    alive = bool(self._ser and self._ser.is_open)
                except Exception:
                    alive = False
                if not alive:
                    self.failed.emit(str(e) or e.__class__.__name__)
                    break
                self.progress.emit(f'处理异常: {e}，继续等待传图请求')
                time.sleep(0.02)

    def _drain(self, buf: bytearray) -> None:
        for ev in consume_rx(buf):
            kind = ev[0]
            if kind == 'ok':
                _tag, parsed, raw = ev
                self._reply(*parsed, raw=raw)
            elif kind == 'bad':
                _tag, raw, why = ev
                self.progress.emit(f'接收指令不正确  {fmt_hex(raw)}  {why}，已丢弃')

    def _reply(self, frame_id: int, seq: int, image_no: int, raw: bytes = b'') -> None:
        head = f'接收指令正确  {fmt_hex(raw)}  ' if raw else '接收指令正确  '
        arr = self._xfer.current_pixels()
        if arr is None:
            with self._lock:
                snapped = self._get_arr()
            arr = self._xfer.on_request(snapped)
            if arr is None:
                self.progress.emit(f'{head}但还没有预览图像，已丢弃')
                return
        h, w = int(arr.shape[0]), int(arr.shape[1])
        kind = FRAME_ID_NAMES.get(frame_id, f'0x{frame_id:02X}')
        if frame_id == FRAME_ID_LAST:
            n = infer_n_from_last_seq(seq)
            already = seq * DATA_CHUNK
            if n:
                need = n * n
                valid = need - already
                pad = DATA_CHUNK - valid
                chunk = take_row_major_chunk(arr, already, valid)[:valid] + bytes(pad)
                mismatch = (
                    f'；注意地检推算 {n}×{n} 与模拟器 {w}×{h} 不一致，会错位'
                    if n != w or n != h
                    else ''
                )
                text = (
                    f'{head}{kind} seq={seq} 图像序号={image_no} → 按行 {w}×{h} '
                    f'推算 {n}×{n} (n×n={need} > 已发送 {already})，'
                    f'尾帧有效 {valid} 字节、填充 {pad} 字节，已应答{mismatch}'
                )
            else:
                chunk = take_row_major_chunk(arr, 0)
                text = (
                    f'{head}{kind} seq={seq} 图像序号={image_no} → 未能推算分辨率'
                    f'（需 n×n > {already}），从数据偏移 0 按行取满 {DATA_CHUNK} 字节，已应答'
                )
        else:
            chunk = take_row_major_chunk(arr, seq * DATA_CHUNK)
            text = (
                f'{head}{kind} seq={seq} 图像序号={image_no} → '
                f'按行 {w}×{h} 满数据 {DATA_CHUNK} 字节，已应答'
            )
        try:
            self._ser.write(build_response(frame_id, seq, image_no, chunk))
        except Exception as e:
            self.progress.emit(f'{head}应答发送失败: {e}，串口保持连接')
            if frame_id == FRAME_ID_LAST:
                self._xfer.on_last_frame()
            return
        self.progress.emit(text)
        if frame_id == FRAME_ID_LAST:
            self._xfer.on_last_frame()


class CameraImageSerialSim(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('相机传图串口模拟器')
        self.resize(720, 640)

        self._ser: serial.Serial | None = None
        self._worker: SerialWorker | None = None
        self._src_arr: np.ndarray | None = None
        self._arr: np.ndarray | None = None
        self._pending_arr: np.ndarray | None = None
        self._pending_source = ''
        self._preview_arr: np.ndarray | None = None
        self._wh = (0, 0)
        self._lock = threading.Lock()
        self._xfer = TransferState()

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        row1 = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(160)
        self.refresh_btn = QPushButton('刷新')
        self.baud_combo = QComboBox()
        for b in BAUDRATES:
            self.baud_combo.addItem(str(b), b)
        self.connect_btn = QPushButton('连接')
        row1.addWidget(QLabel('串口'))
        row1.addWidget(self.port_combo, 1)
        row1.addWidget(self.refresh_btn)
        row1.addWidget(QLabel('波特率'))
        row1.addWidget(self.baud_combo)
        row1.addWidget(self.connect_btn)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.file_btn = QPushButton('选择文件')
        self.gen_btn = QPushButton('生成图片')
        self.res_combo = QComboBox()
        for name in RESOLUTIONS:
            self.res_combo.addItem(name)
        row2.addWidget(self.file_btn)
        row2.addWidget(self.gen_btn)
        row2.addWidget(QLabel('分辨率'))
        row2.addWidget(self.res_combo)
        row2.addStretch(1)
        layout.addLayout(row2)

        self.hint_text = QTextEdit()
        self.hint_text.setReadOnly(True)
        self.hint_text.setAcceptRichText(False)
        self.hint_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.hint_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.hint_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.hint_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        fm = self.hint_text.fontMetrics()
        frame = self.hint_text.frameWidth() * 2
        doc_m = int(self.hint_text.document().documentMargin()) * 2
        two_line_h = fm.lineSpacing() * 2 + frame + doc_m + 10
        self.hint_text.setFixedHeight(two_line_h)
        self.hint_text.setStyleSheet(
            'padding:2px 6px; background:#f5f5f5; border:1px solid #d0d0d0; color:#222;'
        )
        self.hint_text.setPlainText('未连接')
        layout.addWidget(self.hint_text)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(360)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview.setStyleSheet('background:#9e9e9e; color:#333;')
        self.preview.setText('无预览')
        layout.addWidget(self.preview, 1)

        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn.clicked.connect(self.toggle_connect)
        self.file_btn.clicked.connect(self.choose_file)
        self.gen_btn.clicked.connect(self.generate_image)
        self.res_combo.currentTextChanged.connect(self._on_res_changed)

        self.refresh_ports()
        self.generate_image()
        self._pending_timer = QTimer(self)
        self._pending_timer.setInterval(50)
        self._pending_timer.timeout.connect(self._poll_pending)
        self._pending_timer.start()

    def refresh_ports(self) -> None:
        current = self.port_combo.currentData() or ''
        self.port_combo.clear()
        ports = []
        for p in list_ports.comports():
            label = p.device
            if p.description:
                label = f'{p.device}  {p.description}'
            ports.append((p.device, label))
        if not ports:
            self.port_combo.addItem('(无串口)', '')
        else:
            for device, label in ports:
                self.port_combo.addItem(label, device)
            idx = self.port_combo.findData(current)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)

    def _set_connected_ui(self, connected: bool) -> None:
        self.port_combo.setEnabled(not connected)
        self.baud_combo.setEnabled(not connected)
        self.connect_btn.setText('关闭' if connected else '连接')

    def toggle_connect(self) -> None:
        if self._ser and self._ser.is_open:
            self.disconnect_serial()
            return
        port = self.port_combo.currentData() or ''
        if not port:
            QMessageBox.warning(self, '提示', '请选择串口')
            return
        baud = int(self.baud_combo.currentData() or BAUDRATES[0])
        try:
            self._ser = serial.Serial(
                port=port,
                baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_ODD,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.05,
                write_timeout=5.0,
            )
        except Exception as e:
            self._ser = None
            QMessageBox.critical(self, '打开失败', str(e))
            return
        clear_port_buffers(self._ser)
        self._xfer.on_last_frame()
        self._worker = SerialWorker(self._ser, self._lock, self._copy_arr, self._xfer)
        self._worker.progress.connect(self._on_progress)
        self._worker.failed.connect(self._on_serial_error)
        self._worker.start()
        self._set_connected_ui(True)
        self._set_hint('等待传图请求')

    def disconnect_serial(self) -> None:
        worker = self._worker
        self._worker = None
        if worker:
            worker.stop()
        ser = self._ser
        self._ser = None
        if ser:
            try:
                ser.close()
            except Exception:
                pass
        if worker:
            worker.wait(1500)
            try:
                worker.progress.disconnect(self._on_progress)
            except Exception:
                pass
            try:
                worker.failed.disconnect(self._on_serial_error)
            except Exception:
                pass
        self._xfer.on_last_frame()
        self._install_pending()
        self._set_connected_ui(False)
        self._set_hint('未连接')

    def _copy_arr(self) -> np.ndarray | None:
        if self._arr is None:
            return None
        return self._arr.copy()

    def _set_hint(self, text: str) -> None:
        self.hint_text.setPlainText(text)
        self.hint_text.moveCursor(QTextCursor.MoveOperation.Start)

    def is_transferring(self) -> bool:
        return self._xfer.is_transferring()

    def _on_progress(self, text: str) -> None:
        extra = ''
        if self.is_transferring() and self._pending_arr is not None:
            extra = '；已缓存新图，等尾帧后再替换预览'
        self._set_hint(text + extra)

    def _poll_pending(self) -> None:
        if self._pending_arr is None:
            return
        if self.is_transferring():
            return
        self._install_pending()

    def _install_pending(self) -> None:
        arr = self._pending_arr
        source = self._pending_source
        if arr is None:
            return
        if self.is_transferring():
            return
        self._pending_arr = None
        self._pending_source = ''
        h, w = int(arr.shape[0]), int(arr.shape[1])
        with self._lock:
            self._arr = arr
            self._wh = (w, h)
        self._preview_arr = arr
        self._paint_preview(arr)
        self._set_hint(f'已收到尾帧，传输结束，已切换到缓存图 {source}，{w}×{h}')

    def _on_serial_error(self, text: str) -> None:
        self._set_hint(f'串口错误: {text}')
        ser = self._ser
        dead = True
        try:
            dead = ser is None or not ser.is_open
        except Exception:
            dead = True
        if dead:
            self.disconnect_serial()

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, '选择图片', '', '图片 (*.png *.bmp);;PNG (*.png);;BMP (*.bmp)'
        )
        if not path:
            return
        qimg = QImage(path)
        if qimg.isNull():
            QMessageBox.warning(self, '读取失败', '无法打开图片（请确认是有效的 PNG 或 BMP）')
            return
        try:
            arr = qimage_to_gray_array(qimg)
        except Exception as e:
            QMessageBox.warning(self, '读取失败', str(e))
            return
        self._src_arr = arr
        self._rebuild_send(source=Path(path).name)

    def generate_image(self) -> None:
        name = self.res_combo.currentText()
        w, h = RESOLUTIONS.get(name, (400, 400))
        arr = np.random.randint(200, 256, size=(h, w), dtype=np.uint8)
        n_min = 10
        n_max = min(min(w, h) // 2, 50)
        if n_max < n_min:
            n_max = n_min
        n = random.randint(n_min, n_max)
        x = random.randint(0, w - n)
        y = random.randint(0, h - n)
        arr[y : y + n, x : x + n] = 0
        self._src_arr = arr
        self._rebuild_send(source=f'生成 {name} 黑块 {n}×{n} @({x},{y})')

    def _on_res_changed(self, _name: str = '') -> None:
        if self._src_arr is None:
            return
        self._rebuild_send(source='分辨率')

    def _rebuild_send(self, source: str) -> None:
        if self._src_arr is None:
            return
        w, h = RESOLUTIONS.get(self.res_combo.currentText(), (400, 400))
        try:
            arr = scale_gray_array(self._src_arr, w, h)
        except Exception as e:
            QMessageBox.warning(self, '缩放失败', str(e))
            return
        arr = np.ascontiguousarray(arr, dtype=np.uint8)
        src_h, src_w = int(self._src_arr.shape[0]), int(self._src_arr.shape[1])
        extra = '' if (src_w, src_h) == (w, h) else f'（源图 {src_w}×{src_h} 已缩放到发送尺寸）'
        if self.is_transferring():
            self._pending_arr = arr
            self._pending_source = source
            self._set_hint(
                f'传输中，已缓存 {source}，{w}×{h}，不更新预览{extra}'
            )
            return
        self._pending_arr = None
        self._pending_source = ''
        with self._lock:
            self._arr = arr
            self._wh = (w, h)
        self._preview_arr = arr
        self._paint_preview(arr)
        self._set_hint(f'已加载 {source}，按行发送 {w}×{h}，{arr.size} 字节{extra}')

    def _refresh_preview(self) -> None:
        arr = self._preview_arr
        if arr is not None and arr.size:
            self._paint_preview(arr)

    def _paint_preview(self, arr: np.ndarray) -> None:
        h, w = arr.shape
        qimg = QImage(arr.tobytes(), w, h, w, QImage.Format.Format_Grayscale8).copy()
        pix = QPixmap.fromImage(qimg)
        box = self.preview.contentsRect().size()
        if box.width() < 16 or box.height() < 16:
            box = self.preview.size()
        if box.width() >= 16 and box.height() >= 16:
            pix = pix.scaled(
                box,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        self.preview.setPixmap(pix)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._refresh_preview()
        QTimer.singleShot(0, self._refresh_preview)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh_preview()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.disconnect_serial()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    win = CameraImageSerialSim()
    win.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
