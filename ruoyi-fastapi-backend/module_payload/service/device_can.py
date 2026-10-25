"""CAN 厂商/通道与打开关闭。"""

from __future__ import annotations

import asyncio
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collectors.duplex import resolve_full_duplex
from module_payload.collectors.process_manager import CollectorProcessManager
from module_payload.collectors import redis_sync
from module_payload.constants import SRC_KIND_CAN
from module_payload.cfg.device_connect_merge import merge_can_open
from module_payload.entity.vo.payload_device_vo import CanOpenModel
from module_payload.protocol.registry import resolve_node_addr
from module_payload.protocol.protocol_catalog import DEFAULT_BUS_FAMILY, bus_parser_id
from module_payload.service.payload_session_service import PayloadSessionService

DEFAULT_CAN_PARSER = bus_parser_id(DEFAULT_BUS_FAMILY)  # 打开 CAN 未传 parserId 时


class DeviceCanMixin:
    """CAN 生命周期：厂商列表、开/关通道、热更新线缆。厂商扫描在监工。"""

    @classmethod
    def list_can_vendors(cls) -> dict[str, Any]:
        """当前采集机上的 CAN 厂商列表。离线时为空。"""
        from module_payload.collectors.snapshot_store import sync_snapshot

        doc = sync_snapshot()
        if not doc:
            return {'vendors': [], 'defaultVendor': 0}
        vendors = [item for item in (doc.get('canVendors') or []) if isinstance(item, dict)]
        return {'vendors': vendors, 'defaultVendor': int(doc.get('defaultCanVendor') or 0)}

    @classmethod
    def can_channels_from_opened(cls, opened: list[dict[str, Any]], *, demo: bool = False) -> list[dict[str, Any]]:
        """从某台采集机的已打开进程表整理 CAN 通道。demo 为真且没有通道时补一条占位。"""
        channels: list[dict[str, Any]] = []
        for entry in opened or []:
            if entry.get('type') != 'can':
                continue
            cfg = entry.get('config') or {}
            ch_by_index: dict[int, dict[str, Any]] = {}
            for c in cfg.get('channels') or []:
                if not isinstance(c, dict):
                    continue
                try:
                    ch_by_index[int(c.get('can_index', 0))] = c
                except (TypeError, ValueError):
                    continue
            for ch in entry.get('channels') or []:
                parts = entry['deviceId'].split(':')
                vendor = int(parts[1]) if len(parts) > 1 else int(cfg.get('vendor', 0))
                dev_index = int(parts[2]) if len(parts) > 2 else int(cfg.get('dev_index', 0))
                device_id = rk.can_channel_id(vendor, dev_index, ch)
                ch_cfg = ch_by_index.get(int(ch)) or {}
                baud = ch_cfg.get('baud_rate', cfg.get('baud_rate'))
                channels.append(
                    {
                        'deviceId': device_id,
                        'vendor': vendor,
                        'devIndex': dev_index,
                        'canIndex': ch,
                        'baudRate': int(baud) if baud is not None else None,
                        'alive': entry.get('alive', False),
                    }
                )
        if demo and not channels:
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
    def list_can_channels(cls) -> list[dict[str, Any]]:
        """已打开 CAN 通道列表（无通道时返回 demo 占位）。"""
        from module_payload.collectors.snapshot_store import visible_opened

        return cls.can_channels_from_opened(visible_opened(), demo=True)

    @classmethod
    def _open_can_sync(cls, body: CanOpenModel) -> dict[str, Any]:
        """同步打开 CAN 并写 Redis 会话；阻塞，由 open_can 丢进线程池。"""
        from exceptions.exception import ServiceException

        body = merge_can_open(body)
        try:
            assembler_id = PayloadSessionService.validate_assembler_id(body.assembler_id, SRC_KIND_CAN)
            node_addr_to = resolve_node_addr(assembler_id, body.node_addr_to)
            open_cfg: dict[str, Any] = {
                'baud_rate': body.baud_rate,
                'node_addr_to': node_addr_to,
                'assembler_id': assembler_id,
                'full_duplex': resolve_full_duplex(source=body.source, explicit=body.full_duplex),
            }
            if body.cable_flag is not None:
                open_cfg['cable_flag'] = int(body.cable_flag)
            from module_payload.collectors.supervisor_client import invoke

            result = invoke(
                'open_can',
                {
                    'vendor': body.vendor,
                    'devIndex': body.dev_index,
                    'canIndex': body.can_index,
                    'config': open_cfg,
                },
                timeout_s=16.0,
            )
            device_id = str(result.get('deviceId') or '')
            already_open = bool(result.get('alreadyOpen'))
        except RuntimeError as e:
            raise ServiceException(message=str(e)) from e
        parser_id = DEFAULT_CAN_PARSER if body.parser_id is None else (body.parser_id or None)
        r = redis_sync.create_sync_redis()
        try:
            try:
                session = PayloadSessionService.open_session_sync(
                    r,
                    src_param=device_id,
                    src_kind=SRC_KIND_CAN,
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
            CollectorProcessManager.instance().notify_session_changed(device_id)
            if body.cable_flag is not None:
                try:
                    CollectorProcessManager.instance().set_can_cable(
                        body.vendor,
                        body.dev_index,
                        body.can_index,
                        node_addr_to=node_addr_to,
                        cable_flag=body.cable_flag,
                    )
                except RuntimeError:
                    pass
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
        """同步关 CAN 通道并删除 Redis 会话。"""
        from module_payload.collectors.supervisor_client import invoke

        device_id = rk.can_channel_id(body.vendor, body.dev_index, body.can_index)
        invoke(
            'close_can',
            {
                'vendor': body.vendor,
                'devIndex': body.dev_index,
                'canIndex': body.can_index,
                'deviceId': device_id,
            },
            timeout_s=8.0,
        )
        r = redis_sync.create_sync_redis()
        try:
            PayloadSessionService.close_session_sync(r, device_id, SRC_KIND_CAN)
        finally:
            r.close()
        return {'deviceId': device_id, 'status': 'closed'}

    @classmethod
    async def close_can(cls, body: CanOpenModel) -> dict[str, Any]:
        """关闭 CAN：线程池执行，停采集通道并删 Redis 会话。"""
        return await asyncio.to_thread(cls._close_can_sync, body)

    @classmethod
    def _set_can_cable_sync(cls, body: Any) -> dict[str, Any]:
        """热更新已打开 CAN 的 nodeAddrTo / cableFlag（不重开会话）。"""
        from exceptions.exception import ServiceException

        vendor = body.vendor
        dev_index = body.dev_index
        can_index = body.can_index
        device_id = (body.device_id or '').strip()
        if device_id:
            parts = device_id.split(':')
            if len(parts) >= 4 and parts[0] == 'can':
                vendor = int(parts[1])
                dev_index = int(parts[2])
                can_index = int(parts[3])
        if vendor is None or dev_index is None or can_index is None:
            raise ServiceException(message='缺少 CAN 通道标识')
        if body.node_addr_to is None and body.cable_flag is None:
            raise ServiceException(message='请至少指定 nodeAddrTo 或 cableFlag')
        try:
            CollectorProcessManager.instance().set_can_cable(
                int(vendor),
                int(dev_index),
                int(can_index),
                node_addr_to=body.node_addr_to,
                cable_flag=body.cable_flag,
            )
        except RuntimeError as e:
            raise ServiceException(message=str(e)) from e
        return {
            'deviceId': rk.can_channel_id(int(vendor), int(dev_index), int(can_index)),
            'nodeAddrTo': body.node_addr_to,
            'cableFlag': body.cable_flag,
        }

    @classmethod
    async def set_can_cable(cls, body: Any) -> dict[str, Any]:
        """热更新 CAN 线缆参数；阻塞调用放线程池。"""
        return await asyncio.to_thread(cls._set_can_cable_sync, body)
