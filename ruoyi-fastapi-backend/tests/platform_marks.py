"""跨平台测试标记：仅 Windows 有意义的用例在其它平台自动跳过。"""

from __future__ import annotations

import sys

import pytest

IS_WINDOWS = sys.platform == 'win32'

windows_only = pytest.mark.skipif(
    not IS_WINDOWS,
    reason='仅 Windows：依赖 WindowsPath / LOCALAPPDATA / ctypes.WinDLL 等 Windows 语义',
)
