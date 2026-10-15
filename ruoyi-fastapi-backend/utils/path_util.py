"""跨平台路径小工具（只做增量兼容，Windows 上行为与原逻辑一致）。"""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath


def windows_basename(name: str) -> str:
    """在 ``Path(x).name`` 之后再调用：若仍含 ``\\``（Linux/macOS 不把它当分隔符），按 Windows 规则取文件名。

    Windows 上 ``Path(x).name`` 结果不含 ``\\``，原样返回，行为不变。
    """
    text = str(name or '')
    if '\\' in text:
        return PureWindowsPath(text).name
    return text


def has_parent_ref(path: str) -> bool:
    """路径（``/`` 或 ``\\`` 分隔）中是否有 ``..`` 段。"""
    return any(part == '..' for part in str(path or '').replace('\\', '/').split('/'))


def is_absolute_any(path: str) -> bool:
    """POSIX 绝对路径、Windows 盘符/UNC 绝对路径，任一平台上都识别。"""
    text = str(path or '')
    return os.path.isabs(text) or text.startswith(('/', '\\')) or PureWindowsPath(text).drive != ''


def is_within(base: str | os.PathLike[str], target: str | os.PathLike[str]) -> bool:
    """``target`` 解析后是否位于 ``base`` 之内（大小写按当前文件系统规则）。"""
    try:
        Path(target).resolve().relative_to(Path(base).resolve())
    except (ValueError, OSError):
        return False
    return True
