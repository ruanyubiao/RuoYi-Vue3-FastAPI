"""串口收流插件：按会话 source 动态挂载，与 SerialCollector 解耦。"""

from __future__ import annotations

from module_payload.collectors.plugins.base import (
    FilterResult,
    SerialPluginContext,
    SerialStreamPlugin,
    TickResult,
)

__all__ = [
    'FilterResult',
    'SerialPluginContext',
    'SerialStreamPlugin',
    'TickResult',
    'create_serial_plugin',
    'list_serial_plugins',
    'resolve_plugin_id_for_source',
]


def resolve_plugin_id_for_source(source: str | None) -> str | None:
    """按会话 source 解析应挂载的串口插件 id。"""
    from module_payload.collectors.plugins.registry import resolve_plugin_id_for_source as _resolve

    return _resolve(source)


def create_serial_plugin(plugin_id: str | None):
    """按插件 id 创建实例；未知 id 由 registry 处理。"""
    from module_payload.collectors.plugins.registry import create_serial_plugin as _create

    return _create(plugin_id)


def list_serial_plugins():
    """列出已注册串口收流插件。"""
    from module_payload.collectors.plugins.registry import list_serial_plugins as _list

    return _list()
