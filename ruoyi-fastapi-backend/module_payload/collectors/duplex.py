"""全双工 / 半双工：打开连接时写入采集进程 config。"""

from __future__ import annotations

from typing import Any


def coerce_full_duplex(value: Any) -> bool | None:
    """未指定返回 None；否则 True/False。"""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ('', 'none'):
            return None
        return text in ('1', 'true', 'yes', 'on')
    return bool(value)


def resolve_full_duplex(*, source: str | None = None, explicit: Any = None) -> bool:
    """显式值优先；否则按 cfg_device_connect 的 source 条目；默认半双工。"""
    coerced = coerce_full_duplex(explicit)
    if coerced is not None:
        return coerced
    key = (source or '').strip()
    if not key or key.lower() == 'home':
        return False
    try:
        from module_payload.cfg.payload_config_loader import PayloadConfigLoader

        entry = PayloadConfigLoader.get_device_connect_entry(key)
    except Exception:
        return False
    if not isinstance(entry, dict) or 'fullDuplex' not in entry:
        return False
    return bool(coerce_full_duplex(entry.get('fullDuplex')))
