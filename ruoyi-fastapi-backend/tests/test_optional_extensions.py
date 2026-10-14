"""可选扩展 gpcan / TeleMetryParser 检测与冒烟。"""

from __future__ import annotations

import pytest

from config.paths import resolve_config_file
from extension_checks import gpcan_available, telemetryparser_available
from module_payload.protocol.protocol_catalog import require_bus_family
from module_payload.tm.tm_mgr_cache import TmMgrFileCache
from module_payload.service.device_can import DeviceCanMixin


def test_extension_detection_helpers() -> None:
    """扩展检测函数应返回 bool（不抛异常）。"""
    assert isinstance(gpcan_available(), bool)
    assert isinstance(telemetryparser_available(), bool)


@pytest.mark.requires_gpcan
@pytest.mark.skipif(not gpcan_available(), reason='gpcan 未安装或无法枚举厂商')
def test_gpcan_extension_lists_can_vendors() -> None:
    from gpcan import CanSdkClient

    info_map = CanSdkClient.get_supported_device_list()
    assert info_map, 'gpcan SDK 应返回至少一个厂商'

    result = DeviceCanMixin.list_can_vendors()
    assert result['vendors'], 'gpcan 可用时 list_can_vendors 不应返回空'
    assert result['defaultVendor'] is not None


@pytest.mark.requires_telemetryparser
@pytest.mark.skipif(not telemetryparser_available(), reason='TeleMetryParser 未安装')
def test_telemetryparser_extension_loads_biu_cfg() -> None:
    from TeleMetryParser import TeleMetryCfgManager, parse_line_hex

    cfg_file = resolve_config_file(require_bus_family('biu').telemetry_cfg)
    assert cfg_file.is_file(), 'BIU 遥测配置文件应存在'
    mgr = TmMgrFileCache().get(cfg_file, error='extension test')
    assert mgr is not None
    assert isinstance(TeleMetryCfgManager(), TeleMetryCfgManager)
    assert callable(parse_line_hex)
