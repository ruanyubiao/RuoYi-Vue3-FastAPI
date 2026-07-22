"""相机图像采集服务层。"""

from __future__ import annotations

import json
from typing import Any

from redis import asyncio as aioredis

from module_payload import redis_keys as rk
from module_payload.collectors.process_manager import CollectorProcessManager
from module_payload.entity.vo.payload_camera_vo import CameraStartModel
from module_payload.redis_store import get_image_meta, get_status


class PayloadCameraService:
    @classmethod
    def start(cls, body: CameraStartModel) -> dict[str, Any]:
        device_id = rk.serial_id(body.port)
        mgr = CollectorProcessManager.instance()
        # 串口应由页面先 open；此处只发 camera_start，避免再次 start_serial 抢锁/等待
        alive = False
        for entry in mgr.list_opened():
            if entry.get('deviceId') == device_id and entry.get('alive'):
                alive = True
                break
        if not alive:
            device_id, _already = mgr.start_serial(
                body.port,
                {
                    'baudrate': 2_000_000,
                    'source': 'camera_image',
                    'resolution': body.resolution,
                    'image_no': body.image_no,
                },
            )
        from module_payload.collectors.redis_sync import create_sync_redis

        r = create_sync_redis()
        try:
            r.lpush(
                rk.ctrl_queue_key(device_id),
                json.dumps(
                    {
                        'op': 'camera_start',
                        'config': {'resolution': body.resolution, 'image_no': body.image_no},
                    },
                    ensure_ascii=False,
                ),
            )
        finally:
            r.close()
        return {'deviceId': device_id, 'status': 'started'}

    @classmethod
    def stop(cls, port: str) -> dict[str, Any]:
        device_id = rk.serial_id(port)
        from module_payload.collectors.redis_sync import create_sync_redis

        r = create_sync_redis()
        try:
            r.lpush(rk.ctrl_queue_key(device_id), json.dumps({'op': 'camera_stop'}, ensure_ascii=False))
            # 立即清 Redis 图像缓存；串口 RX 缓冲由插件侧 camera_stop 清空
            r.delete(f'{rk.PREFIX}:{device_id}:image:meta', f'{rk.PREFIX}:{device_id}:image:data')
        finally:
            r.close()
        return {'deviceId': device_id, 'status': 'stopped'}

    @classmethod
    async def get_image(cls, redis: aioredis.Redis, port: str) -> dict[str, Any]:
        """一次返回图像区 + 状态区（均来自 Redis，分层不混排）。"""
        device_id = rk.serial_id(port)
        meta = await get_image_meta(redis, device_id) or {}
        b64 = await redis.get(f'{rk.PREFIX}:{device_id}:image:data')
        if isinstance(b64, bytes):
            b64 = b64.decode('ascii')
        status = await get_status(redis, device_id) or {}
        return {
            'image': {
                'meta': meta,
                'data': b64 or '',
                'format': meta.get('format', 'png'),
            },
            'status': {
                'deviceId': device_id,
                'connected': status.get('connected', False),
                'message': status.get('message', ''),
                'state': status.get('state', ''),
            },
        }

    @classmethod
    async def get_camera_status(cls, redis: aioredis.Redis, port: str) -> dict[str, Any]:
        device_id = rk.serial_id(port)
        status = await get_status(redis, device_id) or {}
        return {
            'deviceId': device_id,
            'connected': status.get('connected', False),
            'message': status.get('message', ''),
            'state': status.get('state', ''),
        }
