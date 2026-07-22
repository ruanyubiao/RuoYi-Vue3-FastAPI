"""设备连接管理服务层。"""

from __future__ import annotations

import asyncio
from typing import Any

from redis import asyncio as aioredis

from module_payload import redis_keys as rk
from module_payload.collectors.process_manager import CollectorProcessManager
from module_payload.collectors.redis_sync import create_sync_redis
from module_payload.constants import PARSER_TM_CAN_YC, SRC_KIND_CAN, SRC_KIND_SERIAL, SRC_KIND_UDP
from module_payload.entity.vo.payload_device_vo import CanOpenModel, NetOpenModel, SerialOpenModel
from module_payload.redis_store import get_status
from module_payload.service.payload_session_service import PayloadSessionService


class PayloadDeviceService:
    @classmethod
    def _pick_default_can_vendor(cls, vendors: list[dict[str, Any]]) -> int:
        if not vendors:
            return 0
        for item in vendors:
            text = f"{item.get('key', '')} {item.get('name', '')}".upper()
            if 'PCIE' in text:
                return int(item['value'])
        return int(vendors[0]['value'])

    @classmethod
    def list_can_vendors(cls) -> dict[str, Any]:
        try:
            from gpcan import get_vendor_info_list

            items = get_vendor_info_list()
            vendors = [
                {
                    'key': item.key,
                    'value': int(item.value),
                    'name': item.name,
                }
                for item in items
            ]
        except Exception:
            vendors = [
                {'key': 'CAN_VENDOR_DEMO', 'value': 0, 'name': '演示/虚拟设备'},
                {'key': 'CAN_VENDOR_USB_V502', 'value': 1, 'name': 'USB-CAN V502'},
                {'key': 'CAN_VENDOR_USB_ALYST_PRO', 'value': 2, 'name': 'USB-CAN Alyst Pro'},
                {'key': 'CAN_VENDOR_ZLG', 'value': 3, 'name': 'PCIE ZLG CANFD'},
            ]
        default_vendor = cls._pick_default_can_vendor(vendors)
        return {'vendors': vendors, 'defaultVendor': default_vendor}

    @classmethod
    def list_can_channels(cls) -> list[dict[str, Any]]:
        opened = CollectorProcessManager.instance().list_opened()
        channels: list[dict[str, Any]] = []
        for entry in opened:
            if entry['type'] != 'can':
                continue
            for ch in entry.get('channels') or []:
                parts = entry['deviceId'].split(':')
                # card_id = can:{vendor}:{dev_index}
                cfg = entry.get('config') or {}
                vendor = int(parts[1]) if len(parts) > 1 else int(cfg.get('vendor', 0))
                dev_index = int(parts[2]) if len(parts) > 2 else int(cfg.get('dev_index', 0))
                device_id = rk.can_channel_id(vendor, dev_index, ch)
                channels.append(
                    {
                        'deviceId': device_id,
                        'vendor': vendor,
                        'devIndex': dev_index,
                        'canIndex': ch,
                        'alive': entry.get('alive', False),
                    }
                )
        if not channels:
            channels.append(
                {
                    'deviceId': 'can:0:0:0',
                    'vendor': 0,
                    'devIndex': 0,
                    'canIndex': 0,
                    'alive': False,
                    'demo': True,
                }
            )
        return channels

    @classmethod
    def list_serial_opened(cls) -> list[dict[str, Any]]:
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
    def _is_device_alive(cls, device_id: str) -> bool:
        mgr = CollectorProcessManager.instance()
        if device_id.startswith('serial:'):
            for entry in mgr.list_opened():
                if entry['type'] == 'serial' and entry['deviceId'] == device_id:
                    return bool(entry.get('alive'))
            return False
        if device_id.startswith('udp:') or device_id.startswith('tcp:'):
            for entry in mgr.list_opened():
                if entry['type'] == 'net' and entry['deviceId'] == device_id:
                    return bool(entry.get('alive'))
            return False
        parts = device_id.split(':')
        # channel_id = can:{vendor}:{dev_index}:{can_index}
        if len(parts) >= 4 and parts[0] == 'can':
            card_id = ':'.join(parts[:3])
            can_index = int(parts[3])
            for entry in mgr.list_opened():
                if entry['type'] == 'can' and entry['deviceId'] == card_id:
                    return bool(entry.get('alive')) and can_index in (entry.get('channels') or [])
            return False
        return False

    @classmethod
    def _open_can_sync(cls, body: CanOpenModel) -> dict[str, Any]:
        from exceptions.exception import ServiceException

        try:
            device_id, already_open = CollectorProcessManager.instance().open_can_channel(
                body.vendor,
                body.dev_index,
                body.can_index,
                {
                    'baud_rate': body.baud_rate,
                    'node_addr_to': body.node_addr_to,
                    'cable_flag': body.cable_flag,
                },
            )
        except RuntimeError as e:
            raise ServiceException(message=str(e)) from e
        # None=默认绑定遥测；显式传 '' 表示不绑定
        parser_id = PARSER_TM_CAN_YC if body.parser_id is None else (body.parser_id or None)
        assembler_id = PayloadSessionService.validate_assembler_id(body.assembler_id)
        r = create_sync_redis()
        try:
            session = PayloadSessionService.open_session_sync(
                r,
                src_param=device_id,
                src_kind=SRC_KIND_CAN,
                parser_id=parser_id,
                assembler_id=assembler_id,
            )
        finally:
            r.close()
        return {
            'deviceId': device_id,
            'status': 'already_open' if already_open else 'opened',
            'session': session,
        }

    @classmethod
    async def open_can(cls, body: CanOpenModel) -> dict[str, Any]:
        """打开 CAN：阻塞等待放线程池，避免卡住 FastAPI 事件循环。"""
        return await asyncio.to_thread(cls._open_can_sync, body)

    @classmethod
    def _close_can_sync(cls, body: CanOpenModel) -> dict[str, Any]:
        device_id = rk.can_channel_id(body.vendor, body.dev_index, body.can_index)
        CollectorProcessManager.instance().close_can_channel(body.vendor, body.dev_index, body.can_index)
        r = create_sync_redis()
        try:
            PayloadSessionService.close_session_sync(r, device_id, SRC_KIND_CAN)
        finally:
            r.close()
        return {'deviceId': device_id, 'status': 'closed'}

    @classmethod
    async def close_can(cls, body: CanOpenModel) -> dict[str, Any]:
        return await asyncio.to_thread(cls._close_can_sync, body)

    @classmethod
    def list_serial_ports(cls) -> list[dict[str, Any]]:
        try:
            from serial.tools import list_ports

            return [{'port': p.device, 'description': p.description or ''} for p in list_ports.comports()]
        except Exception:
            return [{'port': 'COM1', 'description': '模拟串口'}, {'port': 'COM3', 'description': '模拟串口'}]

    @classmethod
    def _open_serial_sync(cls, body: SerialOpenModel) -> dict[str, Any]:
        device_id, already_open = CollectorProcessManager.instance().start_serial(
            body.port,
            {
                'baudrate': body.baudrate,
                'mode': body.mode,
                'data_bits': body.data_bits,
                'stop_bits': body.stop_bits,
                'parity': body.parity,
                'flow_control': body.flow_control,
            },
        )
        parser_id = (body.parser_id or '').strip() or None
        assembler_id = PayloadSessionService.validate_assembler_id(body.assembler_id)
        r = create_sync_redis()
        try:
            session = PayloadSessionService.open_session_sync(
                r,
                src_param=device_id,
                src_kind=SRC_KIND_SERIAL,
                parser_id=parser_id,
                assembler_id=assembler_id,
            )
        finally:
            r.close()
        return {
            'deviceId': device_id,
            'status': 'already_open' if already_open else 'opened',
            'session': session,
        }

    @classmethod
    async def open_serial(cls, body: SerialOpenModel) -> dict[str, Any]:
        return await asyncio.to_thread(cls._open_serial_sync, body)

    @classmethod
    def _close_serial_sync(cls, port: str) -> dict[str, Any]:
        device_id = rk.serial_id(port)
        CollectorProcessManager.instance().stop(device_id)
        r = create_sync_redis()
        try:
            PayloadSessionService.close_session_sync(r, device_id, SRC_KIND_SERIAL)
        finally:
            r.close()
        return {'deviceId': device_id, 'status': 'closed'}

    @classmethod
    async def close_serial(cls, port: str) -> dict[str, Any]:
        return await asyncio.to_thread(cls._close_serial_sync, port)

    @classmethod
    def list_local_addresses(cls) -> list[str]:
        """本机 IPv4 地址列表（含 0.0.0.0 / 127.0.0.1）。"""
        import socket

        addrs: set[str] = {'0.0.0.0', '127.0.0.1'}
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ip = info[4][0]
                if ip:
                    addrs.add(ip)
        except Exception:
            pass
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(('8.8.8.8', 80))
                addrs.add(s.getsockname()[0])
        except Exception:
            pass
        # 稳定排序：特殊地址靠前
        special = ['0.0.0.0', '127.0.0.1']
        rest = sorted(a for a in addrs if a not in special)
        return [a for a in special if a in addrs] + rest

    @classmethod
    def _open_net_sync(cls, body: NetOpenModel) -> dict[str, Any]:
        proto = (body.proto or 'udp').lower()
        if proto != 'udp':
            raise ValueError(f'暂不支持协议: {proto}')
        local_host = (body.local_host or '0.0.0.0').strip() or '0.0.0.0'
        local_port = int(body.local_port)
        if local_port <= 0 or local_port > 65535:
            raise ValueError('本机端口无效')
        device_id, already_open = CollectorProcessManager.instance().start_net(
            proto,
            local_host,
            local_port,
            {
                'remote_host': body.remote_host or '',
                'remote_port': int(body.remote_port or 0),
            },
        )
        parser_id = (body.parser_id or '').strip() or None
        assembler_id = PayloadSessionService.validate_assembler_id(body.assembler_id)
        r = create_sync_redis()
        try:
            session = PayloadSessionService.open_session_sync(
                r,
                src_param=device_id,
                src_kind=SRC_KIND_UDP,
                parser_id=parser_id,
                assembler_id=assembler_id,
            )
        finally:
            r.close()
        return {
            'deviceId': device_id,
            'status': 'already_open' if already_open else 'opened',
            'session': session,
        }

    @classmethod
    async def open_net(cls, body: NetOpenModel) -> dict[str, Any]:
        return await asyncio.to_thread(cls._open_net_sync, body)

    @classmethod
    def _close_net_sync(cls, proto: str, local_host: str, local_port: int) -> dict[str, Any]:
        proto = (proto or 'udp').lower()
        device_id = rk.net_id(proto, local_host, int(local_port))
        CollectorProcessManager.instance().stop(device_id)
        r = create_sync_redis()
        try:
            PayloadSessionService.close_session_sync(r, device_id, SRC_KIND_UDP)
        finally:
            r.close()
        return {'deviceId': device_id, 'status': 'closed'}

    @classmethod
    async def close_net(cls, proto: str, local_host: str, local_port: int) -> dict[str, Any]:
        return await asyncio.to_thread(cls._close_net_sync, proto, local_host, local_port)

    @classmethod
    def list_net_opened(cls) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for entry in CollectorProcessManager.instance().list_opened():
            if entry.get('type') != 'net':
                continue
            cfg = entry.get('config') or {}
            out.append(
                {
                    'deviceId': entry['deviceId'],
                    'alive': entry['alive'],
                    'proto': cfg.get('proto', 'udp'),
                    'localHost': cfg.get('local_host', ''),
                    'localPort': cfg.get('local_port'),
                    'remoteHost': cfg.get('remote_host', ''),
                    'remotePort': cfg.get('remote_port'),
                }
            )
        return out

    @classmethod
    async def get_io_log(
        cls, redis: aioredis.Redis, device_id: str, since_seq: int = 0, limit: int = 200
    ) -> dict[str, Any]:
        key = rk.io_log_key(device_id)
        raw_items = await redis.lrange(key, 0, max(0, limit - 1))
        items: list[dict[str, Any]] = []
        for raw in reversed(raw_items):  # 旧→新
            text = raw.decode() if isinstance(raw, bytes) else str(raw)
            try:
                import json

                entry = json.loads(text)
            except Exception:
                continue
            seq = int(entry.get('seq') or 0)
            if seq <= since_seq:
                continue
            items.append(entry)
        return {'deviceId': device_id, 'items': items}

    @classmethod
    async def clear_io_log(cls, redis: aioredis.Redis, device_id: str) -> dict[str, Any]:
        await redis.delete(rk.io_log_key(device_id), rk.io_log_seq_key(device_id))
        return {'deviceId': device_id, 'cleared': True}

    @classmethod
    async def get_device_status(cls, redis: aioredis.Redis, device_id: str) -> dict[str, Any]:
        status = await get_status(redis, device_id) or {}
        hb = await redis.get(rk.heartbeat_key(device_id))
        alive = cls._is_device_alive(device_id)
        parts = str(device_id or '').split(':')
        # CAN 通道：以采集进程是否仍持有该通道为准（status 可能被异常路径清掉）
        if len(parts) >= 4 and parts[0] == 'can':
            connected = alive
        else:
            connected = alive or bool(status.get('connected'))
        session = await PayloadSessionService.get_session(redis, device_id)
        return {
            'deviceId': device_id,
            'connected': connected,
            'state': status.get('state', 'unknown') if connected else (status.get('state') or 'stopped'),
            'message': status.get('message', ''),
            'lastHeartbeat': hb.decode() if isinstance(hb, bytes) else hb,
            'stats': status.get('stats', {}),
            'parserId': (session or {}).get('parserId') or '',
            'assemblerId': (session or {}).get('assemblerId') or 'passthrough',
            'session': session,
        }
