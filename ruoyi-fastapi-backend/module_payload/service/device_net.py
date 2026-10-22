"""UDP 本机地址、打开关闭与已打开列表。"""

from __future__ import annotations

import asyncio
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collectors.duplex import resolve_full_duplex
from module_payload.collectors.process_manager import CollectorProcessManager
from module_payload.collectors import redis_sync
from module_payload.constants import SRC_KIND_UDP, normalize_parser_id
from module_payload.entity.vo.payload_device_vo import NetOpenModel
from module_payload.service.payload_session_service import PayloadSessionService


class DeviceNetMixin:
    """网口生命周期：本机地址、UDP 开/关。"""

    @classmethod
    def list_local_addresses(cls) -> list[str]:
        """当前采集机的 IPv4。没有快照时扫本机，方便监工尚未启动的单测。"""
        from module_payload.collectors.hardware import scan_local_addresses
        from module_payload.collectors.snapshot_store import sync_snapshot

        doc = sync_snapshot()
        if doc is None:
            return scan_local_addresses()
        return [str(item) for item in (doc.get('localAddrs') or []) if item]

    @classmethod
    def _normalize_udp_remote(cls, remote_host: str | None, remote_port: int | None) -> tuple[str, int]:
        """UDP 远程对端：端口 0 表示未指定，允许只填地址不填端口。

        填了非 0 端口则必须同时有地址，且端口为 1–65535。
        """
        host = (remote_host or '').strip()
        try:
            port = int(remote_port if remote_port is not None else 0)
        except (TypeError, ValueError) as e:
            raise ValueError('远程端口无效（0 表示未指定，其它须为 1–65535）') from e
        if port < 0 or port > 65535:
            raise ValueError('远程端口无效（0 表示未指定，其它须为 1–65535）')
        if port and not host:
            raise ValueError('未填写远程地址时端口须为 0（表示未指定端口）')
        return host, port

    @classmethod
    def _open_net_sync(cls, body: NetOpenModel) -> dict[str, Any]:
        """同步开 UDP 并写 Redis 会话（暂不支持 TCP）。

        deviceId = udp:{local_host}:{local_port}，远程地址/端口只写入采集配置
        作为默认发送对端，不参与 id。
        """
        proto = (body.proto or 'udp').lower()
        if proto != 'udp':
            raise ValueError(f'暂不支持协议: {proto}')
        local_host = (body.local_host or '0.0.0.0').strip() or '0.0.0.0'
        local_port = int(body.local_port)
        if local_port <= 0 or local_port > 65535:
            raise ValueError('本机端口无效')
        remote_host, remote_port = cls._normalize_udp_remote(body.remote_host, body.remote_port)
        from module_payload.collectors.supervisor_client import invoke

        result = invoke(
            'start_net',
            {
                'proto': proto,
                'localHost': local_host,
                'localPort': local_port,
                'config': {
                    'remote_host': remote_host,
                    'remote_port': remote_port,
                    'full_duplex': resolve_full_duplex(source=body.source, explicit=body.full_duplex),
                },
            },
            timeout_s=9.0,
        )
        device_id = str(result.get('deviceId') or '')
        already_open = bool(result.get('alreadyOpen'))
        parser_id = normalize_parser_id(body.parser_id) or None
        assembler_id = PayloadSessionService.validate_assembler_id(body.assembler_id, SRC_KIND_UDP)
        from exceptions.exception import ServiceException

        r = redis_sync.create_sync_redis()
        try:
            try:
                session = PayloadSessionService.open_session_sync(
                    r,
                    src_param=device_id,
                    src_kind=SRC_KIND_UDP,
                    parser_id=parser_id,
                    assembler_id=assembler_id,
                    routes=body.routes,
                    source=body.source or 'home',
                )
            except ValueError as e:
                raise ServiceException(message=str(e)) from e
        finally:
            r.close()
        return {
            'deviceId': device_id,
            'status': 'already_open' if already_open else 'opened',
            'session': session,
        }

    @classmethod
    async def open_net(cls, body: NetOpenModel) -> dict[str, Any]:
        """打开网络连接：阻塞等待放线程池。"""
        return await asyncio.to_thread(cls._open_net_sync, body)

    @classmethod
    def _close_net_sync(cls, proto: str, local_host: str, local_port: int) -> dict[str, Any]:
        """同步停网络采集进程并删 Redis 会话。"""
        proto = (proto or 'udp').lower()
        from module_payload.collectors.supervisor_client import invoke

        device_id = rk.net_id(proto, local_host, int(local_port))
        invoke('stop', {'deviceId': device_id}, timeout_s=8.0)
        r = redis_sync.create_sync_redis()
        try:
            PayloadSessionService.close_session_sync(r, device_id, SRC_KIND_UDP)
        finally:
            r.close()
        return {'deviceId': device_id, 'status': 'closed'}

    @classmethod
    async def close_net(cls, proto: str, local_host: str, local_port: int) -> dict[str, Any]:
        """关闭网络连接：线程池执行 stop + 删会话。"""
        return await asyncio.to_thread(cls._close_net_sync, proto, local_host, local_port)

    @classmethod
    def net_opened_from_registry(cls, opened: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """从某台采集机的已打开进程表整理 UDP/TCP。"""
        out: list[dict[str, Any]] = []
        for entry in opened or []:
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
    def list_net_opened(cls) -> list[dict[str, Any]]:
        """已打开的 UDP/TCP 连接列表。"""
        from module_payload.collectors.snapshot_store import visible_opened

        return cls.net_opened_from_registry(visible_opened())
