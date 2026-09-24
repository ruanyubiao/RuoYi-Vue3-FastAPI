"""系统串口列表：pyserial 枚举一次，Windows 注册表再补一次，按端口名去重。

连接与收发仍使用 pyserial.Serial，这里只负责列出端口。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def list_ports() -> list[Any]:
    """返回带 ``device`` / ``description`` 的端口对象。

    pyserial 已给出的端口保留原对象；仅注册表有的端口补一条空描述。
    pyserial 抛错且两边都没有结果时，把该异常抛出，调用方按枚举失败处理。
    """
    found: dict[str, Any] = {}
    pyserial_error: Exception | None = None
    try:
        for item in _ports_from_pyserial():
            name = str(getattr(item, 'device', '') or '').strip()
            if name:
                found.setdefault(name.upper(), item)
    except Exception as exc:
        pyserial_error = exc
    for name in _ports_from_registry():
        text = str(name or '').strip()
        if not text:
            continue
        found.setdefault(text.upper(), SimpleNamespace(device=text, description=''))
    if pyserial_error is not None and not found:
        raise pyserial_error
    return list(found.values())


def _ports_from_pyserial() -> list[Any]:
    from serial.tools import list_ports

    return list(list_ports.comports())


def _ports_from_registry() -> list[str]:
    """``HKLM\\HARDWARE\\DEVICEMAP\\SERIALCOMM``。非 Windows 或没有该项时为空。"""
    try:
        import winreg
    except ImportError:
        return []
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DEVICEMAP\SERIALCOMM')
    except OSError:
        return []
    ports: list[str] = []
    try:
        index = 0
        while True:
            try:
                _name, value, _typ = winreg.EnumValue(key, index)
            except OSError:
                break
            text = str(value or '').strip()
            if text:
                ports.append(text)
            index += 1
    finally:
        winreg.CloseKey(key)
    return ports
