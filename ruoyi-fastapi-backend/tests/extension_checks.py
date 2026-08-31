"""地检可选扩展包检测（gpcan、TeleMetryParser）。"""

from __future__ import annotations


def gpcan_available() -> bool:
    """gpcan 是否已安装且可枚举 CAN 厂商。"""
    try:
        from gpcan import CanSdkClient

        return bool(CanSdkClient.get_supported_device_list())
    except Exception:
        return False


def telemetryparser_available() -> bool:
    """TeleMetryParser（telemetryparser wheel）是否已安装。"""
    try:
        from TeleMetryParser import TeleMetryCfgManager

        return TeleMetryCfgManager is not None
    except Exception:
        return False
