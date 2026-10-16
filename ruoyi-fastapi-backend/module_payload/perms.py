"""地检接口权限。

查询接口同时接受「专用查询权限」和「已经能打开对应页面的权限」。
已有角色不用等菜单补数就能继续用页面；只读角色只授查询权限，不能发遥控或开关设备。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.aspect.interface_auth import UserInterfaceAuthDependency

if TYPE_CHECKING:
    from fastapi import params

# 首页和各业务页都会读设备。专用查询权限给只读角色；已有页面权限保持现网可用。
_DEVICE_QUERY = [
    'payload:device:query',
    'payload:device:operate',
    'payload:telecontrol:query',
    'payload:telecontrol:send',
    'payload:control:view',
    'payload:sequence:list',
    'payload:camera:view',
    'payload:camera_v17:view',
    'payload:rkdj:view',
    'payload:zk:view',
    'payload:dj:view',
    'payload:cpazx:view',
    'payload:rs422:view',
    'payload:telemetry:view',
    'payload:telemetry:curve',
    'payload:xfer:view',
    'payload:devtest:view',
    'payload:configfile:view',
    'payload:tmcalc:view',
    'payload:refactor:view',
    'payload:lvds:view',
]

# 开关设备、绑定解释器。只认显式操作权限，页面 view 不能开关硬件。
_DEVICE_OPERATE = [
    'payload:device:operate',
]

_TELECONTROL_QUERY = [
    'payload:telecontrol:query',
    'payload:telecontrol:send',
    'payload:control:view',
    'payload:sequence:list',
    'payload:sequence:query',
]

_TELEMETRY_CONFIG = [
    'payload:telemetry:view',
    'payload:telemetry:curve',
    'payload:telemetry:archive',
    'payload:telemetry:canHistory',
    'payload:telemetry:fileHistory',
    'payload:telemetry:fileCurve',
    'payload:tmcalc:view',
    'payload:devtest:view',
    'payload:telecontrol:query',
    'payload:telecontrol:send',
    'payload:camera:view',
    'payload:camera_v17:view',
    'payload:rkdj:view',
    'payload:zk:view',
    'payload:dj:view',
    'payload:cpazx:view',
    'payload:rs422:view',
]

_CAMERA_CONFIG = ['payload:camera:view', 'payload:camera_v17:view']

_BOARD_QUERY = [
    'payload:board:query',
    'payload:camera:view',
    'payload:camera_v17:view',
    'payload:rkdj:view',
    'payload:zk:view',
    'payload:dj:view',
    'payload:cpazx:view',
    'payload:rs422:view',
]

_BOARD_OPERATE = ['payload:telecontrol:send']


def device_query() -> params.Depends:
    """设备只读接口。"""
    return UserInterfaceAuthDependency(_DEVICE_QUERY)


def device_operate() -> params.Depends:
    """打开、关闭、绑定设备。"""
    return UserInterfaceAuthDependency(_DEVICE_OPERATE)


def telecontrol_query() -> params.Depends:
    """遥控配置、指令定义、发送历史。"""
    return UserInterfaceAuthDependency(_TELECONTROL_QUERY)


def telemetry_config() -> params.Depends:
    """遥测表列表与字段定义。"""
    return UserInterfaceAuthDependency(_TELEMETRY_CONFIG)


def camera_config() -> params.Depends:
    """相机遥控/遥测配置。"""
    return UserInterfaceAuthDependency(_CAMERA_CONFIG)


def board_query() -> params.Depends:
    """单板遥控/遥测配置。"""
    return UserInterfaceAuthDependency(_BOARD_QUERY)


def board_operate() -> params.Depends:
    """单板组帧与下发。"""
    return UserInterfaceAuthDependency(_BOARD_OPERATE)
