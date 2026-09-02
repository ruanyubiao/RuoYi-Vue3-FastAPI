"""串口插件注册：plugin_id ↔ 实现；source ↔ plugin_id（工厂懒加载）。"""

from __future__ import annotations

from typing import Callable

from module_payload.collectors.plugins.base import SerialStreamPlugin

PluginFactory = Callable[[], SerialStreamPlugin]

PLUGIN_ID_CAMERA_IMAGE = 'camera_image'

# 会话 source → 插件（v1.6 / v1.7 图像口共用同一拉图插件）
_SOURCE_PLUGIN: dict[str, str] = {
    'camera_image': PLUGIN_ID_CAMERA_IMAGE,
    'camera_image_v17': PLUGIN_ID_CAMERA_IMAGE,
}

_CAMERA_IMAGE_SOURCES = frozenset(_SOURCE_PLUGIN.keys())

def is_camera_image_source(source: str | None) -> bool:
    """是否为相机图像串口来源（需挂载拉图插件、短 read 超时）。"""
    return (source or '').strip() in _CAMERA_IMAGE_SOURCES


def _factory_camera_image() -> SerialStreamPlugin:
    """懒加载相机图像串口插件。"""
    from module_payload.collectors.plugins.camera_image import CameraImageSerialPlugin

    return CameraImageSerialPlugin()


_REGISTRY: dict[str, PluginFactory] = {
    PLUGIN_ID_CAMERA_IMAGE: _factory_camera_image,
}


def resolve_plugin_id_for_source(source: str | None) -> str | None:
    """由会话 source 解析应挂载的插件。"""
    src = (source or '').strip()
    return _SOURCE_PLUGIN.get(src)


def create_serial_plugin(plugin_id: str | None) -> SerialStreamPlugin | None:
    """按 plugin_id 创建实例；未知或空则返回 None。"""
    if not plugin_id:
        return None
    factory = _REGISTRY.get(plugin_id)
    if factory is None:
        return None
    return factory()


def list_serial_plugins() -> list[dict[str, str]]:
    """已注册插件 id 列表（供前端/调试）。"""
    return [{'id': pid, 'name': pid} for pid in sorted(_REGISTRY.keys())]
