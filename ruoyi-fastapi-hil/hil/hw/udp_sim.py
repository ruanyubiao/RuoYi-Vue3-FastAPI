"""UDP 模拟器（测试机侧扮演地检板 xl_udp_dj）：绑定本地端口收包，向工控机周期推工程遥测（表格 4，844B）。"""
from __future__ import annotations

import socket

from hil.config import CONFIG, HILConfig
from hil.hw.base import DeviceSim
from hil.hw.reply import ReplyMap
from hil.samples import bytes_to_hex, get_bytes


class UdpSim(DeviceSim):
    def __init__(self, key: str = 'xl_udp_dj', cfg: HILConfig = CONFIG, bind: tuple[str, int] | None = None,
                 peer: tuple[str, int] | None = None, reply_map: ReplyMap | None = None) -> None:
        super().__init__()
        self.key = key
        self.cfg = cfg
        dbind, dpeer = cfg.udp_addrs(key)
        self.bind = bind or dbind
        self.peer = peer or dpeer
        self.name = f'UDP:{key}'
        self.custom = (reply_map or ReplyMap.load(cfg.reply_map_path)).for_target(key)
        self.tm = get_bytes('eng_board_dj')
        self.sock: socket.socket | None = None
        self.sent: list[bytes] = []

    def open(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(self.bind)
        self.sock.settimeout(0.2)
        self.bind = self.sock.getsockname()
        self.log(f'bind {self.bind} -> peer {self.peer}')

    def close(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None

    def send_frame(self, frame: bytes, addr: tuple[str, int] | None = None) -> None:
        self.sock.sendto(frame, addr or self.peer)
        self.sent.append(bytes(frame))

    def rx_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                return
            self.log(f'RX <- {addr} [{bytes_to_hex(data[:32])}{" ..." if len(data) > 32 else ""}]')
            self._emit_rx((addr, data))
            for r in self.custom:
                if data.startswith(r['_prefix']):
                    self.send_frame(r['_reply'], addr)

    def start_telemetry(self, period_s: float | None = None) -> None:
        self.schedule_telemetry(period_s or self.cfg.tm_period_s, lambda: [self.tm])
