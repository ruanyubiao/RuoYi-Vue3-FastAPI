"""pytest 公共配置：可选扩展标记。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 点名跑 tests/<子目录>/test_*.py 时，pytest 不一定把后端根放进 sys.path。
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from extension_checks import gpcan_available, telemetryparser_available


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line('markers', 'requires_gpcan: 需要 gpcan 扩展')
    config.addinivalue_line('markers', 'requires_telemetryparser: 需要 TeleMetryParser 扩展')
    config.addinivalue_line(
        'markers',
        'virtual_hw: 需要虚拟物理设备（COM1/COM2 或 gpcan DEMO）',
    )


@pytest.fixture
def require_gpcan() -> None:
    if not gpcan_available():
        pytest.skip('gpcan 未安装或无法枚举厂商')


@pytest.fixture
def require_telemetryparser() -> None:
    if not telemetryparser_available():
        pytest.skip('TeleMetryParser 未安装')
