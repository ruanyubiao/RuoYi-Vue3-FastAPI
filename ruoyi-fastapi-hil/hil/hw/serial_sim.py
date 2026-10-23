"""串口 / RS422 模拟器（测试机侧扮演单板/相机）：按 hil/protocol/serial_device 的模型拆帧、回包、周期推遥测。"""
from __future__ import annotations

from hil.config import CONFIG, HILConfig
from hil.hw.base import DeviceSim
from hil.hw.reply import ReplyMap
from hil.protocol.serial_device import SerialDeviceModel, make_serial_device
from hil.samples import bytes_to_hex


def _short(b: bytes, n: int = 48) -> str:
    h = bytes_to_hex(b[:n])
    return h + (f' ...(+{len(b) - n}B)' if len(b) > n else '')


class SerialSim(DeviceSim):
    def __init__(self, key: str, port: str | None = None, cfg: HILConfig = CONFIG, dry_run: bool | None = None,
                 model: SerialDeviceModel | None = None, reply_map: ReplyMap | None = None) -> None:
        super().__init__()
        self.key = key
        self.cfg = cfg
        self.port = port if port is not None else cfg.serial_port_for(key)
        self.dry_run = (not self.port) if dry_run is None else dry_run
        self.model = model or make_serial_device(key)
        self.model.extra_rules = (reply_map or ReplyMap.load(cfg.reply_map_path)).for_target(key)
        self.name = f'SERIAL:{key}:{self.port or "dry-run"}'
        self.ser = None
        self.sent: list[bytes] = []
        self.raw_chunks: list[bytes] = []

    def open(self) -> None:
        if self.dry_run:
            self.log('dry-run 模式（设置 HIL_SERIAL_<KEY>=COMx 才打开真实串口）')
            return
        import serial

        params = self.cfg.serial_params(self.key)
        self.ser = serial.Serial(self.port, timeout=0.02, **params)
        self.log(f'opened {params}')

    def close(self) -> None:
        if self.ser is not None:
            self.ser.close()
            self.ser = None

    def send_frame(self, frame: bytes) -> None:
        self.sent.append(bytes(frame))
        if self.dry_run:
            self.log(f'[dry-run] TX [{_short(frame)}]')
            return
        self.ser.write(frame)

    def handle_bytes(self, data: bytes, idle: bool = True) -> list[bytes]:
        before = len(self.model.received)
        self.raw_chunks.append(bytes(data))
        replies = self.model.feed(data, idle=idle)
        for fr in self.model.received[before:]:
            self.log(f'RX [{_short(fr)}]')
            self._emit_rx(fr)
        for r in replies:
            self.send_frame(r)
        return replies

    def rx_loop(self) -> None:
        if self.dry_run:
            return
        while not self._stop.is_set():
            try:
                chunk = self.ser.read(4096)
            except Exception as exc:  # noqa: BLE001
                self.log(f'read 异常: {exc}')
                self._stop.wait(0.5)
                continue
            self.handle_bytes(chunk, idle=not chunk)

    def start_telemetry(self, period_s: float | None = None) -> None:
        self.schedule_telemetry(period_s or self.cfg.tm_period_s, self.model.telemetry)
