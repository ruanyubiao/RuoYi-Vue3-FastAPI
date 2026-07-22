"""
串口采集进程：打开串口 + 按会话挂载收流插件。

图像拉流等业务在 collectors/plugins 中实现，本类不堆功能开关。
"""

from __future__ import annotations

from typing import Any

from module_payload.collectors.base_collector import BaseCollector
from module_payload.collectors.plugins.base import SerialPluginContext
from module_payload.constants import SRC_KIND_SERIAL


class SerialCollector(BaseCollector):
    def __init__(self, device_id: str, config: dict[str, Any]) -> None:
        super().__init__(device_id, config)
        self._ser = None
        self._plugin = None
        self._plugin_id: str | None = None
        self._cached_source: str | None = None

    def setup(self) -> bool:
        import serial

        port = self.config.get('port') or self.device_id.replace('serial:', '')
        parity_map = {
            'N': serial.PARITY_NONE,
            'E': serial.PARITY_EVEN,
            'O': serial.PARITY_ODD,
            'M': serial.PARITY_MARK,
            'S': serial.PARITY_SPACE,
            'NONE': serial.PARITY_NONE,
            'EVEN': serial.PARITY_EVEN,
            'ODD': serial.PARITY_ODD,
        }
        bytesize_map = {5: serial.FIVEBITS, 6: serial.SIXBITS, 7: serial.SEVENBITS, 8: serial.EIGHTBITS}
        stopbits_map = {1: serial.STOPBITS_ONE, 1.5: serial.STOPBITS_ONE_POINT_FIVE, 2: serial.STOPBITS_TWO}
        parity = str(self.config.get('parity', 'O')).upper()
        data_bits = int(self.config.get('dataBits', self.config.get('databits', 8)))
        stop_bits = float(self.config.get('stopBits', self.config.get('stopbits', 1)))
        flow = str(self.config.get('flowControl', self.config.get('flow', '')) or '').upper()
        # 图像拉流：用阻塞 read(n) 凑满帧，timeout 为单次 read 上限
        source = str(self.config.get('source') or '')
        read_timeout = 0.02 if source == 'camera_image' else 0.1
        try:
            self._ser = serial.Serial(
                port=port,
                baudrate=int(self.config.get('baudrate', 2_000_000)),
                bytesize=bytesize_map.get(data_bits, serial.EIGHTBITS),
                parity=parity_map.get(parity, serial.PARITY_ODD),
                stopbits=stopbits_map.get(stop_bits, serial.STOPBITS_ONE),
                xonxoff=flow
                in (
                    'XONXOFF',
                    'XON_XOFF',
                    'RTSCTS_XONXOFF',
                    'RTS_CTS_XON_XOFF',
                    'DTRDSR_XONXOFF',
                    'DTR_DSR_XON_XOFF',
                ),
                rtscts=flow in ('RTSCTS', 'RTS_CTS', 'RTSCTS_XONXOFF', 'RTS_CTS_XON_XOFF'),
                dsrdtr=flow in ('DTRDSR', 'DTR_DSR', 'DTRDSR_XONXOFF', 'DTR_DSR_XON_XOFF'),
                timeout=read_timeout,
            )
        except Exception as e:
            self._ser = None
            msg = str(e) or e.__class__.__name__
            self._write_status('error', f'串口打开失败: {msg}')
            return False
        # Windows 下尽量加大驱动缓冲，减少丢字节/多次小读
        if source == 'camera_image':
            try:
                self._ser.set_buffer_size(rx_size=256 * 1024, tx_size=64 * 1024)
            except Exception:
                pass
        # 打开参数里的 source 先挂载；会话变更靠 session_changed 再同步
        self._sync_plugin(source=(self.config.get('source') or ''), force_session=False)
        return True

    def _write_serial(self, data: bytes) -> None:
        if not self._ser or not data:
            return
        self._ser.write(data)

    def _plugin_ctx(self) -> SerialPluginContext:
        return SerialPluginContext(
            device_id=self.device_id,
            redis=self._redis,
            config=self.config,
            is_running=lambda: self._running,
            read_serial=lambda n: (self._ser.read(n) if self._ser else b''),
            write_serial=self._write_serial,
            in_waiting=lambda: int(self._ser.in_waiting or 0) if self._ser else 0,
            reset_input_buffer=lambda: self._ser.reset_input_buffer() if self._ser else None,
            push_io=self._push_io,
            write_status=self._write_status,
            poll_control=self._consume_control,
        )

    def _read_session_source(self) -> str:
        from module_payload.service.payload_session_service import PayloadSessionService

        session = PayloadSessionService.get_session_sync(self._redis, self.device_id, SRC_KIND_SERIAL) or {}
        return str(session.get('source') or '')

    def _sync_plugin(self, *, source: str | None = None, force_session: bool = True) -> None:
        """按 source 挂载/卸载插件。默认用缓存；force_session 时读 Redis。"""
        from module_payload.collectors.plugins.registry import (
            create_serial_plugin,
            resolve_plugin_id_for_source,
        )

        if source is None:
            if force_session or self._cached_source is None:
                source = self._read_session_source()
            else:
                source = self._cached_source
        self._cached_source = source or ''
        want = resolve_plugin_id_for_source(source)
        if want == self._plugin_id:
            return
        if self._plugin is not None:
            try:
                self._plugin.on_detach()
            except Exception:
                pass
            self._plugin = None
            self._plugin_id = None
        if not want:
            return
        plugin = create_serial_plugin(want)
        if plugin is None:
            return
        plugin.on_attach(self._plugin_ctx())
        self._plugin = plugin
        self._plugin_id = want

    def handle_control(self, msg: dict[str, Any]) -> None:
        if msg.get('op') in ('session_changed', 'rebind', 'source_changed'):
            self._cached_source = None
            self._sync_plugin(force_session=True)
            return
        if self._plugin and self._plugin.handle_control(msg):
            return

    def read_and_parse(self) -> None:
        # 热路径不打 Redis；source 变更靠 session_changed
        self._sync_plugin(force_session=False)
        if self._plugin is not None:
            tick = self._plugin.tick(self._plugin_ctx())
            if tick.owns_loop:
                return
        if not self._ser:
            return
        try:
            waiting = self._ser.in_waiting or 0
            if waiting <= 0:
                return
            data = self._ser.read(waiting)
            if not data:
                return
            self._push_io('recv', data)
            self._rx_count += 1
            if self._plugin is not None:
                filtered = self._plugin.filter_rx(self._plugin_ctx(), data)
                if filtered.consume:
                    data = filtered.passthrough or b''
                    if not data:
                        return
                elif filtered.passthrough is not None:
                    data = filtered.passthrough
            if data:
                self._try_session_ingest(data, self.device_id, SRC_KIND_SERIAL)
        except Exception:
            pass

    def execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        raw = bytes.fromhex(command.get('hex', '').replace(' ', ''))
        self._ser.write(raw)
        # 发送日志由 BaseCollector._push_history → _push_io 统一写入，此处勿重复
        return {'success': True, 'message': 'OK'}

    def teardown(self) -> None:
        if self._plugin is not None:
            try:
                self._plugin.on_detach()
            except Exception:
                pass
            self._plugin = None
            self._plugin_id = None
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
