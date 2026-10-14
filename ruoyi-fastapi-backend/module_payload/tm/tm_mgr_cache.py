"""TeleMetryCfgManager 按文件缓存：热路径不每帧 stat / resolve 配置文件。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

# 热更新最多延迟这么久；reload_tm_cfg 仍可立刻重建
STAT_INTERVAL_S = 2.0


def _cache_key(path: str | Path) -> str:
    """用文件名做 key，避免 ``_ResolvedCfg.__str__`` 每次磁盘探测。"""
    name = getattr(path, 'name', None)
    if isinstance(name, str) and name:
        return name
    return str(path)


def _resolved_path(path: str | Path) -> str:
    """未命中缓存时才解析真实路径。"""
    if hasattr(path, '_p'):
        return str(path)
    p = Path(path)
    if p.is_absolute():
        return str(p)
    from config.paths import resolve_config_file

    return str(resolve_config_file(p.name))


class TmMgrFileCache:
    """单文件 TeleMetryCfgManager 缓存：命中窗口内不 stat，mtime 变化才重建。"""

    __slots__ = ('_mgr', '_key', '_mtime', '_last_stat_mono', 'stat_interval_s')

    def __init__(self, *, stat_interval_s: float = STAT_INTERVAL_S) -> None:
        """stat_interval_s：两次磁盘探测的最短间隔。"""
        self._mgr: Any = None  # 已 init 的 TeleMetryCfgManager
        self._key: str | None = None  # 缓存键（文件名）
        self._mtime: float | None = None  # 上次看到的文件 mtime
        self._last_stat_mono: float = 0.0  # 上次 stat 的单调时钟
        self.stat_interval_s = stat_interval_s  # 热更新探测间隔

    def clear(self) -> None:
        """丢掉管理器，下次 get 重新 init。"""
        self._mgr = None
        self._key = None
        self._mtime = None
        self._last_stat_mono = 0.0

    def get(self, path: str | Path, *, reload: bool = False, error: str = '遥测配置初始化失败') -> Any:
        """取 TeleMetryCfgManager：间隔内直接复用；reload 或 mtime 变则重建。"""
        key = _cache_key(path)
        now = time.monotonic()
        if (
            not reload
            and self._mgr is not None
            and self._key == key
            and (now - self._last_stat_mono) < self.stat_interval_s
        ):
            return self._mgr
        self._last_stat_mono = now
        path_s = _resolved_path(path)
        try:
            mtime = Path(path_s).stat().st_mtime
        except OSError:
            mtime = None
        need = (
            reload
            or self._mgr is None
            or self._key != key
            or (mtime is not None and mtime != self._mtime)
        )
        if need:
            from TeleMetryParser import TeleMetryCfgManager

            # 配置变了才重建；热路径避免每帧 init
            mgr = TeleMetryCfgManager()
            if not mgr.init(path_s):
                raise RuntimeError(error)
            self._mgr = mgr
            self._key = key
            self._mtime = mtime
        return self._mgr
