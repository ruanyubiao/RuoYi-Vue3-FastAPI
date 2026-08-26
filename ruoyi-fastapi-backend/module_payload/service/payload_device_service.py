"""设备连接管理服务层。"""

from __future__ import annotations

import asyncio
from typing import Any

from redis import asyncio as aioredis

from module_payload import redis_keys as rk
from module_payload.collectors.duplex import resolve_full_duplex
from module_payload.collectors.process_manager import CollectorProcessManager
from module_payload.collectors.redis_sync import create_sync_redis
from module_payload.constants import PARSER_TM_CAN_BIU, SRC_KIND_CAN, SRC_KIND_SERIAL, SRC_KIND_UDP
from module_payload.entity.vo.payload_device_vo import CanOpenModel, NetOpenModel, SerialOpenModel
from module_payload.redis_store import get_status
from module_payload.service.payload_session_service import PayloadSessionService


class PayloadDeviceService:
    """设备连接：打开/关闭采集进程，并同步 Redis 会话。"""

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
    def list_can_vendors(cls) -> dict[str, Any]:
        """厂商列表：含 SDK 声明的 channelCount（通道 0..N-1）。"""
        try:
            from gpcan import CanSdkClient, CanVendorType

            info_map = CanSdkClient.get_supported_device_list()
            vendors = []
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
        except Exception:
            vendors = [
                {'key': 'CAN_VENDOR_DEMO', 'value': 0, 'name': '演示/虚拟设备', 'channelCount': 4},
                {'key': 'CAN_VENDOR_USB_V502', 'value': 1, 'name': 'USB-CAN V502', 'channelCount': 2},
                {'key': 'CAN_VENDOR_USB_ALYST_PRO', 'value': 2, 'name': 'USB-CAN Alyst Pro', 'channelCount': 2},
                {'key': 'CAN_VENDOR_ZLG', 'value': 3, 'name': 'PCIE ZLG CANFD', 'channelCount': 2},
            ]
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
                # card_id = can:{vendor}:{dev_index}
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
    def _reconcile_missing_serial_ports(cls) -> None:
        """对照系统串口列表：已打开但物理端口消失的串口，自动 stop + 关会话。"""
        try:
            from serial.tools import list_ports

            present = {str(p.device).strip().upper() for p in list_ports.comports()}
        except Exception:
            # 枚举失败时不误关；由采集进程侧再检测
            return
        opened = CollectorProcessManager.instance().list_opened()
        for entry in opened:
            if entry.get('type') != 'serial' or not entry.get('alive'):
                continue
            device_id = str(entry.get('deviceId') or '')
            port = device_id.split(':', 1)[1] if ':' in device_id else device_id
            if not port or str(port).strip().upper() in present:
                continue
            try:
                cls._close_serial_sync(port)
            except Exception:
                pass

    @classmethod
    def list_serial_opened(cls) -> list[dict[str, Any]]:
        """已打开串口列表；先对消失的物理口做对账关闭。"""
        cls._reconcile_missing_serial_ports()
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
        """同步打开 CAN 并写 Redis 会话；阻塞，由 open_can 丢进线程池。"""
        from exceptions.exception import ServiceException

        try:
            open_cfg: dict[str, Any] = {
                'baud_rate': body.baud_rate,
                'node_addr_to': body.node_addr_to,
                'assembler_id': body.assembler_id or 'can_biu',
                # 全双工：请求显式值优先，否则按 cfg_device_connect 的 source
                'full_duplex': resolve_full_duplex(source=body.source, explicit=body.full_duplex),
            }
            # 首页不指定线缆；遥控 A/B 分别传 0/1
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
        # None=默认绑定遥测；显式传 '' 表示不绑定
        parser_id = PARSER_TM_CAN_BIU if body.parser_id is None else (body.parser_id or None)
        assembler_id = PayloadSessionService.validate_assembler_id(body.assembler_id, SRC_KIND_CAN)
        r = create_sync_redis()
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
        # 复用已打开通道：更新 session；遥控侧指定线缆时热更新
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
        return await asyncio.to_thread(cls._open_can_sync, body)  # SDK 打开会阻塞

    @classmethod
    def _close_can_sync(cls, body: CanOpenModel) -> dict[str, Any]:
        """同步关 CAN 通道并删除 Redis 会话。"""
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

    @classmethod
    def list_serial_ports(cls) -> list[dict[str, Any]]:
        """系统可用串口；枚举失败时返回模拟 COM。"""
        try:
            from serial.tools import list_ports

            return [{'port': p.device, 'description': p.description or ''} for p in list_ports.comports()]
        except Exception:
            return [{'port': 'COM1', 'description': '模拟串口'}, {'port': 'COM3', 'description': '模拟串口'}]

    @classmethod
    def _norm_parity(cls, v: Any) -> str:
        """校验位归一到 N/E/O/M/S。"""
        s = str(v or 'N').strip().upper()
        aliases = {'NONE': 'N', 'EVEN': 'E', 'ODD': 'O', 'MARK': 'M', 'SPACE': 'S'}
        if s in aliases:
            return aliases[s]
        return (s[:1] or 'N')

    @classmethod
    def _norm_flow(cls, v: Any) -> str:
        """流控归一到 NONE / XON/XOFF / RTS/CTS / DTR/DSR。"""
        s = str(v or 'NONE').strip().upper().replace(' ', '').replace('_', '').replace('-', '').replace('/', '')
        if not s or s in ('NONE', 'NO'):
            return 'NONE'
        if 'XON' in s:
            return 'XON/XOFF'
        if 'RTS' in s:
            return 'RTS/CTS'
        if 'DTR' in s:
            return 'DTR/DSR'
        return s

    @classmethod
    def _serial_config_matches(cls, running: dict[str, Any], requested: dict[str, Any]) -> bool:
        """比对已运行串口与请求的物理参数（不含 parser / assembler / source）。"""
        try:
            if int(running.get('baudrate')) != int(requested.get('baudrate')):
                return False
            if int(running.get('data_bits')) != int(requested.get('data_bits')):
                return False
            if float(running.get('stop_bits')) != float(requested.get('stop_bits')):
                return False
        except (TypeError, ValueError):
            return False
        if cls._norm_parity(running.get('parity')) != cls._norm_parity(requested.get('parity')):
            return False
        if cls._norm_flow(running.get('flow_control')) != cls._norm_flow(requested.get('flow_control')):
            return False
        return True

    @classmethod
    def _open_serial_sync(cls, body: SerialOpenModel) -> dict[str, Any]:
        """同步开串口并写 Redis 会话；已打开则校验物理参数一致。"""
        from exceptions.exception import ServiceException

        req_cfg = {
            'baudrate': body.baudrate,
            'data_bits': body.data_bits,
            'stop_bits': body.stop_bits,
            'parity': body.parity,
            'flow_control': body.flow_control,
            'source': (body.source or '').strip(),
            # 全双工：请求显式值优先，否则按 cfg_device_connect 的 source
            'full_duplex': resolve_full_duplex(source=body.source, explicit=body.full_duplex),
        }
        mgr = CollectorProcessManager.instance()
        device_id, already_open = mgr.start_serial(body.port, req_cfg)
        if already_open:
            running = {}
            for entry in mgr.list_opened():
                if entry.get('type') == 'serial' and entry.get('deviceId') == device_id:
                    running = dict(entry.get('config') or {})
                    break
            if not cls._serial_config_matches(running, req_cfg):
                raise ServiceException(
                    message=(
                        f'串口 {body.port} 已打开，但物理参数与请求不一致，'
                        f'请先关闭后再以目标参数重新打开'
                    )
                )
        parser_id = (body.parser_id or '').strip() or None
        assembler_id = PayloadSessionService.validate_assembler_id(body.assembler_id, SRC_KIND_SERIAL)
        r = create_sync_redis()
        try:
            try:
                session = PayloadSessionService.open_session_sync(
                    r,
                    src_param=device_id,
                    src_kind=SRC_KIND_SERIAL,
                    parser_id=parser_id,
                    assembler_id=assembler_id,
                    routes=body.routes,
                    source=body.source or 'home',
                )
            except ValueError as e:
                raise ServiceException(message=str(e)) from e
        finally:
            r.close()
        # 仅复用已打开进程时需要通知其按新 source 挂载插件
        if already_open:
            mgr.notify_session_changed(device_id)
        return {
            'deviceId': device_id,
            'status': 'already_open' if already_open else 'opened',
            'session': session,
        }

    @classmethod
    async def open_serial(cls, body: SerialOpenModel) -> dict[str, Any]:
        """打开串口：阻塞等待放线程池，避免卡住事件循环。"""
        return await asyncio.to_thread(cls._open_serial_sync, body)  # 串口打开会阻塞

    @classmethod
    def _close_serial_sync(cls, port: str) -> dict[str, Any]:
        """同步停串口采集进程并删 Redis 会话。"""
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
        """关闭串口：线程池执行 stop + 删会话。"""
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
        device_id, already_open = CollectorProcessManager.instance().start_net(
            proto,
            local_host,
            local_port,
            {
                'remote_host': remote_host,
                'remote_port': remote_port,
                # 全双工：请求显式值优先，否则按 cfg_device_connect 的 source
                'full_duplex': resolve_full_duplex(source=body.source, explicit=body.full_duplex),
            },
        )
        parser_id = (body.parser_id or '').strip() or None
        assembler_id = PayloadSessionService.validate_assembler_id(body.assembler_id, SRC_KIND_UDP)
        from exceptions.exception import ServiceException

        r = create_sync_redis()
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
        # 复用已打开 UDP：把本页远程对端 + 会话（组装器/解释器）写进采集进程
        if already_open:
            CollectorProcessManager.instance().apply_net_reuse_params(
                device_id,
                remote_host=remote_host,
                remote_port=remote_port,
            )
        return {
            'deviceId': device_id,
            'status': 'already_open' if already_open else 'opened',
            'session': session,
        }

    @classmethod
    async def open_net(cls, body: NetOpenModel) -> dict[str, Any]:
        """打开网络连接：阻塞等待放线程池。"""
        return await asyncio.to_thread(cls._open_net_sync, body)  # bind 可能阻塞

    @classmethod
    def _close_net_sync(cls, proto: str, local_host: str, local_port: int) -> dict[str, Any]:
        """同步停网络采集进程并删 Redis 会话。"""
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
        """关闭网络连接：线程池执行 stop + 删会话。"""
        return await asyncio.to_thread(cls._close_net_sync, proto, local_host, local_port)

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

        # 释放 CAN 卡进程（单通道 close 会保留进程）
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
    def list_net_opened(cls) -> list[dict[str, Any]]:
        """已打开的 UDP/TCP 连接列表。"""
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
        """从 Redis List 取 IO 日志（seq > since_seq，旧→新）。"""
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
        """清空该设备 Redis 中的 IO 日志及序号。"""
        await redis.delete(rk.io_log_key(device_id), rk.io_log_seq_key(device_id))
        return {'deviceId': device_id, 'cleared': True}

    @classmethod
    async def get_device_status(cls, redis: aioredis.Redis, device_id: str) -> dict[str, Any]:
        """合并 Redis 状态/心跳与采集进程存活，返回连接与会话摘要。"""
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
        # 兼容别名
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
            out['sessions'] = await PayloadSessionService.list_sessions(redis)
        if 'parsers' in want:
            out['parsers'] = PayloadSessionService.list_parser_options()
        if 'assemblers' in want:
            out['assemblers'] = PayloadSessionService.list_assembler_options()
        return out
