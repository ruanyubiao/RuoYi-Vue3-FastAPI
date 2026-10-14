"""串口插件注册：plugin_id 来自协议清单，source 的 pluginId 来自连接预设。"""

from __future__ import annotations

import importlib
from functools import cache

from module_payload.collectors.plugins.base import SerialStreamPlugin
from module_payload.protocol.protocol_catalog import SERIAL_STREAM_PLUGINS, serial_stream_plugin

DEFAULT_SERIAL_READ_TIMEOUT = 0.1


@cache
def _load_plugin_cls(module: str) -> type:
    """导入采集插件模块并取 ``PLUGIN``。"""
    mod = importlib.import_module(module)
    cls = getattr(mod, 'PLUGIN', None)
    if cls is None:
        raise ValueError(f'{module} 未导出 PLUGIN')
    return cls


def resolve_plugin_id_for_source(source: str | None) -> str | None:
    """由连接预设的 pluginId 解析应挂载的插件。未登记则返回 None。"""
    from module_payload.cfg.payload_config_loader import PayloadConfigLoader

    src = (source or '').strip()
    if not src:
        return None
    entry = PayloadConfigLoader.get_device_connect_entry(src)
    pid = str(entry.get('pluginId') or '').strip()
    if serial_stream_plugin(pid) is None:
        return None
    return pid


def read_timeout_for_source(source: str | None) -> float:
    """有采集插件时用清单里的读超时，否则用串口默认值。"""
    row = serial_stream_plugin(resolve_plugin_id_for_source(source))
    if row is None:
        return DEFAULT_SERIAL_READ_TIMEOUT
    return row.read_timeout


def create_serial_plugin(plugin_id: str | None) -> SerialStreamPlugin | None:
    """按 plugin_id 创建实例；未知或空则返回 None。"""
    row = serial_stream_plugin(plugin_id)
    if row is None:
        return None
    return _load_plugin_cls(row.module)()


def list_serial_plugins() -> list[dict[str, str]]:
    """已登记采集插件 id 列表（供前端/调试）。"""
    return [{'id': row.id, 'name': row.id} for row in SERIAL_STREAM_PLUGINS]
