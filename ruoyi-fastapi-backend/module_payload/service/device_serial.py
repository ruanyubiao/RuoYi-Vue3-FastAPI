"""串口枚举、对账与打开关闭。"""

from __future__ import annotations

import asyncio
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collectors.duplex import resolve_full_duplex
from module_payload.collectors.process_manager import CollectorProcessManager
from module_payload.collectors import redis_sync
from module_payload.constants import SRC_KIND_SERIAL
from module_payload.entity.vo.payload_device_vo import SerialOpenModel
from module_payload.hw_probe import HW_PROBE_TIMEOUT_SEC, call_with_timeout
from module_payload.service.payload_session_service import PayloadSessionService


class DeviceSerialMixin:
    """串口生命周期：端口列表、开/关、物理参数一致性。"""

    @classmethod
    def _enumerate_serial_ports(cls) -> list[Any]:
        from serial.tools import list_ports

        return list(list_ports.comports())

    @classmethod
    def _reconcile_missing_serial_ports(cls) -> None:
        """对照系统串口列表：已打开但物理端口消失的串口，自动 stop + 关会话。"""
        try:
            ports = call_with_timeout(
                cls._enumerate_serial_ports,
                timeout=HW_PROBE_TIMEOUT_SEC,
                label='reconcile_serial_ports',
            )
            present = {str(p.device).strip().upper() for p in ports}
        except (ImportError, TimeoutError, Exception):
            return
        opened = CollectorProcessManager.instance().list_opened()
        for entry in opened:
            if entry.get('type') != 'serial' or not entry.get('alive'):
                continue
            device_id = str(entry.get('deviceId') or '')
            port = device_id.split(':', 1)[1] if ':' in device_id else device_id
            if not port or str(port).strip().upper() in present:
                continue
            try:
                cls._close_serial_sync(port)
            except Exception:
                pass

    @classmethod
    def list_serial_opened(cls) -> list[dict[str, Any]]:
        """已打开串口列表；先对消失的物理口做对账关闭。"""
        cls._reconcile_missing_serial_ports()
        opened = CollectorProcessManager.instance().list_opened()
        ports: list[dict[str, Any]] = []
        for entry in opened:
            if entry['type'] != 'serial':
                continue
            device_id = entry['deviceId']
            port = device_id.split(':', 1)[1] if ':' in device_id else device_id
            cfg = entry.get('config') or {}
            ports.append(
                {
                    'deviceId': device_id,
                    'port': port,
                    'alive': entry.get('alive', False),
                    'baudrate': cfg.get('baudrate'),
                    'dataBits': cfg.get('data_bits'),
                    'stopBits': cfg.get('stop_bits'),
                    'parity': cfg.get('parity'),
                    'flowControl': cfg.get('flow_control'),
                }
            )
        return ports

    @classmethod
    def list_serial_ports(cls) -> list[dict[str, Any]]:
        """系统可用串口；枚举失败或超时返回空列表。"""
        try:
            ports = call_with_timeout(
                cls._enumerate_serial_ports,
                timeout=HW_PROBE_TIMEOUT_SEC,
                label='list_serial_ports',
            )
            return [{'port': p.device, 'description': p.description or ''} for p in ports]
        except (ImportError, TimeoutError, Exception):
            return []

    @classmethod
    def _norm_parity(cls, v: Any) -> str:
        """校验位归一到 N/E/O/M/S。"""
        s = str(v or 'N').strip().upper()
        aliases = {'NONE': 'N', 'EVEN': 'E', 'ODD': 'O', 'MARK': 'M', 'SPACE': 'S'}
        if s in aliases:
            return aliases[s]
        return s[:1] or 'N'

    @classmethod
    def _norm_flow(cls, v: Any) -> str:
        """流控归一到 NONE / XON/XOFF / RTS/CTS / DTR/DSR。"""
        s = str(v or 'NONE').strip().upper().replace(' ', '').replace('_', '').replace('-', '').replace('/', '')
        if not s or s in ('NONE', 'NO'):
            return 'NONE'
        if 'XON' in s:
            return 'XON/XOFF'
        if 'RTS' in s:
            return 'RTS/CTS'
        if 'DTR' in s:
            return 'DTR/DSR'
        return s

    @classmethod
    def _serial_config_matches(cls, running: dict[str, Any], requested: dict[str, Any]) -> bool:
        """比对已运行串口与请求的物理参数（不含 parser / assembler / source）。"""
        try:
            if int(running.get('baudrate')) != int(requested.get('baudrate')):
                return False
            if int(running.get('data_bits')) != int(requested.get('data_bits')):
                return False
            if float(running.get('stop_bits')) != float(requested.get('stop_bits')):
                return False
        except (TypeError, ValueError):
            return False
        if cls._norm_parity(running.get('parity')) != cls._norm_parity(requested.get('parity')):
            return False
        if cls._norm_flow(running.get('flow_control')) != cls._norm_flow(requested.get('flow_control')):
            return False
        return True

    @classmethod
    def _open_serial_sync(cls, body: SerialOpenModel) -> dict[str, Any]:
        """同步开串口并写 Redis 会话；已打开则校验物理参数一致。"""
        from exceptions.exception import ServiceException

        req_cfg = {
            'baudrate': body.baudrate,
            'data_bits': body.data_bits,
            'stop_bits': body.stop_bits,
            'parity': body.parity,
            'flow_control': body.flow_control,
            'source': (body.source or '').strip(),
            'full_duplex': resolve_full_duplex(source=body.source, explicit=body.full_duplex),
        }
        mgr = CollectorProcessManager.instance()
        device_id, already_open = mgr.start_serial(body.port, req_cfg)
        if already_open:
            running = {}
            for entry in mgr.list_opened():
                if entry.get('type') == 'serial' and entry.get('deviceId') == device_id:
                    running = dict(entry.get('config') or {})
                    break
            if not cls._serial_config_matches(running, req_cfg):
                raise ServiceException(
                    message=(
                        f'串口 {body.port} 已打开，但物理参数与请求不一致，'
                        f'请先关闭后再以目标参数重新打开'
                    )
                )
        parser_id = (body.parser_id or '').strip() or None
        assembler_id = PayloadSessionService.validate_assembler_id(body.assembler_id, SRC_KIND_SERIAL)
        r = redis_sync.create_sync_redis()
        try:
            try:
                session = PayloadSessionService.open_session_sync(
                    r,
                    src_param=device_id,
                    src_kind=SRC_KIND_SERIAL,
                    parser_id=parser_id,
                    assembler_id=assembler_id,
                    routes=body.routes,
                    source=body.source or 'home',
                )
            except ValueError as e:
                raise ServiceException(message=str(e)) from e
        finally:
            r.close()
        if already_open:
            mgr.notify_session_changed(device_id)
        return {
            'deviceId': device_id,
            'status': 'already_open' if already_open else 'opened',
            'session': session,
        }

    @classmethod
    async def open_serial(cls, body: SerialOpenModel) -> dict[str, Any]:
        """打开串口：阻塞等待放线程池，避免卡住事件循环。"""
        return await asyncio.to_thread(cls._open_serial_sync, body)

    @classmethod
    def _close_serial_sync(cls, port: str) -> dict[str, Any]:
        """同步停串口采集进程并删 Redis 会话。"""
        device_id = rk.serial_id(port)
        CollectorProcessManager.instance().stop(device_id)
        r = redis_sync.create_sync_redis()
        try:
            PayloadSessionService.close_session_sync(r, device_id, SRC_KIND_SERIAL)
        finally:
            r.close()
        return {'deviceId': device_id, 'status': 'closed'}

    @classmethod
    async def close_serial(cls, port: str) -> dict[str, Any]:
        """关闭串口：线程池执行 stop + 删会话。"""
        return await asyncio.to_thread(cls._close_serial_sync, port)
