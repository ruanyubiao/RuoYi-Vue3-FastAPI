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
    def open_can(cls, body: CanOpenModel) -> dict[str, Any]:
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
            body.port, {'baudrate': body.baudrate, 'mode': body.mode}
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
        return {
            'deviceId': device_id,
            'connected': bool(status.get('connected')),
            'state': status.get('state', 'unknown'),
            'message': status.get('message', ''),
            'lastHeartbeat': hb.decode() if isinstance(hb, bytes) else hb,
            'stats': status.get('stats', {}),
        }
