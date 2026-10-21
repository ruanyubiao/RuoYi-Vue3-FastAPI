"""回放槽位：占槽、跨实例停止、孤儿会话。"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

from module_payload import redis_keys as rk
from module_payload.fileplay import store
from module_payload.fileplay.janitor import sweep_orphans
from module_payload.fileplay.manager import FilePlayManager


class _Redis:
    def __init__(self) -> None:
        self.h: dict[str, dict[str, str]] = {}
        self.kv: dict[str, str] = {}
        self.lists: dict[str, list] = {}

    def hset(self, key, field=None, value=None, mapping=None):
        bucket = self.h.setdefault(key, {})
        if mapping:
            bucket.update(mapping)
        if field is not None:
            bucket[field] = value

    def hget(self, key, field):
        return self.h.get(key, {}).get(field)

    def hdel(self, key, *fields):
        bucket = self.h.get(key) or {}
        n = 0
        for field in fields:
            if field in bucket:
                bucket.pop(field, None)
                n += 1
        return n

    def hlen(self, key):
        return len(self.h.get(key) or {})

    def set(self, key, value, ex=None):
        self.kv[key] = value

    def get(self, key):
        return self.kv.get(key)

    def delete(self, *keys):
        for key in keys:
            self.h.pop(key, None)
            self.kv.pop(key, None)
            self.lists.pop(key, None)

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def scan(self, cursor=0, match=None, count=None):
        import fnmatch

        keys = list(self.h) + list(self.kv) + list(self.lists)
        if match:
            keys = [k for k in keys if fnmatch.fnmatch(k, match)]
        return 0, keys

    def close(self):
        return None


def _mgr(fake: _Redis) -> FilePlayManager:
    FilePlayManager._instances.clear()
    mgr = FilePlayManager()
    mgr._redis = fake
    return mgr


def test_reserve_exists_busy_and_expired(monkeypatch) -> None:
    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    assert mgr.reserve('a' * 16) == 'reserved'
    assert mgr.reserve('a' * 16) == 'exists'
    for i in range(4):
        assert mgr.reserve(f'{i:016x}') == 'reserved'
    assert mgr.reserve('b' * 16) == 'busy'

    key = rk.fileplay_procs_key('history')
    stale = 'c' * 16
    fake.hset(key, stale, json.dumps({'pid': 1, 'ctime': 1, 'owner': 1, 'ts': time.time() - 30}))
    # 腾出一个名额：删掉一个活槽，过期槽应在下次占槽时被收走
    fake.hdel(key, '0000000000000000')
    assert mgr.reserve('d' * 16) == 'reserved'
    assert stale not in (fake.h.get(key) or {})


def test_release_keeps_newer_pid(monkeypatch) -> None:
    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    h = 'a' * 16
    key = rk.fileplay_procs_key('history')
    fake.hset(key, h, json.dumps({'pid': 9, 'ctime': 1, 'owner': 1, 'ts': time.time()}))
    mgr.release(h, 8)
    assert h in fake.h[key]
    mgr.release(h, 9)
    assert h not in (fake.h.get(key) or {})


def test_kill_reaches_other_manager(monkeypatch) -> None:
    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    owner = _mgr(fake)
    h = 'a' * 16
    proc = MagicMock()
    proc.pid = 42
    proc.poll.return_value = None
    owner._procs[h] = proc
    with patch('psutil.Process', side_effect=ProcessLookupError('gone')):
        owner._write_slot(h, proc)
    other = FilePlayManager()
    other._redis = fake
    with patch('psutil.pid_exists', return_value=False):
        other.kill(h)
    assert fake.lists[rk.fileplay_ctrl_key(h)]
    assert h not in (fake.h.get(rk.fileplay_procs_key('history')) or {})


def test_sweep_orphans_keeps_starting_slot(monkeypatch) -> None:
    fake = _Redis()
    h_old = 'a' * 16
    h_new = 'b' * 16
    store.write_meta(fake, h_old, {'status': 'parsing', 'parsedDone': False})
    fake.set(rk.fileplay_touch_key(h_old), str(int(time.time()) - 60))
    store.write_meta(fake, h_new, {'status': 'parsing', 'parsedDone': False})
    fake.set(rk.fileplay_touch_key(h_new), str(int(time.time()) - 60))
    fake.hset(
        rk.fileplay_procs_key('history'),
        h_new,
        json.dumps({'pid': 0, 'ctime': 0, 'owner': 1, 'ts': time.time()}),
    )
    n = sweep_orphans(fake, now=int(time.time()))
    assert n == 1
    assert store.read_meta(fake, h_old) is None
    assert store.read_meta(fake, h_new) is not None


def test_config_reload_does_not_reset_sessions(tmp_path, monkeypatch) -> None:
    from module_payload.cfg.payload_config_loader import PayloadConfigLoader

    path = tmp_path / 'sample.json'
    path.write_text('{"n": 1}', encoding='utf-8')
    key = 'file:sample'
    PayloadConfigLoader._cache.pop(key, None)
    PayloadConfigLoader._stamp.pop(key, None)
    loads = {'n': 0}

    def _load(file_path):
        loads['n'] += 1
        return {'n': loads['n']}

    monkeypatch.setattr(PayloadConfigLoader, '_load_json', _load)
    with patch('module_payload.protocol.registry.reset_tm_caches') as reset:
        first = PayloadConfigLoader._load_if_stale(key, path)
        PayloadConfigLoader._stamp[key] = (0.0, PayloadConfigLoader._stamp[key][1] - 1)
        second = PayloadConfigLoader._load_if_stale(key, path)
        reset.assert_not_called()
    assert first['n'] == 1
    assert second['n'] == 2


def test_process_layout_warnings(monkeypatch, caplog) -> None:
    import os

    from app import apply_process_layout
    from config.env import AppConfig

    saved = (AppConfig.app_workers, AppConfig.app_reload, AppConfig.collector_embedded)
    env_workers = os.environ.get('APP_WORKERS')
    env_reload = os.environ.get('APP_RELOAD')
    try:
        AppConfig.collector_embedded = True
        AppConfig.app_workers = 4
        AppConfig.app_reload = True
        with caplog.at_level('WARNING'):
            reload, workers = apply_process_layout()
        assert (reload, workers) == (True, 1)
        assert os.environ['APP_WORKERS'] == '1'
        assert '1 个 worker' in caplog.text

        caplog.clear()
        AppConfig.collector_embedded = False
        AppConfig.app_workers = 4
        AppConfig.app_reload = True
        with caplog.at_level('WARNING'):
            reload, workers = apply_process_layout()
        assert (reload, workers) == (False, 4)
        assert os.environ['APP_RELOAD'] == 'false'
        assert '热重载' in caplog.text
    finally:
        AppConfig.app_workers, AppConfig.app_reload, AppConfig.collector_embedded = saved
        if env_workers is None:
            os.environ.pop('APP_WORKERS', None)
        else:
            os.environ['APP_WORKERS'] = env_workers
        if env_reload is None:
            os.environ.pop('APP_RELOAD', None)
        else:
            os.environ['APP_RELOAD'] = env_reload
        AppConfig.app_workers = saved[0]
        AppConfig.app_reload = saved[1]

