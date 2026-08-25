"""遥测配置管理器：热路径 2s 内不重复 stat。"""

from __future__ import annotations

from pathlib import Path

from module_payload.parsers.tm_mgr_cache import TmMgrFileCache


def test_cache_skips_stat_within_interval(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / 'tm.json'
    cfg.write_text('{}', encoding='utf-8')
    cache = TmMgrFileCache(stat_interval_s=10.0)
    stats = {'n': 0}
    real_stat = Path.stat

    def counting_stat(self, *a, **k):
        stats['n'] += 1
        return real_stat(self, *a, **k)

    class _Mgr:
        def init(self, path: str) -> bool:
            return True

    monkeypatch.setattr('TeleMetryParser.TeleMetryCfgManager', _Mgr)
    monkeypatch.setattr(Path, 'stat', counting_stat)

    cache.get(cfg, error='x')
    n1 = stats['n']
    cache.get(cfg, error='x')
    cache.get(cfg, error='x')
    assert stats['n'] == n1

    cache.get(cfg, reload=True, error='x')
    assert stats['n'] > n1


def test_cache_hit_does_not_stringify_path(tmp_path: Path, monkeypatch) -> None:
    """``_ResolvedCfg.__str__`` 会 resolve + is_file；命中缓存时绝不能走到。"""
    cfg = tmp_path / 'tm.json'
    cfg.write_text('{}', encoding='utf-8')
    str_calls = {'n': 0}

    class _PathLike:
        name = cfg.name

        def __str__(self) -> str:
            str_calls['n'] += 1
            return str(cfg)

        def __fspath__(self) -> str:
            str_calls['n'] += 1
            return str(cfg)

    class _Mgr:
        def init(self, path: str) -> bool:
            return True

    monkeypatch.setattr('TeleMetryParser.TeleMetryCfgManager', _Mgr)
    cache = TmMgrFileCache(stat_interval_s=10.0)
    path_like = _PathLike()
    cache.get(path_like, error='x')
    n_after_miss = str_calls['n']
    assert n_after_miss >= 1
    cache.get(path_like, error='x')
    cache.get(path_like, error='x')
    assert str_calls['n'] == n_after_miss
