"""设备连接管理服务层。"""

from __future__ import annotations

from typing import Any

from redis import asyncio as aioredis

from module_payload import redis_keys as rk
from module_payload.collectors.process_manager import CollectorProcessManager
from module_payload.entity.vo.payload_device_vo import CanOpenModel, SerialOpenModel
from module_payload.redis_store import get_status


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
                vendor = int(parts[1]) if len(parts) > 1 else 0
                dev_index = int(parts[2]) if len(parts) > 2 else 0
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
        parts = device_id.split(':')
        if len(parts) >= 4 and parts[0] == 'can':
            card_id = ':'.join(parts[:3])
            can_index = int(parts[3])
            for entry in mgr.list_opened():
                if entry['type'] == 'can' and entry['deviceId'] == card_id:
                    return bool(entry.get('alive')) and can_index in (entry.get('channels') or [])
            return False
        return False

    @classmethod
    def open_can(cls, body: CanOpenModel) -> dict[str, Any]:
        from exceptions.exception import ServiceException

        try:
            device_id = CollectorProcessManager.instance().open_can_channel(
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
        return {'deviceId': device_id, 'status': 'opened'}

    @classmethod
    def close_can(cls, body: CanOpenModel) -> dict[str, Any]:
        CollectorProcessManager.instance().close_can_channel(body.vendor, body.dev_index, body.can_index)
        return {'deviceId': rk.can_channel_id(body.vendor, body.dev_index, body.can_index), 'status': 'closed'}

    @classmethod
    def list_serial_ports(cls) -> list[dict[str, Any]]:
        try:
            from serial.tools import list_ports

            return [{'port': p.device, 'description': p.description or ''} for p in list_ports.comports()]
        except Exception:
            return [{'port': 'COM1', 'description': '模拟串口'}, {'port': 'COM3', 'description': '模拟串口'}]

    @classmethod
    def open_serial(cls, body: SerialOpenModel) -> dict[str, Any]:
        device_id = CollectorProcessManager.instance().start_serial(
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
        return {'deviceId': device_id, 'status': 'opened'}

    @classmethod
    def close_serial(cls, port: str) -> dict[str, Any]:
        device_id = rk.serial_id(port)
        CollectorProcessManager.instance().stop(device_id)
        return {'deviceId': device_id, 'status': 'closed'}

    @classmethod
    async def get_device_status(cls, redis: aioredis.Redis, device_id: str) -> dict[str, Any]:
        status = await get_status(redis, device_id) or {}
        hb = await redis.get(rk.heartbeat_key(device_id))
        connected = bool(status.get('connected')) or cls._is_device_alive(device_id)
        return {
            'deviceId': device_id,
            'connected': connected,
            'state': status.get('state', 'unknown'),
            'message': status.get('message', ''),
            'lastHeartbeat': hb.decode() if isinstance(hb, bytes) else hb,
            'stats': status.get('stats', {}),
        }
