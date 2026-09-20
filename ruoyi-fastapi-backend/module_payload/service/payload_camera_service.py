"""相机图像采集服务层。"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from redis import asyncio as aioredis

from exceptions.exception import ServiceException
from module_payload import redis_keys as rk
from module_payload.collectors.process_manager import CollectorProcessManager
from module_payload.entity.vo.payload_camera_vo import CameraStartModel
from module_payload.redis_store import get_image_meta, get_status
from module_payload.store.image_store import resolve_image_path


class PayloadCameraService:
    """相机采图：向串口采集进程 Redis 控制队列发 camera_start/stop。"""

    @classmethod
    def start(cls, body: CameraStartModel) -> dict[str, Any]:
        """要求串口已打开；清旧图、标记 acquiring，LPUSH camera_start。"""
        device_id = rk.serial_id(body.port)
        mgr = CollectorProcessManager.instance()
        # 串口须由页面先 open（带用户/配置页选定的波特率等）；此处只发 camera_start
        alive = False
        for entry in mgr.list_opened():
            if entry.get('deviceId') == device_id and entry.get('alive'):
                alive = True
                break
        if not alive:
            raise ServiceException(message=f'图像串口 {body.port} 未打开，请先连接后再采图')
        from datetime import datetime

        from module_payload.collectors.redis_sync import create_sync_redis, dumps_json

        r = create_sync_redis()
        try:
            # 立刻标记 acquiring，避免前端空等到超时（磁盘图片保留，不删）
            r.set(
                rk.image_meta_key(device_id),
                dumps_json(
                    {
                        'phase': 'acquiring',
                        'message': '正在采集图像',
                        'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    }
                ),
            )
            r.lpush(
                rk.ctrl_queue_key(device_id),
                json.dumps(
                    {
                        'op': 'camera_start',
                        'config': {
                            'resolution': body.resolution,
                            'image_no': body.image_no,
                            'once': bool(body.once),
                        },
                    },
                    ensure_ascii=False,
                ),
            )
        finally:
            r.close()
        return {'deviceId': device_id, 'status': 'started', 'once': bool(body.once)}

    @classmethod
    def stop(cls, port: str) -> dict[str, Any]:
        """LPUSH camera_stop 并立刻删 Redis 图像 meta/data。"""
        device_id = rk.serial_id(port)
        from module_payload.collectors.redis_sync import create_sync_redis

        r = create_sync_redis()
        try:
            r.lpush(rk.ctrl_queue_key(device_id), json.dumps({'op': 'camera_stop'}, ensure_ascii=False))
            # 立即清 Redis 图像元数据；串口 RX 缓冲由插件侧 camera_stop 清空
            r.delete(rk.image_meta_key(device_id))
        finally:
            r.close()
        return {'deviceId': device_id, 'status': 'stopped'}

    @classmethod
    async def get_image(
        cls, redis: aioredis.Redis, port: str, since: str = ''
    ) -> dict[str, Any]:
        """返回图像区 + 状态区。图片在磁盘，Redis 只存相对路径。

        ``since`` 为上一次拿到的相对路径；路径没变就只回状态，不读盘。
        """
        device_id = rk.serial_id(port)
        meta = await get_image_meta(redis, device_id) or {}
        status = await get_status(redis, device_id) or {}
        path = str(meta.get('path') or '')
        prev = str(since or '').strip().replace('\\', '/')
        changed = bool(path) and path != prev
        b64 = ''
        if changed:
            b64 = await asyncio.to_thread(cls._read_image_b64, path)
            if not b64:
                changed = False
        return {
            'image': {
                'meta': meta,
                'path': path,
                'changed': changed,
                'data': b64,
                'format': meta.get('format', 'png'),
            },
            'status': {
                'deviceId': device_id,
                'connected': status.get('connected', False),
                'message': status.get('message', ''),
                'state': status.get('state', ''),
                'imagePhase': meta.get('phase') or '',
            },
        }

    @staticmethod
    def _read_image_b64(rel_path: str) -> str:
        """读磁盘图片转 base64；越界或不存在返回空串。"""
        target = resolve_image_path(rel_path)
        if target is None:
            return ''
        try:
            return base64.b64encode(target.read_bytes()).decode('ascii')
        except OSError:
            return ''

    @classmethod
    async def get_camera_status(cls, redis: aioredis.Redis, port: str) -> dict[str, Any]:
        """读 Redis 设备状态（不含图像数据）。"""
        device_id = rk.serial_id(port)
        status = await get_status(redis, device_id) or {}
        return {
            'deviceId': device_id,
            'connected': status.get('connected', False),
            'message': status.get('message', ''),
            'state': status.get('state', ''),
        }
