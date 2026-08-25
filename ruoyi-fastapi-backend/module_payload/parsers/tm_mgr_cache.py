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
    __slots__ = ('_mgr', '_key', '_mtime', '_last_stat_mono', 'stat_interval_s')

    def __init__(self, *, stat_interval_s: float = STAT_INTERVAL_S) -> None:
        self._mgr: Any = None
        self._key: str | None = None
        self._mtime: float | None = None
        self._last_stat_mono: float = 0.0
        self.stat_interval_s = stat_interval_s

    def clear(self) -> None:
        self._mgr = None
        self._key = None
        self._mtime = None
        self._last_stat_mono = 0.0

    def get(self, path: str | Path, *, reload: bool = False, error: str = '遥测配置初始化失败') -> Any:
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

            mgr = TeleMetryCfgManager()
            if not mgr.init(path_s):
                raise RuntimeError(error)
            self._mgr = mgr
            self._key = key
            self._mtime = mtime
        return self._mgr
