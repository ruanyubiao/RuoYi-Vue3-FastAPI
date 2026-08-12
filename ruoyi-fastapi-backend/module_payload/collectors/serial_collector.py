"""
串口采集进程：打开串口 + 按会话挂载收流插件。

图像拉流等业务在 collectors/plugins 中实现，本类不堆功能开关。
"""

from __future__ import annotations

import time
from typing import Any

from module_payload.collectors.base_collector import BaseCollector
from module_payload.collectors.plugins.base import SerialPluginContext
from module_payload.constants import SRC_KIND_SERIAL

# 空闲时也定期核对系统串口列表（秒）
PORT_PRESENCE_CHECK_S = 1.0
# 控制口等默认 RX：勿一次读光 in_waiting，避免整包 HEX 写 Redis 卡死环路
MAX_RX_CHUNK = 4096
MAX_RX_CHUNKS = 32
# 积压时加大块/轮次，并节流 IO 日志（ingest 仍每块做）
BACKLOG_BYTES = 64 * 1024
BACKLOG_RX_CHUNK = 16 * 1024
BACKLOG_RX_CHUNKS = 128
BACKLOG_IO_LOG_EVERY = 16


class SerialCollector(BaseCollector):
    def __init__(self, device_id: str, config: dict[str, Any]) -> None:
        super().__init__(device_id, config)
        self._ser = None
        self._plugin = None
        self._plugin_id: str | None = None
        self._cached_source: str | None = None
        self._last_port_check = 0.0
        self._rx_io_skip = 0

    def _port_name(self) -> str:
        return str(self.config.get('port') or self.device_id.replace('serial:', '') or '').strip()

    @staticmethod
    def _is_port_lost_error(exc: BaseException) -> bool:
        """USB 拔出 / 句柄失效等应结束采集进程的错误。"""
        try:
            import serial

            if isinstance(exc, serial.SerialException):
                return True
        except Exception:
            pass
        if isinstance(exc, (OSError, PermissionError, TimeoutError)):
            return True
        name = type(exc).__name__.lower()
        return 'serial' in name

    def _fatal_disconnect(self, reason: str | BaseException) -> None:
        """串口物理消失或 I/O 致命失败：写状态并退出采集循环。"""
        if isinstance(reason, BaseException):
            msg = str(reason) or type(reason).__name__
        else:
            msg = str(reason or '串口已断开')
        try:
            self._write_status('error', f'串口已断开: {msg}')
        except Exception:
            pass
        self._running = False
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def _port_still_present(self) -> bool:
        """对照系统串口列表；端口已不存在则 fatal。"""
        now = time.monotonic()
        if now - self._last_port_check < PORT_PRESENCE_CHECK_S:
            return True
        self._last_port_check = now
        port = self._port_name()
        if not port:
            return True
        try:
            from serial.tools import list_ports

            present = {str(p.device).strip().upper() for p in list_ports.comports()}
        except Exception:
            return True
        if port.upper() in present:
            return True
        self._fatal_disconnect(f'系统串口列表中已不存在 {port}')
        return False

    def setup(self) -> bool:
        import serial

        port = self._port_name()
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
        self._last_port_check = time.monotonic()
        return True

    def _read_serial(self, n: int) -> bytes:
        if not self._ser:
            return b''
        try:
            return self._ser.read(n) or b''
        except Exception as e:
            if self._is_port_lost_error(e):
                self._fatal_disconnect(e)
            return b''

    def _write_serial(self, data: bytes) -> None:
        if not self._ser or not data:
            return
        try:
            self._ser.write(data)
        except Exception as e:
            if self._is_port_lost_error(e):
                self._fatal_disconnect(e)
                raise
            raise

    def _in_waiting(self) -> int:
        if not self._ser:
            return 0
        try:
            return int(self._ser.in_waiting or 0)
        except Exception as e:
            if self._is_port_lost_error(e):
                self._fatal_disconnect(e)
            return 0

    def _reset_input_buffer(self) -> None:
        if not self._ser:
            return
        try:
            self._ser.reset_input_buffer()
        except Exception as e:
            if self._is_port_lost_error(e):
                self._fatal_disconnect(e)

    def _plugin_ctx(self) -> SerialPluginContext:
        return SerialPluginContext(
            device_id=self.device_id,
            redis=self._redis,
            config=self.config,
            is_running=lambda: self._running,
            read_serial=self._read_serial,
            write_serial=self._write_serial,
            in_waiting=self._in_waiting,
            reset_input_buffer=self._reset_input_buffer,
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
        op = msg.get('op')
        if op in ('session_changed', 'rebind', 'source_changed'):
            self._cached_source = None
            self._invalidate_session_cache()
            self._sync_plugin(force_session=True)
            self._sync_xfer_logger()
            self._reset_tm_parsers()
            return
        if op == 'reload_tm_cfg':
            self._reset_tm_parsers()
            return
        if self._plugin and self._plugin.handle_control(msg):
            return

    def read_and_parse(self) -> None:
        if not self._port_still_present():
            return
        # 热路径不打 Redis；source 变更靠 session_changed
        self._sync_plugin(force_session=False)
        if self._plugin is not None:
            tick = self._plugin.tick(self._plugin_ctx())
            if tick.owns_loop:
                return
        if not self._ser:
            return
        try:
            waiting0 = self._in_waiting()
            if waiting0 <= 0:
                return
            backlog = waiting0 >= BACKLOG_BYTES
            chunk_size = BACKLOG_RX_CHUNK if backlog else MAX_RX_CHUNK
            max_chunks = BACKLOG_RX_CHUNKS if backlog else MAX_RX_CHUNKS
            for i in range(max_chunks):
                waiting = self._in_waiting() if i else waiting0
                if waiting <= 0:
                    break
                data = self._read_serial(min(waiting, chunk_size))
                if not data:
                    break
                # 积压时少写 IO 日志，优先 ingest/追上缓冲
                if backlog:
                    self._rx_io_skip += 1
                    if self._rx_io_skip >= BACKLOG_IO_LOG_EVERY:
                        self._rx_io_skip = 0
                        self._push_io('recv', data)
                else:
                    self._rx_io_skip = 0
                    self._push_io('recv', data)
                self._rx_count += 1
                if self._plugin is not None:
                    filtered = self._plugin.filter_rx(self._plugin_ctx(), data)
                    if filtered.consume:
                        data = filtered.passthrough or b''
                        if not data:
                            continue
                    elif filtered.passthrough is not None:
                        data = filtered.passthrough
                if data:
                    self._try_session_ingest(data, self.device_id, SRC_KIND_SERIAL)
        except Exception as e:
            if self._is_port_lost_error(e):
                self._fatal_disconnect(e)

    def execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        if not self._ser:
            return {'success': False, 'message': '串口未打开或已断开'}
        try:
            raw = bytes.fromhex(command.get('hex', '').replace(' ', ''))
            self._write_serial(raw)
            # 发送日志由 BaseCollector._push_history → _push_io 统一写入，此处勿重复
            return {'success': True, 'message': 'OK'}
        except Exception as e:
            if self._is_port_lost_error(e):
                self._fatal_disconnect(e)
                return {'success': False, 'message': f'串口已断开: {e}'}
            return {'success': False, 'message': str(e) or '发送失败'}

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
            self._ser = None
        super().teardown()
