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

    _SNAPSHOT_WAIT_S = 5.0

    @classmethod
    def _session_alive(cls, opened: list[dict[str, Any]], src_param: str) -> bool:
        """进程表是否仍持有该 src_param。未知类型视为存活，以免误删会话。"""
        p = (src_param or '').strip()
        parts = p.split(':')
        if len(parts) >= 4 and parts[0] == 'can':
            card_id = ':'.join(parts[:3])
            try:
                can_index = int(parts[3])
            except ValueError:
                return False
            for entry in opened:
                if entry.get('type') == 'can' and entry.get('deviceId') == card_id:
                    return bool(entry.get('alive')) and can_index in (entry.get('channels') or [])
            return False
        if parts[0] == 'serial' or p.startswith('udp:') or p.startswith('tcp:'):
            for entry in opened:
                if entry.get('deviceId') == p:
                    return bool(entry.get('alive'))
            return False
        return True

    @classmethod
    def is_session_device_alive(cls, src_param: str) -> bool:
        """当前采集机进程表是否仍持有该 src_param。"""
        from module_payload.collectors.snapshot_store import visible_opened

        return cls._session_alive(visible_opened(), src_param)

    @classmethod
    async def list_alive_sessions(cls, redis: aioredis.Redis) -> list[dict[str, Any]]:
        """列出当前采集机快照里仍在进程表中的会话。快照不在线时返回空列表，不扫、不删。"""
        from redis.exceptions import RedisError

        from module_payload.collector_host import current_collector_host
        from module_payload.collectors.redis_sync import create_sync_redis
        from module_payload.collectors.snapshot_store import load_snapshot

        host = current_collector_host()

        def _load() -> dict[str, Any] | None:
            client = create_sync_redis()
            try:
                return load_snapshot(client, host)
            finally:
                client.close()

        try:
            doc = await asyncio.wait_for(asyncio.to_thread(_load), cls._SNAPSHOT_WAIT_S)
        except (RedisError, asyncio.TimeoutError, OSError):
            return []
        if not doc:
            return []
        registry = [row for row in (doc.get('registry') or []) if isinstance(row, dict)]
        return await PayloadSessionService.list_sessions(
            redis,
            is_alive=lambda src: cls._session_alive(registry, src),
            host=host,
            drop_missing=True,
        )

    @classmethod
    def _is_device_alive(cls, device_id: str) -> bool:
        """采集进程是否仍持有该 deviceId（CAN 按卡+通道判断）。"""
        from module_payload.collectors.snapshot_store import visible_opened

        opened = visible_opened()
        if device_id.startswith('serial:'):
            for entry in opened:
                if entry['type'] == 'serial' and entry['deviceId'] == device_id:
                    return bool(entry.get('alive'))
            return False
        if device_id.startswith('udp:') or device_id.startswith('tcp:'):
            for entry in opened:
                if entry['type'] == 'net' and entry['deviceId'] == device_id:
                    return bool(entry.get('alive'))
            return False
        parts = device_id.split(':')
        if len(parts) >= 4 and parts[0] == 'can':
            card_id = ':'.join(parts[:3])
            can_index = int(parts[3])
            for entry in opened:
                if entry['type'] == 'can' and entry['deviceId'] == card_id:
                    return bool(entry.get('alive')) and can_index in (entry.get('channels') or [])
            return False
        return False

    @classmethod
    def _close_all_sync(cls) -> dict[str, Any]:
        """关闭当前全部 CAN / 串口 / 网络连接（一次请求，避免前端连打触发重复提交）。"""
        from types import SimpleNamespace

        from module_payload.collectors.snapshot_store import visible_opened
        from module_payload.collectors.supervisor_client import invoke

        closed: list[str] = []
        failed: list[dict[str, str]] = []
        can_cards: set[str] = set()

        for entry in list(visible_opened()):
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
                invoke('stop', {'deviceId': card_id}, timeout_s=8.0)
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
        ack_key = rk.io_stream_flush_ack_key(device_id, str(req_id))
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
    def _decode_redis_text(cls, raw: Any) -> str:
        if raw is None:
            return ''
        if isinstance(raw, bytes):
            return raw.decode()
        return str(raw)

    @classmethod
    async def _stream_recv_enabled(cls, redis: aioredis.Redis, device_id: str) -> bool:
        """无心跳视为关；有心跳才读 ``io:stream:on``。"""
        ctrl_id = rk.collector_ctrl_id(device_id)
        try:
            hb = await redis.get(rk.heartbeat_key(ctrl_id))
        except Exception:
            hb = None
        if not hb:
            return False
        try:
            raw = await redis.get(rk.io_stream_on_key(device_id))
        except Exception:
            return False
        return cls._decode_redis_text(raw).strip() in ('1', 'true', 'True')

    @classmethod
    def set_io_stream_recv(cls, device_id: str, enabled: bool) -> dict[str, Any]:
        """用户点击：进程活着才入队；否则当作关。"""
        did = str(device_id or '').strip()
        if not did or not cls._is_device_alive(did):
            return {'deviceId': did, 'streamEnabled': False}
        on = bool(enabled)
        try:
            CollectorProcessManager.instance().notify_set_io_stream(did, on)
        except Exception:
            return {'deviceId': did, 'streamEnabled': False}
        return {'deviceId': did, 'streamEnabled': on}

    @classmethod
    async def get_io_log(
        cls,
        redis: aioredis.Redis,
        device_id: str,
        since_seq: int = 0,
        limit: int = IO_LOG_MAX,
        kind: str = 'preview',
        include_devices: bool = False,
    ) -> dict[str, Any]:
        """从 Redis List 取 IO 日志（seq > since_seq，旧→新；最多环缓 IO_LOG_MAX）。"""
        is_stream = str(kind or '').strip().lower() == 'stream'
        stream_enabled = False
        if is_stream:
            stream_enabled = await cls._stream_recv_enabled(redis, device_id)
            if stream_enabled:
                await cls._wait_stream_ctrl(redis, device_id, 'flush')
        try:
            cap = min(IO_LOG_MAX, max(1, int(limit)))
        except (TypeError, ValueError):
            cap = IO_LOG_MAX
        key, _seq_key = cls._io_log_keys(device_id, kind)
        raw_items = await redis.lrange(key, 0, IO_LOG_MAX - 1)
        parsed: list[dict[str, Any]] = []
        for raw in reversed(raw_items):
            text = raw.decode() if isinstance(raw, bytes) else str(raw)
            try:
                import json

                entry = json.loads(text)
            except Exception:
                continue
            parsed.append(entry)
        items: list[dict[str, Any]] = []
        max_seq = 0
        for entry in parsed:
            try:
                seq = int(entry.get('seq') or 0)
            except (TypeError, ValueError):
                seq = 0
            if seq > max_seq:
                max_seq = seq
            if seq <= since_seq:
                continue
            items.append(entry)
            if len(items) >= cap:
                break
        # 水位超前（序号键被清/回绕）：环缓里已没有 seq>since_seq，把现有窗口回放给前端接上
        if not items and parsed and since_seq > 0 and max_seq < since_seq:
            items = parsed[:cap]
        out: dict[str, Any] = {
            'deviceId': device_id,
            'items': items,
            'kind': 'stream' if is_stream else 'preview',
        }
        if is_stream:
            out['streamEnabled'] = stream_enabled
            if include_devices:
                try:
                    from module_payload.collector_host import current_collector_host
                    from module_payload.collectors.redis_sync import create_sync_redis
                    from module_payload.collectors.snapshot_store import list_machines

                    host = current_collector_host()

                    def _one_machine() -> list[dict[str, Any]]:
                        client = create_sync_redis()
                        try:
                            return list_machines(client, [host] if host else None)
                        finally:
                            client.close()

                    async def _devices() -> dict[str, Any]:
                        machines = await asyncio.to_thread(_one_machine)
                        item = next((row for row in machines if row.get('host') == host), None)
                        if item is None and machines:
                            item = machines[0]
                        row = await cls._device_row(redis, item, drop_missing=False) if item else {}
                        return {
                            'can': row.get('can') or [],
                            'serialOpened': row.get('serialOpened') or [],
                            'netOpened': row.get('netOpened') or [],
                            'sessions': row.get('sessions') or [],
                        }

                    out['devices'] = await asyncio.wait_for(_devices(), cls._SNAPSHOT_WAIT_S)
                except Exception:
                    pass
        return out

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
    async def _sessions_for_host(
        cls,
        redis: aioredis.Redis,
        host: str,
        opened: list[dict[str, Any]],
        *,
        drop_missing: bool = True,
    ) -> list[dict[str, Any]]:
        """只读这一台的会话。drop_missing 时用它自己的进程表清僵尸。"""
        return await PayloadSessionService.list_sessions(
            redis,
            is_alive=lambda src: cls._session_alive(opened, src),
            host=host,
            drop_missing=drop_missing,
        )

    @classmethod
    def _offline_device(cls, host: str) -> dict[str, Any]:
        """Redis 不可用时的空行。点名查询仍留在这一台。"""
        return {
            'host': host,
            'online': False,
            'serialPorts': [],
            'canVendors': [],
            'defaultCanVendor': 0,
            'localAddrs': [],
            'serialScanOk': False,
            'registry': [],
            'can': [],
            'serialOpened': [],
            'netOpened': [],
            'sessions': [],
        }

    @classmethod
    async def _device_row(
        cls, redis: aioredis.Redis, item: dict[str, Any], *, drop_missing: bool = True
    ) -> dict[str, Any]:
        """一台采集机的状态。离线只留空名单，不扫、不删它的会话。"""
        host = str(item.get('host') or '')
        online = bool(item.get('online'))
        registry = [row for row in (item.get('registry') or []) if isinstance(row, dict)] if online else []
        if online:
            serial_ports = [row for row in (item.get('serialPorts') or []) if isinstance(row, dict)]
            can_vendors = [row for row in (item.get('canVendors') or []) if isinstance(row, dict)]
            local_addrs = list(item.get('localAddrs') or [])
            sessions = await cls._sessions_for_host(redis, host, registry, drop_missing=drop_missing)
        else:
            serial_ports = []
            can_vendors = []
            local_addrs = []
            sessions = []
        return {
            'host': host,
            'online': online,
            'serialPorts': serial_ports,
            'canVendors': can_vendors,
            'defaultCanVendor': int(item.get('defaultCanVendor') or 0) if online else 0,
            'localAddrs': local_addrs,
            'serialScanOk': bool(item.get('serialScanOk')) if online else False,
            'registry': registry,
            'can': cls.can_channels_from_opened(registry, demo=False) if online else [],
            'serialOpened': cls.serial_opened_from_registry(registry) if online else [],
            'netOpened': cls.net_opened_from_registry(registry) if online else [],
            'sessions': sessions,
        }

    @classmethod
    async def get_snapshot(
        cls,
        redis: aioredis.Redis,
        parts: list[str] | str | None = None,
        hosts: list[str] | None = None,
    ) -> dict[str, Any]:
        """采集机状态列表。parts 忽略。不传 hosts 只含在线；点名含离线。"""
        del parts
        from redis.exceptions import RedisError

        from module_payload.collectors.redis_sync import create_sync_redis
        from module_payload.collectors.snapshot_store import list_machines

        parsers = PayloadSessionService.list_parser_options()
        assemblers = PayloadSessionService.list_assembler_options()
        named = [str(item).strip() for item in (hosts or []) if str(item or '').strip()]

        def _machines() -> list[dict[str, Any]]:
            client = create_sync_redis()
            try:
                return list_machines(client, hosts)
            finally:
                client.close()

        try:
            machines = await asyncio.wait_for(asyncio.to_thread(_machines), cls._SNAPSHOT_WAIT_S)
        except (RedisError, asyncio.TimeoutError, OSError):
            devices = [cls._offline_device(name) for name in named]
            return {'devices': devices, 'parsers': parsers, 'assemblers': assemblers}

        devices: list[dict[str, Any]] = []
        drop_missing = not named
        for item in machines:
            try:
                devices.append(
                    await asyncio.wait_for(
                        cls._device_row(redis, item, drop_missing=drop_missing),
                        cls._SNAPSHOT_WAIT_S,
                    )
                )
            except (RedisError, asyncio.TimeoutError, OSError):
                if named:
                    devices.append(cls._offline_device(str(item.get('host') or '')))
                continue
        return {
            'devices': devices,
            'parsers': parsers,
            'assemblers': assemblers,
        }
