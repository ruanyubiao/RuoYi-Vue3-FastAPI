"""虚拟物理设备探测：COM1/COM2 对、gpcan DEMO 厂商。"""

from __future__ import annotations

from typing import Any


def list_serial_port_names() -> set[str]:
    """系统当前串口名（大写）。"""
    try:
        from serial.tools import list_ports
    except Exception:
        return set()
    return {str(p.device).strip().upper() for p in list_ports.comports() if p.device}


def virtual_com_pair() -> tuple[str, str] | None:
    """若同时存在 COM1 与 COM2，视为 Windows 虚拟串口对。"""
    names = list_serial_port_names()
    if 'COM1' in names and 'COM2' in names:
        return 'COM1', 'COM2'
    return None


def gpcan_demo_available() -> bool:
    """gpcan 已安装且枚举到 DEMO/虚拟厂商。"""
    try:
        from gpcan import CanSdkClient, CanVendorType

        vendors = CanSdkClient.get_supported_device_list() or {}
        demo = int(CanVendorType.CAN_VENDOR_DEMO)
        if demo not in vendors:
            return False
        info: Any = vendors[demo]
        name = str(getattr(info, 'name', '') or '')
        return '演示' in name or '虚拟' in name or demo == 0
    except Exception:
        return False
