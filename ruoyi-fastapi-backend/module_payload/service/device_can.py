"""CAN 厂商/通道与打开关闭。"""

from __future__ import annotations

import asyncio
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collectors.duplex import resolve_full_duplex
from module_payload.collectors.process_manager import CollectorProcessManager
from module_payload.collectors import redis_sync
from module_payload.constants import PARSER_TM_CAN_BIU, SRC_KIND_CAN
from module_payload.entity.vo.payload_device_vo import CanOpenModel
from module_payload.hw_probe import HW_PROBE_TIMEOUT_SEC, call_with_timeout
from module_payload.service.payload_session_service import PayloadSessionService


class DeviceCanMixin:
    """CAN 生命周期：厂商列表、开/关通道、热更新线缆。"""

    @classmethod
    def _pick_default_can_vendor(cls, vendors: list[dict[str, Any]]) -> int:
        """厂商列表默认项：优先 PCIE，否则取第一项。"""
        if not vendors:
            return 0
        for item in vendors:
            text = f"{item.get('key', '')} {item.get('name', '')}".upper()
            if 'PCIE' in text:
                return int(item['value'])
        return int(vendors[0]['value'])

    @classmethod
    def _build_can_vendors_from_sdk(cls) -> list[dict[str, Any]]:
        from gpcan import CanSdkClient, CanVendorType

        info_map = CanSdkClient.get_supported_device_list()
        vendors: list[dict[str, Any]] = []
        for member in CanVendorType:
            value = int(member)
            info = info_map.get(value)
            channel_count = 2
            if info is None:
                name = member.name
            elif isinstance(info, str):
                name = info
            else:
                name = getattr(info, 'name', None) or member.name
                try:
                    channel_count = max(1, int(getattr(info, 'channel_count', 2) or 2))
                except (TypeError, ValueError):
                    channel_count = 2
            vendors.append(
                {
                    'key': member.name,
                    'value': value,
                    'name': name,
                    'channelCount': channel_count,
                }
            )
        return vendors

    @classmethod
    def list_can_vendors(cls) -> dict[str, Any]:
        """厂商列表：含 SDK 声明的 channelCount（通道 0..N-1）。"""
        try:
            vendors = call_with_timeout(
                cls._build_can_vendors_from_sdk,
                timeout=HW_PROBE_TIMEOUT_SEC,
                label='list_can_vendors',
            )
        except (ImportError, TimeoutError, Exception):
            vendors = []
        default_vendor = cls._pick_default_can_vendor(vendors)
        return {'vendors': vendors, 'defaultVendor': default_vendor}

    @classmethod
    def list_can_channels(cls) -> list[dict[str, Any]]:
        """已打开 CAN 通道列表（无通道时返回 demo 占位）。"""
        opened = CollectorProcessManager.instance().list_opened()
        channels: list[dict[str, Any]] = []
        for entry in opened:
            if entry['type'] != 'can':
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
    def _open_can_sync(cls, body: CanOpenModel) -> dict[str, Any]:
        """同步打开 CAN 并写 Redis 会话；阻塞，由 open_can 丢进线程池。"""
        from exceptions.exception import ServiceException

        try:
            open_cfg: dict[str, Any] = {
                'baud_rate': body.baud_rate,
                'node_addr_to': body.node_addr_to,
                'assembler_id': body.assembler_id or 'can_biu',
                'full_duplex': resolve_full_duplex(source=body.source, explicit=body.full_duplex),
            }
            if body.cable_flag is not None:
                open_cfg['cable_flag'] = int(body.cable_flag)
            device_id, already_open = CollectorProcessManager.instance().open_can_channel(
                body.vendor,
                body.dev_index,
                body.can_index,
                open_cfg,
            )
        except RuntimeError as e:
            raise ServiceException(message=str(e)) from e
        parser_id = PARSER_TM_CAN_BIU if body.parser_id is None else (body.parser_id or None)
        assembler_id = PayloadSessionService.validate_assembler_id(body.assembler_id, SRC_KIND_CAN)
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
                        node_addr_to=body.node_addr_to,
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
        device_id = rk.can_channel_id(body.vendor, body.dev_index, body.can_index)
        CollectorProcessManager.instance().close_can_channel(body.vendor, body.dev_index, body.can_index)
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
