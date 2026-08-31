"""设备连接管理服务层（门面：CAN/串口/UDP mixin + 存活/快照）。"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from redis import asyncio as aioredis

from module_payload import redis_keys as rk
from module_payload.collectors.process_manager import CollectorProcessManager
from module_payload.collectors.redis_sync import create_sync_redis  # 兼容旧 patch 路径
from module_payload.constants import IO_LOG_MAX, STREAM_FLUSH_WAIT_S
from module_payload.redis_store import get_status
from module_payload.service.device_can import DeviceCanMixin
from module_payload.service.device_net import DeviceNetMixin
from module_payload.service.device_serial import DeviceSerialMixin
from module_payload.service.payload_session_service import PayloadSessionService


class PayloadDeviceService(DeviceCanMixin, DeviceSerialMixin, DeviceNetMixin):
    """设备连接：打开/关闭采集进程，并同步 Redis 会话。"""

    @classmethod
    def is_session_device_alive(cls, src_param: str) -> bool:
        """采集进程是否仍持有该 src_param；未知类型视为存活以免误删会话。"""
        mgr = CollectorProcessManager.instance()
        p = (src_param or '').strip()
        parts = p.split(':')
        if len(parts) >= 4 and parts[0] == 'can':
            card_id = ':'.join(parts[:3])
            try:
                can_index = int(parts[3])
            except ValueError:
                return False
            for entry in mgr.list_opened():
                if entry.get('type') == 'can' and entry.get('deviceId') == card_id:
                    return bool(entry.get('alive')) and can_index in (entry.get('channels') or [])
            return False
        if parts[0] == 'serial' or p.startswith('udp:') or p.startswith('tcp:'):
            for entry in mgr.list_opened():
                if entry.get('deviceId') == p:
                    return bool(entry.get('alive'))
            return False
        return True

    @classmethod
    async def list_alive_sessions(cls, redis: aioredis.Redis) -> list[dict[str, Any]]:
        """列出会话并清掉采集进程已不在的僵尸 Redis 记录。"""
        return await PayloadSessionService.list_sessions(redis, is_alive=cls.is_session_device_alive)

    @classmethod
    def _is_device_alive(cls, device_id: str) -> bool:
        """采集进程是否仍持有该 deviceId（CAN 按卡+通道判断）。"""
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
        if len(parts) >= 4 and parts[0] == 'can':
            card_id = ':'.join(parts[:3])
            can_index = int(parts[3])
            for entry in mgr.list_opened():
                if entry['type'] == 'can' and entry['deviceId'] == card_id:
                    return bool(entry.get('alive')) and can_index in (entry.get('channels') or [])
            return False
        return False

    @classmethod
    def _close_all_sync(cls) -> dict[str, Any]:
        """关闭当前全部 CAN / 串口 / 网络连接（一次请求，避免前端连打触发重复提交）。"""
        from types import SimpleNamespace

        mgr = CollectorProcessManager.instance()
        closed: list[str] = []
        failed: list[dict[str, str]] = []
        can_cards: set[str] = set()

        for entry in list(mgr.list_opened()):
            typ = entry.get('type')
            device_id = str(entry.get('deviceId') or '')
            cfg = entry.get('config') or {}
            try:
                if typ == 'can':
                    parts = device_id.split(':')
                    if len(parts) < 3:
                        failed.append({'deviceId': device_id, 'message': '无效 CAN 卡 ID'})
                        continue
                    vendor = int(parts[1])
                    dev_index = int(parts[2])
                    can_cards.add(device_id)
                    for ch in list(entry.get('channels') or []):
                        ch_id = rk.can_channel_id(vendor, dev_index, int(ch))
                        try:
                            cls._close_can_sync(
                                SimpleNamespace(vendor=vendor, dev_index=dev_index, can_index=int(ch))
                            )
                            closed.append(ch_id)
                        except Exception as e:
                            failed.append({'deviceId': ch_id, 'message': str(e)})
                elif typ == 'serial':
                    port = device_id.split(':', 1)[1] if ':' in device_id else device_id
                    try:
                        cls._close_serial_sync(port)
                        closed.append(device_id)
                    except Exception as e:
                        failed.append({'deviceId': device_id, 'message': str(e)})
                elif typ == 'net':
                    proto = str(cfg.get('proto') or 'udp')
                    host = str(cfg.get('local_host') or '0.0.0.0')
                    port = int(cfg.get('local_port') or 0)
                    try:
                        cls._close_net_sync(proto, host, port)
                        closed.append(device_id)
                    except Exception as e:
                        failed.append({'deviceId': device_id, 'message': str(e)})
            except Exception as e:
                failed.append({'deviceId': device_id or typ or 'unknown', 'message': str(e)})

        for card_id in can_cards:
            try:
                mgr.stop(card_id)
            except Exception:
                pass

        return {
            'closed': closed,
            'failed': failed,
            'ok': len(closed),
            'fail': len(failed),
        }

    @classmethod
    async def close_all(cls) -> dict[str, Any]:
        """一键关闭全部连接：线程池执行，避免卡住事件循环。"""
        return await asyncio.to_thread(cls._close_all_sync)

    @classmethod
    def _io_log_keys(cls, device_id: str, kind: str = 'preview') -> tuple[str, str]:
        """preview=:io（相机/单板）；stream=:io:stream（调试页全量）。"""
        if str(kind or '').strip().lower() == 'stream':
            return rk.io_stream_key(device_id), rk.io_stream_seq_key(device_id)
        return rk.io_log_key(device_id), rk.io_log_seq_key(device_id)

    @classmethod
    async def _wait_stream_ctrl(
        cls, redis: aioredis.Redis, device_id: str, op: str
    ) -> None:
        """通知采集进程刷/清 stream，等到 ack 或超时。无心跳则不 wait，直接读/删 Redis。"""
        ctrl_id = rk.collector_ctrl_id(device_id)
        try:
            hb = await redis.get(rk.heartbeat_key(ctrl_id))
        except Exception:
            hb = None
        if not hb:
            return
        req_id = str(uuid.uuid4())
        ack_key = rk.io_stream_flush_ack_key(device_id, req_id)
        try:
            mgr = CollectorProcessManager.instance()
            if op == 'clear':
                mgr.notify_clear_io_stream(device_id, req_id)
            else:
                mgr.notify_flush_io_stream(device_id, req_id)
        except Exception:
            return
        deadline = time.monotonic() + STREAM_FLUSH_WAIT_S
        while time.monotonic() < deadline:
            try:
                raw = await redis.get(ack_key)
            except Exception:
                return
            if raw:
                try:
                    await redis.delete(ack_key)
                except Exception:
                    pass
                return
            await asyncio.sleep(0.02)

    @classmethod
    async def get_io_log(
        cls,
        redis: aioredis.Redis,
        device_id: str,
        since_seq: int = 0,
        limit: int = IO_LOG_MAX,
        kind: str = 'preview',
    ) -> dict[str, Any]:
        """从 Redis List 取 IO 日志（seq > since_seq，旧→新；最多环缓 IO_LOG_MAX）。"""
        if str(kind or '').strip().lower() == 'stream':
            await cls._wait_stream_ctrl(redis, device_id, 'flush')
        try:
            cap = min(IO_LOG_MAX, max(1, int(limit)))
        except (TypeError, ValueError):
            cap = IO_LOG_MAX
        key, _seq_key = cls._io_log_keys(device_id, kind)
        raw_items = await redis.lrange(key, 0, IO_LOG_MAX - 1)
        items: list[dict[str, Any]] = []
        for raw in reversed(raw_items):
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
            if len(items) >= cap:
                break
        return {'deviceId': device_id, 'items': items, 'kind': 'stream' if str(kind).lower() == 'stream' else 'preview'}

    @classmethod
    async def clear_io_log(
        cls, redis: aioredis.Redis, device_id: str, kind: str = 'preview'
    ) -> dict[str, Any]:
        """清空该设备 Redis 中的 IO 日志及序号。stream 只清调试流，不动预览。"""
        if str(kind or '').strip().lower() == 'stream':
            await cls._wait_stream_ctrl(redis, device_id, 'clear')
        key, seq_key = cls._io_log_keys(device_id, kind)
        await redis.delete(key, seq_key)
        return {'deviceId': device_id, 'cleared': True, 'kind': 'stream' if str(kind).lower() == 'stream' else 'preview'}

    @classmethod
    async def get_device_status(cls, redis: aioredis.Redis, device_id: str) -> dict[str, Any]:
        """合并 Redis 状态/心跳与采集进程存活，返回连接与会话摘要。"""
        status = await get_status(redis, device_id) or {}
        hb = await redis.get(rk.heartbeat_key(device_id))
        alive = cls._is_device_alive(device_id)
        parts = str(device_id or '').split(':')
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
            'routes': (session or {}).get('routes') or [],
            'session': session,
        }

    @classmethod
    async def get_snapshot(cls, redis: aioredis.Redis, parts: list[str] | str | None = None) -> dict[str, Any]:
        """按 parts 批量返回设备侧只读数据，减少前端并发请求。

        支持：can / serialList / serialOpened / netOpened / sessions / parsers / assemblers
        """
        if isinstance(parts, str):
            keys = [p.strip() for p in parts.split(',') if p.strip()]
        else:
            keys = [str(p).strip() for p in (parts or []) if str(p).strip()]
        alias = {
            'canList': 'can',
            'list': 'can',
            'serial': 'serialList',
            'opened': 'serialOpened',
            'net': 'netOpened',
        }
        want = {alias.get(k, k) for k in keys}
        out: dict[str, Any] = {'parts': sorted(want)}
        if 'can' in want:
            out['can'] = cls.list_can_channels()
        if 'serialList' in want:
            out['serialList'] = cls.list_serial_ports()
        if 'serialOpened' in want:
            out['serialOpened'] = cls.list_serial_opened()
        if 'netOpened' in want:
            out['netOpened'] = cls.list_net_opened()
        if 'sessions' in want:
            out['sessions'] = await cls.list_alive_sessions(redis)
        if 'parsers' in want:
            out['parsers'] = PayloadSessionService.list_parser_options()
        if 'assemblers' in want:
            out['assemblers'] = PayloadSessionService.list_assembler_options()
        return out
