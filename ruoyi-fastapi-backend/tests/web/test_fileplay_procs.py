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
        self.ttl: dict[str, int] = {}

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
        if ex is not None:
            self.ttl[key] = ex

    def get(self, key):
        return self.kv.get(key)

    def delete(self, *keys):
        for key in keys:
            self.h.pop(key, None)
            self.kv.pop(key, None)
            self.lists.pop(key, None)

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def lrem(self, key, count, value):
        items = self.lists.get(key) or []
        if count == 0:
            kept = [item for item in items if item != value]
        else:
            target = abs(int(count))
            order = range(len(items)) if count > 0 else range(len(items) - 1, -1, -1)
            drop: set[int] = set()
            for index in order:
                if items[index] == value:
                    drop.add(index)
                    if len(drop) >= target:
                        break
            kept = [item for index, item in enumerate(items) if index not in drop]
        self.lists[key] = kept
        return len(items) - len(kept)

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
    fake.hset(
        rk.fileplay_procs_key('history'),
        h,
        json.dumps({'pid': 42, 'ctime': 10.0, 'owner': 1, 'ts': time.time()}),
    )
    other = FilePlayManager()
    other._redis = fake
    with patch('module_payload.fileplay.manager._pid_alive', return_value=False):
        other.kill(h)
    assert json.dumps({'op': 'stop'}) not in (fake.lists.get(rk.fileplay_ctrl_key(h)) or [])
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
        AppConfig.collector_embedded = True
        AppConfig.app_workers = 1
        AppConfig.app_reload = False
        os.environ['APP_WORKERS'] = '1'
        os.environ['APP_RELOAD'] = 'false'
        with caplog.at_level('WARNING'):
            reload, workers = apply_process_layout()
        assert (reload, workers) == (False, 1)
        assert os.environ['APP_WORKERS'] == '1'
        assert os.environ['APP_RELOAD'] == 'false'
        assert '1 个 worker' not in caplog.text

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


def test_kill_then_ensure_relaunches(monkeypatch) -> None:
    """确认退出后心跳被删，紧接着可以再拉起。"""
    import subprocess

    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    monkeypatch.setattr('module_payload.collectors.process_guard.assign_to_kill_job', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    h = 'a' * 16
    proc = MagicMock()
    proc.pid = 42
    proc.poll.return_value = None
    waits = {'n': 0}

    def wait(timeout=None):
        waits['n'] += 1
        if waits['n'] == 1:
            raise subprocess.TimeoutExpired(cmd='fileplay', timeout=timeout or 2)
        return 0

    proc.wait.side_effect = wait
    mgr._procs[h] = proc
    fake.set(rk.fileplay_worker_status_key(h), '{"alive":true}')
    fake.hset(
        rk.fileplay_procs_key('history'),
        h,
        json.dumps({'pid': 42, 'ctime': 10.0, 'owner': 1, 'ts': time.time()}),
    )
    mgr.kill(h)
    assert rk.fileplay_worker_status_key(h) not in fake.kv
    assert h not in (fake.h.get(rk.fileplay_procs_key('history')) or {})
    assert proc.kill.called

    new_proc = MagicMock()
    new_proc.pid = 99
    new_proc.poll.return_value = None
    with (
        patch('subprocess.Popen', return_value=new_proc) as popen,
        patch.object(mgr, '_wait_worker_heartbeat', return_value=True),
        patch('psutil.Process') as ps,
    ):
        ps.return_value.create_time.return_value = 3.0
        assert mgr.ensure_worker(h) is True
        popen.assert_called_once()


def test_pid_zero_within_grace_is_starting(monkeypatch) -> None:
    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    h = 'b' * 16
    fake.hset(
        rk.fileplay_procs_key('history'),
        h,
        json.dumps({'pid': 0, 'ctime': 0, 'owner': 1, 'ts': time.time()}),
    )
    assert mgr._remote_alive(h) is True
    with patch('subprocess.Popen') as popen:
        assert mgr.ensure_worker(h) is True
        popen.assert_not_called()

    fake.hset(
        rk.fileplay_procs_key('history'),
        h,
        json.dumps({'pid': 0, 'ctime': 0, 'owner': 1, 'ts': time.time() - 30}),
    )
    assert mgr._remote_alive(h) is False


def test_remote_alive_prefers_dead_slot_over_heartbeat(monkeypatch) -> None:
    import psutil

    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    h = 'c' * 16
    fake.set(rk.fileplay_worker_status_key(h), '{"alive":true}')
    fake.hset(
        rk.fileplay_procs_key('history'),
        h,
        json.dumps({'pid': 123, 'ctime': 5.0, 'owner': 1, 'ts': time.time()}),
    )
    with patch('psutil.Process', side_effect=psutil.NoSuchProcess(123)):
        assert mgr._remote_alive(h) is False


def test_zombie_kill_returns_without_waiting(monkeypatch) -> None:
    import psutil

    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)

    class Zombie:
        def status(self):
            return psutil.STATUS_ZOMBIE

        def create_time(self):
            return 10.0

        def kill(self):
            raise AssertionError('zombie should not be killed')

    with patch('psutil.Process', return_value=Zombie()):
        started = time.monotonic()
        assert mgr._kill_pid({'pid': 42, 'ctime': 10.0}) is True
        assert time.monotonic() - started < 0.2


def test_ctime_zero_past_grace_is_not_alive_and_not_killed(monkeypatch) -> None:
    import os

    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    h = 'd' * 16
    fake.hset(
        rk.fileplay_procs_key('history'),
        h,
        json.dumps({'pid': os.getpid(), 'ctime': 0, 'owner': 1, 'ts': time.time() - 60}),
    )
    with patch('psutil.Process') as proc_cls:
        proc_cls.return_value.status.return_value = 'running'
        proc_cls.return_value.kill = MagicMock()
        assert mgr._remote_alive(h) is False
        assert mgr._kill_pid({'pid': os.getpid(), 'ctime': 0}) is False
        proc_cls.return_value.kill.assert_not_called()


def test_ctime_zero_uses_heartbeat(monkeypatch) -> None:
    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    h = 'd' * 16
    fake.hset(
        rk.fileplay_procs_key('history'),
        h,
        json.dumps({'pid': 4321, 'ctime': 0, 'owner': 1, 'ts': time.time() - 60}),
    )
    beat = rk.fileplay_worker_status_key(h, 'history')
    fake.set(beat, '1')
    assert mgr._remote_alive(h) is True
    fake.delete(beat)
    assert mgr._remote_alive(h) is False


def test_ctime_zero_within_grace_is_alive(monkeypatch) -> None:
    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    h = 'd' * 16
    fake.hset(
        rk.fileplay_procs_key('history'),
        h,
        json.dumps({'pid': 4321, 'ctime': 0, 'owner': 1, 'ts': time.time()}),
    )
    assert mgr._remote_alive(h) is True


def test_ctime_present_ignores_heartbeat(monkeypatch) -> None:
    import psutil

    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    h = 'd' * 16
    fake.hset(
        rk.fileplay_procs_key('history'),
        h,
        json.dumps({'pid': 4321, 'ctime': 10.0, 'owner': 1, 'ts': time.time() - 60}),
    )
    fake.set(rk.fileplay_worker_status_key(h, 'history'), '1')
    with patch('psutil.Process', side_effect=psutil.NoSuchProcess(4321)):
        assert mgr._remote_alive(h) is False


def test_two_managers_share_one_popen(monkeypatch) -> None:
    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    monkeypatch.setattr('module_payload.collectors.process_guard.assign_to_kill_job', lambda *_a, **_k: None)
    first = _mgr(fake)
    second = FilePlayManager()
    second._redis = fake
    h = 'e' * 16
    proc = MagicMock()
    proc.pid = 77
    proc.poll.return_value = None

    class Live:
        def create_time(self):
            return 5.0

        def status(self):
            return 'running'

    with (
        patch('subprocess.Popen', return_value=proc) as popen,
        patch.object(FilePlayManager, '_wait_worker_heartbeat', return_value=True),
        patch('psutil.Process', return_value=Live()),
    ):
        assert first.ensure_worker(h) is True
        assert second.ensure_worker(h) is True
        popen.assert_called_once()


def test_reap_drops_dead_local_slot(monkeypatch) -> None:
    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    h = 'f' * 16
    proc = MagicMock()
    proc.pid = 7
    proc.poll.return_value = 0
    mgr._procs[h] = proc
    fake.hset(
        rk.fileplay_procs_key('history'),
        h,
        json.dumps({'pid': 7, 'ctime': 1, 'owner': 1, 'ts': time.time()}),
    )
    mgr._reap()
    assert h not in mgr._procs
    assert h not in (fake.h.get(rk.fileplay_procs_key('history')) or {})


def test_single_worker_popen_failure_uses_local_engine(monkeypatch) -> None:
    from config.env import AppConfig

    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    h = '1' * 16
    saved = AppConfig.app_workers
    AppConfig.app_workers = 1
    try:
        with patch('subprocess.Popen', side_effect=OSError('no spawn')):
            assert mgr.ensure_worker(h) is True
    finally:
        AppConfig.app_workers = saved
    assert h in mgr._local_engines


def test_closed_mark_survives_orphan_sweep(monkeypatch) -> None:
    from module_payload.service.payload_fileplay_service import PayloadFilePlayService

    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    FilePlayManager._instances['history'] = mgr
    h = 'a' * 16
    store.write_meta(fake, h, {'status': 'parsing', 'parsedDone': False})
    past = int(time.time()) - 31
    fake.set(rk.fileplay_touch_key(h), str(past))
    monkeypatch.setattr(mgr, 'kill', lambda *_a, **_k: None)
    PayloadFilePlayService.close_session(h, 'history')
    closed = rk.fileplay_closed_key(h)
    assert fake.kv[closed]
    assert fake.ttl[closed] == rk.FILEPLAY_CLOSED_TTL_S
    assert sweep_orphans(fake, now=int(time.time())) == 0
    assert store.read_meta(fake, h) is not None

    fake.delete(closed)
    assert sweep_orphans(fake, now=int(time.time())) == 1
    assert store.read_meta(fake, h) is None

    store.write_meta(fake, h, {'status': 'parsing', 'parsedDone': False})
    fake.set(closed, '1', ex=rk.FILEPLAY_CLOSED_TTL_S)
    store.delete_session(fake, h)
    assert closed not in fake.kv


def test_reserve_eval_error_does_not_fallback(monkeypatch, caplog) -> None:
    import logging

    class Boom(_Redis):
        def eval(self, *_a, **_k):
            raise RuntimeError('lua down')

    fake = Boom()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    monkeypatch.setattr('module_payload.collectors.process_guard.assign_to_kill_job', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    h = 'a' * 16
    with caplog.at_level(logging.ERROR):
        assert mgr.reserve(h) == 'error'
    assert '占槽 Lua' in caplog.text
    assert not fake.h.get(rk.fileplay_procs_key('history'))
    with patch('subprocess.Popen') as popen:
        assert mgr.ensure_worker(h) is False
        popen.assert_not_called()
    assert mgr._slot_error is True


async def test_parse_slot_error_message(tmp_path, monkeypatch) -> None:
    from module_payload.service.payload_fileplay_service import PayloadFilePlayService

    logs = tmp_path / 'logs_data' / 'raw'
    upload = tmp_path / 'log_data'
    logs.mkdir(parents=True)
    upload.mkdir()
    monkeypatch.setattr('module_payload.fileplay.paths.get_logs_data_dir', lambda: logs.parent)
    monkeypatch.setattr('module_payload.fileplay.paths.get_upload_log_data_dir', lambda: upload)
    p = logs / 'slot_recv.txt'
    p.write_text('aa\n', encoding='utf-8')

    class _Mgr:
        _slot_error = True

        def parse(self, *_a, **_k):
            return False

    monkeypatch.setattr(
        'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
        classmethod(lambda cls, channel='history': _Mgr()),
    )

    async def _no_meta(*_a, **_k):
        return {}

    monkeypatch.setattr(PayloadFilePlayService, '_file_meta', _no_meta)
    out = await PayloadFilePlayService.parse(object(), 'BIU:FF', str(p))
    assert out['status'] == 'error'
    assert out['error'] == '回放占槽失败'
    assert '解析队列已满' not in out['error']


def test_worker_cleanup_runs_when_read_meta_fails(monkeypatch) -> None:
    import signal

    from module_payload.fileplay import worker as w

    deleted: list[str] = []
    released: list[tuple] = []
    redis = MagicMock()
    redis.delete.side_effect = lambda *keys: deleted.extend(keys)

    def boom(*_a, **_k):
        raise RuntimeError('meta')

    monkeypatch.setattr(w, '_bootstrap', lambda: None)
    monkeypatch.setattr(w.sys, 'argv', ['worker.py', 'history', 'ab' * 8])
    monkeypatch.setattr(signal, 'signal', lambda *_a, **_k: None)
    monkeypatch.setattr('module_payload.collectors.redis_sync.create_sync_redis', lambda: redis)
    monkeypatch.setattr('module_payload.fileplay.store.read_meta', boom)
    monkeypatch.setattr(
        'module_payload.fileplay.manager.release_fileplay_slot',
        lambda *args, **_k: released.append(args),
    )
    try:
        w.main()
    except RuntimeError as exc:
        assert 'meta' in str(exc)
    else:
        raise AssertionError('read_meta 的异常应该冒出来')
    assert deleted
    assert released


def test_stale_config_clears_derived_only(tmp_path, monkeypatch) -> None:
    from module_payload.cfg.payload_config_loader import PayloadConfigLoader
    from module_payload.protocol.xl.camera.tm import CFG_FILE as CAM_FILE
    from module_payload.protocol.xl.camera.tm import XlCameraTmIngest
    from module_payload.protocol.yj216.rs422 import tm as rs422

    names = dict(XlCameraTmIngest._table_names)
    mux = dict(XlCameraTmIngest._d9_mux_cache)
    spans = rs422._spans
    XlCameraTmIngest._table_names['D8'] = '旧表名'
    XlCameraTmIngest._d9_mux_cache['sess'] = {1: b'\x01'}
    rs422._spans = {'LCWP': 8}
    cam_path = tmp_path / CAM_FILE
    rs_path = tmp_path / rs422.CFG_FILE
    cam_path.write_text('{}', encoding='utf-8')
    rs_path.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(PayloadConfigLoader, '_load_json', lambda _path: {'n': 1})
    try:
        for key, path in (('cam-stale', cam_path), ('rs-stale', rs_path)):
            PayloadConfigLoader._cache.pop(key, None)
            PayloadConfigLoader._stamp.pop(key, None)
            with patch('module_payload.protocol.registry.reset_cfg_derived') as reset:
                PayloadConfigLoader._load_if_stale(key, path)
                reset.assert_not_called()
            PayloadConfigLoader._stamp[key] = (0.0, 0.0)
            PayloadConfigLoader._load_if_stale(key, path)
        assert 'D8' not in XlCameraTmIngest._table_names
        assert XlCameraTmIngest._d9_mux_cache['sess'] == {1: b'\x01'}
        assert rs422._spans is None
    finally:
        XlCameraTmIngest._table_names.clear()
        XlCameraTmIngest._table_names.update(names)
        XlCameraTmIngest._d9_mux_cache.clear()
        XlCameraTmIngest._d9_mux_cache.update(mux)
        rs422._spans = spans
        PayloadConfigLoader._cache.pop('cam-stale', None)
        PayloadConfigLoader._cache.pop('rs-stale', None)
        PayloadConfigLoader._stamp.pop('cam-stale', None)
        PayloadConfigLoader._stamp.pop('rs-stale', None)


def _ctrl(h: str) -> str:
    return rk.fileplay_ctrl_key(h)


def test_send_busy_withdraws_command(monkeypatch) -> None:
    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    h = 'a' * 16
    with patch.object(mgr, 'reserve', return_value='busy'):
        assert mgr.can_accept(h) is True
        assert mgr.send({'op': 'ensure', 'pathHash': h, 'index': 3}) is False
    assert not fake.lists.get(_ctrl(h))


def test_send_error_withdraws_command(monkeypatch) -> None:
    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    h = 'a' * 16
    with patch.object(mgr, 'reserve', return_value='error'):
        assert mgr.send({'op': 'ensure', 'pathHash': h, 'index': 3}) is False
    assert mgr._slot_error is True
    assert not fake.lists.get(_ctrl(h))


def test_send_withdraw_keeps_other_commands(monkeypatch) -> None:
    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    h = 'a' * 16
    other = json.dumps({'op': 'curve', 'pathHash': h, 'keep': 1}, ensure_ascii=False)
    fake.lpush(_ctrl(h), other)
    with patch.object(mgr, 'reserve', return_value='busy'):
        assert mgr.send({'op': 'ensure', 'pathHash': h, 'index': 3}) is False
    assert fake.lists[_ctrl(h)] == [other]


def test_kill_drops_stale_stop(monkeypatch) -> None:
    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    h = 'a' * 16
    proc = MagicMock()
    proc.pid = 42
    proc.wait.return_value = 0
    mgr._procs[h] = proc
    mgr.kill(h)
    assert json.dumps({'op': 'stop'}) not in (fake.lists.get(_ctrl(h)) or [])


def test_janitor_skips_sweep_when_not_leader(monkeypatch) -> None:
    import asyncio

    import pytest

    from config.get_scheduler import SchedulerUtil
    from module_payload.fileplay import janitor

    calls: list[str] = []

    async def to_thread(fn, *args, **kwargs):
        calls.append(fn.__name__)

    async def sleep(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(janitor.asyncio, 'to_thread', to_thread)
    monkeypatch.setattr(janitor.asyncio, 'sleep', sleep)
    monkeypatch.setattr(SchedulerUtil, 'is_leader', staticmethod(lambda: False))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(janitor.janitor_loop())
    assert calls == ['_reap_local']


def test_stale_slots_purged_before_busy(monkeypatch) -> None:
    """Dead Redis procs slots must not keep can_accept busy (queue full vs UI)."""
    fake = _Redis()
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    mgr = _mgr(fake)
    key = rk.fileplay_procs_key('history')
    now = time.time()
    # five dead slots (pid>0 but process gone; ts old)
    for i in range(5):
        h = f'{i:016x}'
        fake.hset(
            key,
            h,
            json.dumps({'pid': 1000 + i, 'ctime': 1.0, 'owner': 1, 'ts': now - 60}),
        )
    monkeypatch.setattr('module_payload.fileplay.manager._pid_alive', lambda *_a, **_k: False)
    assert mgr.worker_count() == 0
    assert mgr.can_accept('d' * 16) is True
    assert mgr.reserve('d' * 16) == 'reserved'

