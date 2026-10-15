"""虚拟物理设备探测：COM1/COM2 对、gpcan DEMO 厂商。"""

from __future__ import annotations


def list_serial_port_names() -> set[str]:
    """系统当前串口名（大写）。"""
    try:
        from module_payload.serial_ports import list_ports
    except Exception:
        return set()
    return {str(p.device).strip().upper() for p in list_ports() if getattr(p, 'device', None)}


def virtual_com_pair() -> tuple[str, str] | None:
    """若同时存在 COM1 与 COM2，视为 Windows 虚拟串口对。"""
    names = list_serial_port_names()
    if 'COM1' in names and 'COM2' in names:
        return 'COM1', 'COM2'
    return None


def gpcan_demo_available() -> bool:
    """gpcan 已安装且 DEMO/虚拟厂商（纯 Python）可用。

    不调用 get_supported_device_list：gpcan 1.0.5 在非 Windows 上枚举会因导入
    WinDLL 驱动失败（见 tests/gpcan_compat.py）。
    """
    from gpcan_compat import demo_vendor_info

    info = demo_vendor_info()
    if info is None:
        return False
    name, _count = info
    return '演示' in name or '虚拟' in name
