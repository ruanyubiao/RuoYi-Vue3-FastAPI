"""回放占槽 Lua：连真实 Redis。连不上就跳过。只用 db 15，只删 payload:play:file:*。"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest

from module_payload import redis_keys as rk
from module_payload.fileplay.manager import FilePlayManager

URL = os.environ.get('PGT_TEST_REDIS_URL', 'redis://127.0.0.1:6379/15')
_WORKER = Path(__file__).resolve().parents[2] / 'module_payload' / 'fileplay' / 'worker.py'


def _redis_module():
    import redis

    return redis


@pytest.fixture
def real_redis():
    redis = _redis_module()
    client = redis.Redis.from_url(URL, decode_responses=True, socket_connect_timeout=0.5)
    try:
        client.ping()
    except Exception:
        pytest.skip('no redis')
    for key in client.scan_iter('payload:play:file:*'):
        client.delete(key)
    yield client
    for key in client.scan_iter('payload:play:file:*'):
        client.delete(key)
    client.close()


def _manager(client) -> FilePlayManager:
    mgr = FilePlayManager('history')
    mgr._redis = client
    return mgr


def test_lua_reserve_limits_and_release(real_redis, monkeypatch) -> None:
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    distinct: list[str] = []
    lock = threading.Lock()

    def reserve_one(index: int) -> None:
        redis = _redis_module()
        client = redis.Redis.from_url(URL, decode_responses=True, socket_connect_timeout=0.5)
        try:
            state = _manager(client).reserve(f'{index:016x}')
        finally:
            client.close()
        with lock:
            distinct.append(state)

    threads = [threading.Thread(target=reserve_one, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert distinct.count('reserved') == 5
    assert distinct.count('busy') == 15

    real_redis.delete(rk.fileplay_procs_key('history'))
    same: list[str] = []

    def reserve_same() -> None:
        redis = _redis_module()
        client = redis.Redis.from_url(URL, decode_responses=True, socket_connect_timeout=0.5)
        try:
            state = _manager(client).reserve('f' * 16)
        finally:
            client.close()
        with lock:
            same.append(state)

    threads = [threading.Thread(target=reserve_same) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert same.count('reserved') == 1
    assert same.count('exists') == 9

    real_redis.delete(rk.fileplay_procs_key('history'))
    stale = 'c' * 16
    key = rk.fileplay_procs_key('history')
    real_redis.hset(key, stale, '{"pid": 1, "ctime": 1, "owner": 1, "ts": %s}' % (time.time() - 30))
    for index in range(4):
        assert _manager(real_redis).reserve(f'{index:016x}') == 'reserved'
    fresh = 'd' * 16
    assert _manager(real_redis).reserve(fresh) == 'reserved'
    fields = {k.decode() if isinstance(k, bytes) else k for k in real_redis.hkeys(key)}
    assert stale not in fields

    kept = 'e' * 16
    real_redis.hset(key, kept, '{"pid": 9, "ctime": 1, "owner": 1, "ts": %s}' % time.time())
    _manager(real_redis).release(kept, 8)
    assert kept in {k.decode() if isinstance(k, bytes) else k for k in real_redis.hkeys(key)}
    _manager(real_redis).release(kept, 9)
    assert kept not in {k.decode() if isinstance(k, bytes) else k for k in real_redis.hkeys(key)}


@pytest.mark.skipif(sys.platform == 'win32', reason='SIGTERM 清理只在 POSIX 上测')
def test_worker_sigterm_clears_heartbeat(real_redis, monkeypatch) -> None:
    monkeypatch.setattr('module_payload.collectors.process_guard.install_shutdown_hooks', lambda *_a, **_k: None)
    parsed = urlparse(URL)
    env = os.environ.copy()
    env['REDIS_HOST'] = parsed.hostname or '127.0.0.1'
    env['REDIS_PORT'] = str(parsed.port or 6379)
    env['REDIS_DATABASE'] = (parsed.path or '/15').strip('/') or '15'
    if parsed.password:
        env['REDIS_PASSWORD'] = parsed.password
    h = 'ab' * 8
    proc = subprocess.Popen(
        [sys.executable, str(_WORKER), 'history', h],
        cwd=str(_WORKER.parents[2]),
        env=env,
    )
    status = rk.fileplay_worker_status_key(h, 'history')
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not real_redis.get(status):
            time.sleep(0.05)
        assert real_redis.get(status)
        proc.terminate()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and real_redis.get(status):
            time.sleep(0.05)
        assert real_redis.get(status) is None
        fields = {k.decode() if isinstance(k, bytes) else k for k in real_redis.hkeys(rk.fileplay_procs_key('history'))}
        assert h not in fields
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=3)
