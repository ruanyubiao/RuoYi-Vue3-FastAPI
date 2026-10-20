"""采集机本机硬件扫描：串口、CAN 厂商、IPv4。只在监工进程调用。"""

from __future__ import annotations

from typing import Any


def enumerate_serial_ports() -> list[Any]:
    """系统当前串口。失败时由调用方保留上一拍。"""
    from module_payload.collectors.serial_ports import list_ports

    return list_ports()


def pick_default_can_vendor(vendors: list[dict[str, Any]]) -> int:
    """厂商列表默认项：优先 PCIE，否则取第一项。"""
    if not vendors:
        return 0
    for item in vendors:
        text = f"{item.get('key', '')} {item.get('name', '')}".upper()
        if 'PCIE' in text:
            return int(item['value'])
    return int(vendors[0]['value'])


def build_can_vendors() -> list[dict[str, Any]]:
    """gpcan 支持的 CAN 厂商。会导入厂商驱动，只能在采集机上调用。"""
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


def scan_local_addresses() -> list[str]:
    """本机 IPv4。0.0.0.0 与 127.0.0.1 排在前面。"""
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
    special = ['0.0.0.0', '127.0.0.1']
    rest = sorted(a for a in addrs if a not in special)
    return [a for a in special if a in addrs] + rest
