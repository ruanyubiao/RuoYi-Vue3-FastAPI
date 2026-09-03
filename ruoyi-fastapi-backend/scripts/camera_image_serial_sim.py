"""相机传图串口模拟器（SC-LINK41EP 图像下传 D6）。

自包含单文件脚本，不 import 项目内任何模块。用虚拟串口对与地检平台「图像串口」
相连后，只应答传图请求帧（10 字节），其它数据丢弃；按序号切本地图像并回 266 字节应答。

v16 / v17 收请求逻辑相同；差异仅在应答：v16 长度固定 0x0101，v17 为有效字节 L+1。

用法:
    pip install PyQt6 pyserial numpy
    python camera_image_serial_sim.py

串口参数与平台相机图像口一致：8 数据位 / 奇校验 / 1 停止位。
波特率仅 2000000、11000000。
"""

from __future__ import annotations

import math
import random
import sys
import threading
import time

import numpy as np
import serial
from serial.tools import list_ports

try:
    from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
    from PyQt6.QtGui import QImage, QPixmap, QTextCursor
    from PyQt6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QSizePolicy,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise SystemExit('请先安装 PyQt6：pip install PyQt6') from exc

# ---- D6 协议（与地检平台 camera_image_d6 一致，内联副本）----
FRAME_HEADER = bytes([0xEB, 0x90])
FRAME_TYPE = 0xD6
REQ_SIZE = 10
RESP_SIZE = 266
DATA_CHUNK = 256
REQ_LEN = 0x0001
RESP_LEN = 0x0101

# 帧标识字节位：bit2 首帧 / bit0 尾帧 / bit1 中间帧；判断顺序 首→尾→中
_FRAME_ID_BIT_FIRST = 2
_FRAME_ID_BIT_MID = 1
_FRAME_ID_BIT_LAST = 0

_FRAME_ID_LABEL = {
    'first': '首帧',
    'mid': '中间帧',
    'last': '尾帧',
}


def frame_id_is_first(frame_id: int) -> bool:
    return bool((int(frame_id) >> _FRAME_ID_BIT_FIRST) & 1)


def frame_id_is_last(frame_id: int) -> bool:
    return bool((int(frame_id) >> _FRAME_ID_BIT_LAST) & 1)


def frame_id_is_mid(frame_id: int) -> bool:
    return bool((int(frame_id) >> _FRAME_ID_BIT_MID) & 1)


def classify_frame_id(frame_id: int) -> str:
    fid = int(frame_id) & 0xFF
    if frame_id_is_first(fid):
        return 'first'
    if frame_id_is_last(fid):
        return 'last'
    if frame_id_is_mid(fid):
        return 'mid'
    return 'unknown'


def frame_id_is_valid(frame_id: int) -> bool:
    return classify_frame_id(frame_id) != 'unknown'


def _frame_id_label(frame_id: int) -> str:
    kind = classify_frame_id(frame_id)
    return _FRAME_ID_LABEL.get(kind, f'0x{frame_id:02X}')


RESOLUTIONS = {
    '400×400': (400, 400),
    '256×256': (256, 256),
    '128×128': (128, 128),
    '64×64': (64, 64),
}
# v16 下拉 ↔ v17 输入框可无损互转的边长
STANDARD_RES_SIDES = frozenset((64, 128, 256, 400))
BAUDRATES = [2_000_000, 11_000_000]
PREVIEW_BOX = 400


def label_to_side(label: str) -> int | None:
    """v16 下拉文案 → 边长；未知返回 None。"""
    wh = RESOLUTIONS.get(str(label or '').strip())
    return int(wh[0]) if wh else None


def side_to_label(side: int) -> str | None:
    """标准边长 → v16 下拉文案；非 64/128/256/400 返回 None。"""
    n = int(side)
    if n not in STANDARD_RES_SIDES:
        return None
    return f'{n}×{n}'


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def take_row_major_chunk(arr: np.ndarray, start: int, count: int = DATA_CHUNK) -> bytes:
    """按行取连续像素：位置 i 对应 y,x = divmod(i, width)，再切 count 字节。"""
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
    """解析 10 字节传图请求，返回 (frame_id, seq, image_no)。v16/v17 相同。"""
    if len(buf) < REQ_SIZE:
        return None
    if buf[0:2] != FRAME_HEADER or buf[2] != FRAME_TYPE:
        return None
    frame_id = buf[3]
    if not frame_id_is_valid(frame_id):
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
    """v16：长度字段固定 0x0101，数据区恒 256 字节。"""
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


def build_response_v17(frame_id: int, seq: int, image_no: int, chunk: bytes) -> bytes:
    """v17：字节 4-5 为有效长度编码 L，有效字节 = L+1。"""
    valid = len(chunk)
    if valid < 1 or valid > DATA_CHUNK:
        raise ValueError(f'v17 chunk valid length must be 1..{DATA_CHUNK}')
    padded = chunk + bytes(DATA_CHUNK - valid)
    l = (valid - 1) & 0xFFFF
    body = bytes(
        [
            FRAME_TYPE,
            frame_id & 0xFF,
            (l >> 8) & 0xFF,
            l & 0xFF,
            (seq >> 8) & 0xFF,
            seq & 0xFF,
            image_no & 0xFF,
        ]
    ) + padded
    return FRAME_HEADER + body + bytes([checksum(body)])


def infer_n_from_last_seq(seq: int) -> int | None:
    """尾帧反推正方形边长 n。"""
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
    if not frame_id_is_valid(buf[3]):
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


def consume_rx(buf: bytearray) -> list[tuple]:
    """从接收缓存取出请求事件。v16/v17 同一套收包。

    返回 ('ok', (frame_id, seq, image_no), raw10) 或 ('bad', raw10, why)。
    回环的 266 字节应答丢弃；半截帧留在 buf。
    """
    events: list[tuple] = []
    while buf:
        req_off = find_valid_request_offset(bytes(buf))
        if req_off == 0:
            raw = bytes(buf[:REQ_SIZE])
            parsed = parse_request(raw)
            del buf[:REQ_SIZE]
            events.append(('ok', parsed, raw))
            continue

        if req_off > 0:
            if len(buf) >= RESP_SIZE and buf[0:3] == bytes([FRAME_HEADER[0], FRAME_HEADER[1], FRAME_TYPE]):
                del buf[:RESP_SIZE]
                continue
            del buf[:req_off]
            continue

        if len(buf) >= RESP_SIZE and buf[0:3] == bytes([FRAME_HEADER[0], FRAME_HEADER[1], FRAME_TYPE]):
            del buf[:RESP_SIZE]
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
        if len(buf) < RESP_SIZE:
            return events
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
    regen_on_first = pyqtSignal()

    def __init__(
        self,
        ser: serial.Serial,
        pixels_lock: threading.Lock,
        get_arr,
        xfer: TransferState,
        get_protocol,
        get_regen_on_first,
    ) -> None:
        super().__init__()
        self._ser = ser
        self._lock = pixels_lock
        self._get_arr = get_arr
        self._xfer = xfer
        self._get_protocol = get_protocol
        self._get_regen_on_first = get_regen_on_first
        self._running = True
        self._regen_done = threading.Event()

    def stop(self) -> None:
        self._running = False
        self._regen_done.set()

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

    def _payload_for_request(self, arr: np.ndarray, frame_id: int, seq: int) -> bytes:
        """按序号取像素；尾帧按剩余有效长度截取（v17 组帧用）。"""
        if frame_id_is_last(frame_id):
            already = seq * DATA_CHUNK
            n_infer = infer_n_from_last_seq(seq)
            if n_infer:
                valid = n_infer * n_infer - already
                return take_row_major_chunk(arr, already, valid)[:valid]
            return take_row_major_chunk(arr, already, DATA_CHUNK)
        return take_row_major_chunk(arr, seq * DATA_CHUNK, DATA_CHUNK)

    def _sync_regen_on_first(self) -> bool:
        """主线程生成并刷新预览后再继续应答。返回是否已刷新。"""
        try:
            want = bool(self._get_regen_on_first())
        except Exception:
            want = False
        if not want:
            return False
        self._regen_done.clear()
        self.regen_on_first.emit()
        self._regen_done.wait(timeout=2.0)
        return True

    def mark_regen_done(self) -> None:
        self._regen_done.set()

    def _reply(self, frame_id: int, seq: int, image_no: int, raw: bytes = b'') -> None:
        head = f'接收指令正确  {fmt_hex(raw)}  ' if raw else '接收指令正确  '
        refreshed = False
        if frame_id_is_first(frame_id):
            refreshed = self._sync_regen_on_first()
            with self._lock:
                snapped = self._get_arr()
            self._xfer.on_last_frame()
            arr = self._xfer.on_request(snapped)
        else:
            arr = self._xfer.current_pixels()
            if arr is None:
                with self._lock:
                    snapped = self._get_arr()
                arr = self._xfer.on_request(snapped)
        if arr is None:
            self.progress.emit(f'{head}但还没有图像数据，已丢弃')
            return
        h, w = int(arr.shape[0]), int(arr.shape[1])
        kind = _frame_id_label(frame_id)
        payload = self._payload_for_request(arr, frame_id, seq)
        regen_note = '已按首帧刷新图片，' if refreshed else ''
        if frame_id_is_last(frame_id):
            n = infer_n_from_last_seq(seq)
            already = seq * DATA_CHUNK
            if n:
                text = (
                    f'{head}{kind} seq={seq} 图像序号={image_no} → {regen_note}按行 {w}×{h} '
                    f'推算 {n}×{n}，尾帧有效 {len(payload)} 字节，已应答'
                )
            else:
                text = (
                    f'{head}{kind} seq={seq} 图像序号={image_no} → {regen_note}未能推算分辨率'
                    f'（需 n×n > {already}），满 {DATA_CHUNK} 字节，已应答'
                )
        else:
            text = (
                f'{head}{kind} seq={seq} 图像序号={image_no} → {regen_note}'
                f'按行 {w}×{h} 满数据 {len(payload)} 字节，已应答'
            )
        try:
            proto = self._get_protocol()
            if proto == 'v17':
                resp = build_response_v17(frame_id, seq, image_no, payload)
            else:
                resp = build_response(frame_id, seq, image_no, payload)
            self._ser.write(resp)
        except Exception as e:
            self.progress.emit(f'{head}应答发送失败: {e}，串口保持连接')
            if frame_id_is_last(frame_id):
                self._xfer.on_last_frame()
            return
        self.progress.emit(text)
        if frame_id_is_last(frame_id):
            self._xfer.on_last_frame()


class CameraImageSerialSim(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('相机传图串口模拟器')
        self.resize(860, 560)

        self._ser: serial.Serial | None = None
        self._worker: SerialWorker | None = None
        self._arr: np.ndarray | None = None
        self._preview_prev_arr: np.ndarray | None = None
        self._preview_curr_arr: np.ndarray | None = None
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
        self.gen_btn = QPushButton('生成图片')
        self.ver_combo = QComboBox()
        self.ver_combo.addItem('v16')
        self.ver_combo.addItem('v17')
        self.res_combo = QComboBox()
        for name in RESOLUTIONS:
            self.res_combo.addItem(name)
        self.res_spin = QSpinBox()
        self.res_spin.setRange(8, 400)
        self.res_spin.setSingleStep(8)
        self.res_spin.setValue(400)
        # 关闭键盘跟踪：逐字输入不刷图，回车/失焦或点步进箭头时才 valueChanged
        self.res_spin.setKeyboardTracking(False)
        self.res_spin.setVisible(False)

        row2.addWidget(QLabel('版本'))
        row2.addWidget(self.ver_combo)
        row2.addWidget(QLabel('分辨率'))
        row2.addWidget(self.res_combo)
        row2.addWidget(self.res_spin)
        row2.addWidget(self.gen_btn)
        self.regen_check = QCheckBox('收到首帧后刷新图片')
        self.regen_check.setChecked(True)
        row2.addWidget(self.regen_check)
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

        preview_row = QHBoxLayout()
        preview_row.setSpacing(12)
        prev_col, self.preview_prev = self._make_preview_pane('上一张')
        curr_col, self.preview_curr = self._make_preview_pane('当前图像')
        preview_row.addStretch(1)
        preview_row.addWidget(prev_col)
        preview_row.addWidget(curr_col)
        preview_row.addStretch(1)
        layout.addLayout(preview_row)
        layout.addStretch(1)

        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn.clicked.connect(self.toggle_connect)
        self.gen_btn.clicked.connect(self.generate_image)
        self.res_combo.currentTextChanged.connect(self._on_res_changed)
        self.res_spin.valueChanged.connect(self._on_res_changed)
        self.ver_combo.currentTextChanged.connect(self._on_ver_changed)

        self.refresh_ports()
        self.generate_image()

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
        self._worker = SerialWorker(
            self._ser,
            self._lock,
            self._copy_arr,
            self._xfer,
            self._protocol,
            self._regen_on_first_enabled,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.failed.connect(self._on_serial_error)
        self._worker.regen_on_first.connect(self._on_first_frame_regen)
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
            try:
                worker.regen_on_first.disconnect(self._on_first_frame_regen)
            except Exception:
                pass
        self._xfer.on_last_frame()
        self._set_connected_ui(False)
        self._set_hint('未连接')

    def _copy_arr(self) -> np.ndarray | None:
        if self._arr is None:
            return None
        return self._arr.copy()

    def _set_hint(self, text: str) -> None:
        self.hint_text.setPlainText(text)
        self.hint_text.moveCursor(QTextCursor.MoveOperation.Start)

    def _on_progress(self, text: str) -> None:
        self._set_hint(text)

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

    def _protocol(self) -> str:
        return str(self.ver_combo.currentText() or 'v16')

    def _regen_on_first_enabled(self) -> bool:
        return bool(self.regen_check.isChecked())

    def _on_first_frame_regen(self) -> None:
        try:
            self.generate_image(force=True, silent=True)
            QApplication.processEvents()
        finally:
            worker = self._worker
            if worker is not None:
                worker.mark_regen_done()

    def _current_wh(self) -> tuple[int, int]:
        if self._protocol() == 'v17':
            n = int(self.res_spin.value())
            return n, n
        return RESOLUTIONS.get(self.res_combo.currentText(), (400, 400))

    def _on_ver_changed(self, ver: str) -> None:
        """v16↔v17：标准分辨率互转且不刷图；v17 非标准边长则保留下拉原值并刷一次图。"""
        v17 = ver == 'v17'
        need_refresh = False
        self.res_combo.blockSignals(True)
        self.res_spin.blockSignals(True)
        try:
            if v17:
                # 下拉 → 输入框（下拉项必为标准边长）
                side = label_to_side(self.res_combo.currentText()) or 400
                self.res_spin.setValue(side)
            else:
                # 输入框 → 下拉：仅标准边长互转；否则下拉不动并刷新图片
                label = side_to_label(int(self.res_spin.value()))
                if label is not None:
                    idx = self.res_combo.findText(label)
                    if idx >= 0:
                        self.res_combo.setCurrentIndex(idx)
                else:
                    need_refresh = True
            self.res_combo.setVisible(not v17)
            self.res_spin.setVisible(v17)
        finally:
            self.res_combo.blockSignals(False)
            self.res_spin.blockSignals(False)
        if need_refresh:
            self.generate_image()

    def generate_image(self, *_args, force: bool = False, silent: bool = False) -> None:
        w, h = self._current_wh()
        name = f'{w}×{h}' if self._protocol() == 'v17' else self.res_combo.currentText()
        arr = np.random.randint(200, 256, size=(h, w), dtype=np.uint8)
        n_min = 10
        n_max = min(min(w, h) // 2, 50)
        if n_max < n_min:
            n_max = n_min
        n = random.randint(n_min, n_max)
        x = random.randint(0, w - n)
        y = random.randint(0, h - n)
        arr[y : y + n, x : x + n] = 0
        arr = np.ascontiguousarray(arr, dtype=np.uint8)
        if not force and self._xfer.is_transferring():
            self._set_hint(f'传输中，生成的 {name} 未生效，等尾帧后再点生成')
            return
        with self._lock:
            self._arr = arr
        self._push_preview(arr)
        if not silent:
            self._set_hint(f'已生成 {name} 黑块 {n}×{n} @({x},{y})，{arr.size} 字节')

    def _on_res_changed(self, _name: str = '') -> None:
        self.generate_image()

    def _make_preview_pane(self, title: str) -> tuple[QWidget, QLabel]:
        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        cap = QLabel(title)
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box = QLabel()
        box.setFixedSize(PREVIEW_BOX, PREVIEW_BOX)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setStyleSheet('background:#9e9e9e; color:#333;')
        box.setText('无预览')
        lay.addWidget(cap)
        lay.addWidget(box)
        return col, box

    def _push_preview(self, arr: np.ndarray) -> None:
        """刷新预览：左=原右图，右=最新；第一张则左右相同。"""
        if self._preview_curr_arr is None:
            self._preview_prev_arr = arr
            self._preview_curr_arr = arr
        else:
            self._preview_prev_arr = self._preview_curr_arr
            self._preview_curr_arr = arr
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        self._paint_one(self.preview_prev, self._preview_prev_arr)
        self._paint_one(self.preview_curr, self._preview_curr_arr)

    def _arr_to_pixmap(self, arr: np.ndarray) -> QPixmap:
        h, w = int(arr.shape[0]), int(arr.shape[1])
        qimg = QImage(arr.tobytes(), w, h, w, QImage.Format.Format_Grayscale8).copy()
        pix = QPixmap.fromImage(qimg)
        if w > PREVIEW_BOX or h > PREVIEW_BOX:
            pix = pix.scaled(
                PREVIEW_BOX,
                PREVIEW_BOX,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        return pix

    def _paint_one(self, label: QLabel, arr: np.ndarray | None) -> None:
        if arr is None or arr.size == 0:
            label.clear()
            label.setText('无预览')
            return
        label.setText('')
        label.setPixmap(self._arr_to_pixmap(arr))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._refresh_preview()
        QTimer.singleShot(0, self._refresh_preview)

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
