"""CAN 模拟器（测试机侧扮演载荷）：gpcan 真实收发；未选被测 CAN 设备（HIL_CAN_TARGET）时 dry-run。

每条线缆一个实例：cable=a → 测试机 ch0，cable=b → ch1（hil.local.json 可改），两路都收发、都回遥测。

收：CanSdkClient.recv → CanDeviceModel.feed（gpcan ProtocolParser 拼帧）→ 按协议回遥测
发：CanSdkClient.send(id, data, len)
"""
from __future__ import annotations

from hil.config import CONFIG, CanChannel, HILConfig
from hil.hw.base import DeviceSim
from hil.hw.reply import ReplyMap
from hil.protocol.can_device import CanDeviceModel, gpcan_available
from hil.samples import bytes_to_hex


class CanSim(DeviceSim):
    def __init__(self, family: str, cfg: HILConfig = CONFIG, channel: CanChannel | None = None,
                 dry_run: bool | None = None, reply_map: ReplyMap | None = None, cable: str = 'a') -> None:
        super().__init__()
        self.family = family
        self.cable = cable
        self.cfg = cfg
        self.channel = channel or cfg.can_channel(family, cable)
        self.name = f'CAN:{family}:{cable.upper()}:ch{self.channel.can_index}'
        self.dry_run = (not cfg.can_enable) if dry_run is None else dry_run
        ok, err = gpcan_available()
        if not ok:
            raise RuntimeError(f'gpcan 不可用（pip install -e E:\\plat\\pygpcan）: {err}')
        self.model = CanDeviceModel(family)
        self.raw_frames: list[tuple[int, bytes]] = []
        self.custom = (reply_map or ReplyMap.load(cfg.reply_map_path)).for_target(family)
        self.client = None
        self.sent: list[tuple[int, bytes]] = []

    def open(self) -> None:
        if self.dry_run:
            self.log('dry-run 模式（选了被测 CAN 设备 HIL_CAN_TARGET 才打开真实 CAN）')
            return
        import gpcan

        ch = self.channel
        param = gpcan.CanCardParam(n_can_index=ch.can_index, n_baud_rate=ch.baud_kbps, n_dev_index=ch.dev_index,
                                   n_can_timeout_read_ms=50)
        self.client = gpcan.CanSdkClient(ch.vendor, param)
        ok = int(gpcan.CanRetCode.CAN_RET_CODE_OK)
        # 与后端 can_collector 一致：先 init 再 open
        if self.client.init_can() != ok:
            raise RuntimeError(f'CAN init 失败 vendor={ch.vendor} dev={ch.dev_index} ch={ch.can_index}: {self.client.get_last_error()}')
        if self.client.open_can() != ok:
            err = self.client.get_last_error()
            self.client.deinit_can()
            raise RuntimeError(f'CAN open 失败 vendor={ch.vendor} dev={ch.dev_index} ch={ch.can_index}: {err}')
        self.log(f'opened vendor={ch.vendor} dev={ch.dev_index} ch={ch.can_index} {ch.baud_kbps}kbps')

    def close(self) -> None:
        if self.client is not None:
            try:
                self.client.close_can()
                self.client.deinit_can()
            finally:
                self.client = None

    def send_frame(self, frame: tuple[int, bytes]) -> None:
        can_id, data = frame
        self.sent.append((can_id, bytes(data)))
        if self.dry_run:
            self.log(f'[dry-run] TX id=0x{can_id:03X} [{bytes_to_hex(data)}]')
            return
        self.client.send(can_id, bytes(data), len(data))

    def handle_frames(self, frames: list[tuple[int, bytes]]) -> list[tuple[int, bytes]]:
        """Receive hardware frames: reassemble, log, reply TM (dry-run included)."""
        self.raw_frames.extend(frames)
        before = len(self.model.events)
        replies = self.model.feed(frames)
        for ev in self.model.events[before:]:
            self.log(f'RX {ev.kind} id=0x{ev.can_id:03X} [{bytes_to_hex(ev.payload)}] {ev.meta or ""}')
            self._emit_rx(ev)
            for r in self.custom:
                if ev.payload.startswith(r['_prefix']):
                    cid = r.get('can_id')
                    cid = int(cid, 0) if isinstance(cid, str) else (cid if cid is not None else ev.can_id)
                    replies += [(cid, r['_reply'][i:i + 8]) for i in range(0, len(r['_reply']), 8)]
        for fr in replies:
            self.send_frame(fr)
        return replies

    def rx_loop(self) -> None:
        if self.dry_run:
            return
        while not self._stop.is_set():
            try:
                objs = self.client.recv(64)
            except Exception as exc:  # noqa: BLE001
                self.log(f'recv 异常: {exc}')
                self._stop.wait(0.5)
                continue
            if not objs:
                self._stop.wait(0.005)
                continue
            self.handle_frames([(int(o.un_id), bytes(o.str_data)[: int(o.un_data_len)]) for o in objs])

    def start_push(self, period_s: float) -> None:
        """可选：不等请求，按周期主动推遥测（默认不用，三条总线都是请求-应答）。"""
        self.schedule_telemetry(period_s, self.model.periodic_frames)
