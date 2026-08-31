"""pytest 公共配置：可选扩展标记。"""

from __future__ import annotations

import pytest

from extension_checks import gpcan_available, telemetryparser_available


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line('markers', 'requires_gpcan: 需要 gpcan 扩展')
    config.addinivalue_line('markers', 'requires_telemetryparser: 需要 TeleMetryParser 扩展')


@pytest.fixture
def require_gpcan() -> None:
    if not gpcan_available():
        pytest.skip('gpcan 未安装或无法枚举厂商')


@pytest.fixture
def require_telemetryparser() -> None:
    if not telemetryparser_available():
        pytest.skip('TeleMetryParser 未安装')
