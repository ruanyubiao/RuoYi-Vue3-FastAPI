"""文件回放子进程生命周期（仿采集 ``CollectorProcessManager``）。

Windows 下 uvicorn spawn worker 不宜再套 multiprocessing，统一 ``subprocess.Popen``。
每频道最多 ``MAX_WORKERS`` 个按 pathHash 隔离的子进程；完成后自行退出。
子进程卡住无法合作中断时，只重启该 hash 的进程，不删其它文件的 Redis。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from subprocess import Popen
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collectors import process_guard
from module_payload.fileplay.engine import FilePlayEngine, parse_force

_LOG = logging.getLogger(__name__)
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_WORKER = Path(__file__).resolve().parent / 'worker.py'
_SLOT_GRACE_S = 15.0  # 比等心跳的 8 秒长，避免刚占槽就被收走

_RESERVE_LUA = """
local procs, h = KEYS[1], ARGV[1]
local max, now, grace = tonumber(ARGV[2]), tonumber(ARGV[3]), tonumber(ARGV[4])
for _, f in ipairs(redis.call('HKEYS', procs)) do
  local raw = redis.call('HGET', procs, f)
  local ok, v = pcall(cjson.decode, raw)
  if ok and type(v) == 'table' then
    local ts = tonumber(v.ts) or 0
    if redis.call('EXISTS', ARGV[5] .. f .. ':worker') == 0 and now - ts > grace then
      redis.call('HDEL', procs, f)
    end
  end
end
if redis.call('HEXISTS', procs, h) == 1 then return 'exists' end
if redis.call('HLEN', procs) >= max then return 'busy' end
redis.call('HSET', procs, h, cjson.encode({pid=0, ctime=0, owner=tonumber(ARGV[6]), ts=now}))
return 'reserved'
"""

_RELEASE_LUA = """
local cur = redis.call('HGET', KEYS[1], ARGV[1])
if not cur then return 0 end
local ok, v = pcall(cjson.decode, cur)
if not ok or type(v) ~= 'table' then
  redis.call('HDEL', KEYS[1], ARGV[1])
  return 1
end
if tonumber(v.pid) == tonumber(ARGV[2]) then
  redis.call('HDEL', KEYS[1], ARGV[1])
  return 1
end
return 0
"""


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return str(value or '')


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _hash_fields(redis, key: str) -> list[str]:
    hkeys = getattr(redis, 'hkeys', None)
    raw: Any = None
    if callable(hkeys):
        raw = hkeys(key)
    if raw is None:
        store = getattr(redis, 'h', None)
        if isinstance(store, dict):
            raw = list((store.get(key) or {}).keys())
    out: list[str] = []
    for item in raw or []:
        out.append(_as_text(item))
    return out


def _slot_map(redis, key: str) -> dict[str, str]:
    hgetall = getattr(redis, 'hgetall', None)
    if callable(hgetall):
        raw = hgetall(key) or {}
        return {_as_text(k): _as_text(v) for k, v in raw.items()}
    store = getattr(redis, 'h', None)
    if isinstance(store, dict):
        return {_as_text(k): _as_text(v) for k, v in (store.get(key) or {}).items()}
    return {}


def _key_exists(redis, key: str) -> bool:
    exists = getattr(redis, 'exists', None)
    if callable(exists):
        try:
            return bool(exists(key))
        except Exception:
            return False
    kv = getattr(redis, 'kv', None)
    if isinstance(kv, dict):
        return key in kv
    try:
        return redis.get(key) is not None
    except Exception:
        return False


def _decode_slot(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        data = json.loads(_as_text(raw))
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _reserve_slot_py(redis, key: str, path_hash: str, *, max_n: int, now: float, grace: float, prefix: str, owner: int) -> str:
    for field in list(_hash_fields(redis, key)):
        rec = _decode_slot(redis.hget(key, field))
        if rec is None:
            continue
        ts = float(rec.get('ts') or 0)
        if not _key_exists(redis, f'{prefix}{field}:worker') and now - ts > grace:
            redis.hdel(key, field)
    if path_hash in _hash_fields(redis, key):
        return 'exists'
    if len(_hash_fields(redis, key)) >= max_n:
        return 'busy'
    redis.hset(
        key,
        path_hash,
        json.dumps({'pid': 0, 'ctime': 0, 'owner': owner, 'ts': now}, ensure_ascii=False),
    )
    return 'reserved'


def _release_slot_py(redis, key: str, path_hash: str, pid: int) -> None:
    rec = _decode_slot(redis.hget(key, path_hash))
    if rec is None:
        redis.hdel(key, path_hash)
        return
    if _as_int(rec.get('pid')) == int(pid):
        redis.hdel(key, path_hash)


def release_fileplay_slot(redis, channel: str, path_hash: str, pid: int) -> None:
    """按 pid 释放槽位。pid 不一致时保留，避免删掉后拉起的子进程。"""
    h = (path_hash or '').strip().lower()
    if not h or redis is None:
        return
    key = rk.fileplay_procs_key(channel)
    try:
        redis.eval(_RELEASE_LUA, 1, key, h, int(pid))
        return
    except Exception:
        pass
    try:
        _release_slot_py(redis, key, h, int(pid))
    except Exception:
        pass


class FilePlayManager:
    """按频道调度解析进程：history / curve 各最多 5 个，按 pathHash 隔离。"""

    _instances: dict[str, 'FilePlayManager'] = {}
    ACK_WAIT_S = 0.8  # 等 worker 把 parseId 写进 meta；超时则杀该 hash 进程重开
    MAX_WORKERS = 5
    BUSY_ERROR = '解析队列已满（最多同时解析5个文件）'

    def __init__(self, channel: str = 'history') -> None:
        self.channel = rk.fileplay_channel(channel)
        self._procs: dict[str, Popen] = {}
        self._lock = threading.RLock()
        self._local_engine: FilePlayEngine | None = None  # 测试/全局回退 mock
        self._local_engines: dict[str, FilePlayEngine] = {}
        self._started_at: dict[str, float] = {}
        self._use_local = False
        self._redis = None
        process_guard.install_shutdown_hooks(type(self).shutdown_all)

    def _get_redis(self):
        """主进程共用同步 Redis；worker 子进程另有连接。"""
        if self._redis is None:
            from module_payload.collectors.redis_sync import create_sync_redis

            self._redis = create_sync_redis()
        return self._redis

    def _close_redis(self) -> None:
        r = self._redis
        self._redis = None
        if r is None:
            return
        try:
            r.close()
        except Exception:
            pass

    @classmethod
    def instance(cls, channel: str = 'history') -> 'FilePlayManager':
        """按频道单例。"""
        ch = rk.fileplay_channel(channel)
        inst = cls._instances.get(ch)
        if inst is None:
            inst = cls(ch)
            cls._instances[ch] = inst
        return inst

    @classmethod
    def shutdown_all(cls) -> None:
        """关掉 history / curve 全部子进程。"""
        for inst in list(cls._instances.values()):
            inst.shutdown()
        cls._instances.clear()

    @classmethod
    def wipe_all_channels(cls) -> None:
        """API 启动时清掉上次留下的 meta/Hash，避免残心跳误报已解析完成。"""
        from module_payload.fileplay import store
        from module_payload.collectors.redis_sync import create_sync_redis

        r = create_sync_redis()
        try:
            for ch in rk.FILEPLAY_CHANNELS:
                store.clear_channel(r, ch)
        finally:
            try:
                r.close()
            except Exception:
                pass

    def _norm_hash(self, path_hash: str) -> str:
        return (path_hash or '').strip().lower()

    def _multi_worker(self) -> bool:
        from config.env import AppConfig

        return int(AppConfig.app_workers or 1) > 1

    def _procs_key(self) -> str:
        return rk.fileplay_procs_key(self.channel)

    def _read_slot(self, path_hash: str) -> dict[str, Any] | None:
        h = self._norm_hash(path_hash)
        if not h:
            return None
        try:
            return _decode_slot(self._get_redis().hget(self._procs_key(), h))
        except Exception:
            return None

    def reserve(self, path_hash: str) -> str:
        """占槽。返回 exists / busy / reserved。"""
        h = self._norm_hash(path_hash)
        if not h:
            return 'busy'
        r = self._get_redis()
        key = self._procs_key()
        now = time.time()
        prefix = rk.fileplay_channel_prefix(self.channel)
        try:
            raw = r.eval(
                _RESERVE_LUA,
                1,
                key,
                h,
                self.MAX_WORKERS,
                now,
                _SLOT_GRACE_S,
                prefix,
                os.getpid(),
            )
            return _as_text(raw)
        except Exception:
            return _reserve_slot_py(
                r,
                key,
                h,
                max_n=self.MAX_WORKERS,
                now=now,
                grace=_SLOT_GRACE_S,
                prefix=prefix,
                owner=os.getpid(),
            )

    def release(self, path_hash: str, pid: int) -> None:
        release_fileplay_slot(self._get_redis(), self.channel, path_hash, pid)

    def _write_slot(self, path_hash: str, proc: Popen) -> None:
        pid = _as_int(getattr(proc, 'pid', 0))
        ctime = 0.0
        if pid > 0:
            try:
                import psutil

                ctime = float(psutil.Process(pid).create_time())
            except Exception:
                ctime = 0.0
        payload = json.dumps(
            {'pid': pid, 'ctime': ctime, 'owner': os.getpid(), 'ts': time.time()},
            ensure_ascii=False,
        )
        try:
            self._get_redis().hset(self._procs_key(), path_hash, payload)
        except Exception:
            _LOG.exception('写入 fileplay 槽位失败 %s', path_hash)

    def _reap(self) -> None:
        """丢掉已退出的子进程，并按 pid 释放槽位。"""
        dead = [h for h, p in list(self._procs.items()) if p is None or p.poll() is not None]
        for h in dead:
            proc = self._procs.pop(h, None)
            self._started_at.pop(h, None)
            pid = _as_int(getattr(proc, 'pid', 0)) if proc is not None else 0
            if pid <= 0:
                rec = self._read_slot(h)
                pid = _as_int((rec or {}).get('pid'))
            try:
                self.release(h, pid)
            except Exception:
                pass

    def alive(self, path_hash: str = '') -> bool:
        """指定 hash 是否仍有解析进程。先看本 worker 的 Popen，再看心跳或槽位 pid。"""
        self._reap()
        h = self._norm_hash(path_hash)
        if h:
            proc = self._procs.get(h)
            if proc is not None:
                return proc.poll() is None
            return self._remote_alive(h)
        if any(p.poll() is None for p in self._procs.values()):
            return True
        return bool(_slot_map(self._get_redis(), self._procs_key()))

    def _is_alive(self, path_hash: str = '') -> bool:
        return self.alive(path_hash)

    def _remote_alive(self, path_hash: str) -> bool:
        h = self._norm_hash(path_hash)
        if not h:
            return False
        try:
            r = self._get_redis()
            if _key_exists(r, rk.fileplay_worker_status_key(h, self.channel)):
                return True
        except Exception:
            return False
        rec = self._read_slot(h)
        if not rec:
            return False
        pid = _as_int(rec.get('pid'))
        ctime = float(rec.get('ctime') or 0)
        if pid <= 0:
            return False
        try:
            import psutil

            proc = psutil.Process(pid)
            if ctime and abs(float(proc.create_time()) - ctime) > 1.0:
                return False
            return proc.is_running()
        except Exception:
            return False

    def _slot_hashes(self) -> set[str]:
        hashes = set(self._procs) | set(self._local_engines)
        try:
            hashes.update(_slot_map(self._get_redis(), self._procs_key()))
        except Exception:
            pass
        return hashes

    def worker_count(self) -> int:
        """正在占用的槽位数（本进程 + Redis 槽位 + 进程内引擎）。"""
        self._reap()
        hashes = self._slot_hashes()
        n = len(hashes)
        if self._local_engine is not None and self._local_engine not in self._local_engines.values():
            if not hashes:
                n += 1
        return n

    def can_accept(self, path_hash: str) -> bool:
        """该 hash 已有槽，或尚未满 5 个。"""
        h = self._norm_hash(path_hash)
        if not h:
            return False
        if self.alive(h) or h in self._local_engines or self._read_slot(h):
            return True
        if self._local_engine is not None:
            return self.worker_count() < self.MAX_WORKERS
        return self.worker_count() < self.MAX_WORKERS

    def _start_local_engine(self, path_hash: str) -> FilePlayEngine:
        """Popen 失败：同一进程内解析，结果仍写 Redis Hash，不删其它文件。"""
        h = self._norm_hash(path_hash)
        eng = FilePlayEngine(self._get_redis(), channel=self.channel)
        if h:
            self._local_engines[h] = eng
            self._started_at.setdefault(h, time.time())
        self._use_local = True
        _LOG.warning('fileplay %s/%s 使用进程内引擎（子进程不可用）', self.channel, h)
        return eng

    def _wait_worker_heartbeat(self, path_hash: str, timeout_s: float = 8.0) -> bool:
        """等该 hash 子进程写心跳；进程已死则失败。"""
        h = self._norm_hash(path_hash)
        deadline = time.monotonic() + timeout_s
        r = self._get_redis()
        while time.monotonic() < deadline:
            if not self._is_alive(h):
                return False
            try:
                if r.get(rk.fileplay_worker_status_key(h, self.channel)):
                    return True
            except Exception:
                pass
            time.sleep(0.1)
        return self._is_alive(h)

    def _mark_start_error(self, path_hash: str) -> None:
        from module_payload.fileplay import store

        h = self._norm_hash(path_hash)
        try:
            meta = store.read_meta(self._get_redis(), h, channel=self.channel) or {}
            meta['status'] = 'error'
            meta['error'] = '解析进程启动失败'
            meta['parsedDone'] = False
            store.write_meta(self._get_redis(), h, meta, channel=self.channel)
        except Exception:
            _LOG.exception('写入 fileplay 启动失败状态出错 %s', h)

    def ensure_worker(self, path_hash: str) -> bool:
        """拉起该 hash 的子进程。Popen 留在当前线程（事件循环线程）。

        Linux 的 PR_SET_PDEATHSIG 绑的是调用 Popen 的线程，不能丢进会退出的临时线程。
        多 worker 时拉起失败只写错误并释放槽位，不在 API 进程内解析。
        """
        h = self._norm_hash(path_hash)
        if not h:
            return False
        with self._lock:
            if self._procs.get(h) is not None and self._procs[h].poll() is None:
                return True
            if h in self._local_engines:
                return True
            if self._use_local and self._local_engine is not None and not self._multi_worker():
                self._local_engines.setdefault(h, self._local_engine)
                return True
            if self._remote_alive(h):
                return True
            state = self.reserve(h)
            if state == 'exists':
                return True
            if state != 'reserved':
                return False
            env = os.environ.copy()
            env['APP_ENV'] = os.environ.get('APP_ENV') or 'dev'
            env['PYTHONUNBUFFERED'] = '1'
            popen_kwargs: dict[str, Any] = {
                'args': [sys.executable, str(_WORKER), self.channel, h],
                'cwd': str(_BACKEND_ROOT),
                'env': env,
                'stdout': subprocess.DEVNULL,
                'stderr': subprocess.DEVNULL,
            }
            if sys.platform != 'win32':
                popen_kwargs['preexec_fn'] = process_guard.unix_child_preexec
            else:
                popen_kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                proc = subprocess.Popen(**popen_kwargs)
                process_guard.assign_to_kill_job(proc)
                self._procs[h] = proc
                self._started_at[h] = time.time()
                self._use_local = False
                self._write_slot(h, proc)
            except Exception:
                _LOG.exception('拉起 fileplay 子进程失败')
                self.release(h, 0)
                if self._multi_worker():
                    self._mark_start_error(h)
                    return False
                self._start_local_engine(h)
                return True
            if self._wait_worker_heartbeat(h):
                return True
            if not self.alive(h):
                _LOG.error('fileplay 子进程已退出')
                pid = _as_int(getattr(self._procs.get(h), 'pid', 0))
                self._procs.pop(h, None)
                self.release(h, pid)
                if self._multi_worker():
                    self._mark_start_error(h)
                    return False
                self._start_local_engine(h)
            return True

    def _msg_hash(self, msg: dict[str, Any]) -> str:
        h = str(msg.get('pathHash') or '').strip().lower()
        if h:
            return h
        path = str(msg.get('path') or '')
        if path:
            h = rk.fileplay_path_hash(path)
            msg['pathHash'] = h
            return h
        return ''

    def _dispatch_local(self, engine: FilePlayEngine, msg: dict[str, Any]) -> None:
        op = str(msg.get('op') or '')
        if op == 'parse':
            engine.parse(
                str(msg.get('type') or ''),
                str(msg.get('path') or ''),
                force=parse_force(msg.get('force')),
                parse_id=str(msg.get('parseId') or msg.get('parse_id') or ''),
            )
        elif op == 'ensure':
            engine.ensure_frame(str(msg.get('pathHash') or ''), int(msg.get('index') or 0))
        elif op == 'curve':
            engine.curve_points(
                str(msg.get('pathHash') or ''),
                [str(f) for f in (msg.get('fields') or [])],
                chunks=msg.get('chunks'),
                start_index=int(msg.get('startIndex') or 0),
                end_index=int(msg['endIndex']) if msg.get('endIndex') not in (None, '') else None,
            )

    def send(self, msg: dict[str, Any]) -> bool:
        """向该 hash 控制队列推命令；本地模式则直接执行。满槽且新文件返回 False。"""
        h = self._msg_hash(msg)
        if not h:
            return False
        if not self.can_accept(h):
            return False
        msg = {**msg, 'pathHash': h, 'channel': self.channel}
        if h in self._local_engines or self._local_engine is not None:
            eng = self._local_engines.get(h) or self._local_engine
            if eng is None:
                self.ensure_worker(h)
                eng = self._local_engines.get(h) or self._local_engine
            if eng is not None:
                self._dispatch_local(eng, msg)
                return True
        r = self._get_redis()
        r.lpush(rk.fileplay_ctrl_key(h, self.channel), json.dumps(msg, ensure_ascii=False))
        return self.ensure_worker(h)

    def parse(self, table_type: str, path: str, *, force: bool = False) -> bool:
        """通知该文件拆帧。满 5 个其它文件时返回 False。"""
        path_hash = rk.fileplay_path_hash(path)
        if not self.can_accept(path_hash):
            return False
        parse_id = str(time.time_ns())
        msg = {
            'op': 'parse',
            'type': table_type,
            'path': path,
            'pathHash': path_hash,
            'channel': self.channel,
            'force': 1 if force else 0,
            'parseId': parse_id,
        }
        if not self.send(msg):
            return False
        if self._use_local or path_hash in self._local_engines:
            return True
        if self._wait_parse_ack(path_hash, parse_id):
            return True
        _LOG.warning('fileplay %s/%s 未能迅速中断解析，结束子进程并重开', self.channel, path_hash)
        self._restart_worker(path_hash)
        return self.send(msg)

    def _wait_parse_ack(self, path_hash: str, parse_id: str, timeout_s: float | None = None) -> bool:
        """子进程接到 parse 后会把 parseId 写入该文件 meta。"""
        want = str(parse_id or '')
        if not want:
            return True
        deadline = time.monotonic() + (self.ACK_WAIT_S if timeout_s is None else timeout_s)
        from module_payload.fileplay import store

        r = self._get_redis()
        h = self._norm_hash(path_hash)
        while time.monotonic() < deadline:
            if not self._is_alive(h) and h not in self._local_engines:
                return False
            try:
                meta = store.read_meta(r, h, channel=self.channel) or {}
                if str(meta.get('parseId') or '') == want:
                    return True
            except Exception:
                pass
            time.sleep(0.05)
        return False

    def _restart_worker(self, path_hash: str) -> None:
        """杀掉该 hash 子进程再拉起，用于卡住无法合作中断的解析。"""
        h = self._norm_hash(path_hash)
        self.kill(h)
        self.ensure_worker(h)

    def ensure_frame(self, path_hash: str, index: int) -> bool:
        """通知该文件解析第 N 帧。"""
        return self.send(
            {
                'op': 'ensure',
                'pathHash': path_hash,
                'index': index,
                'channel': self.channel,
            }
        )

    def _kill_pid(self, rec: dict[str, Any] | None) -> None:
        """槽位里的 pid 在 2 秒内没退出，且 create_time 一致时强杀。"""
        if not rec:
            return
        pid = _as_int(rec.get('pid'))
        ctime = float(rec.get('ctime') or 0)
        if pid <= 0:
            return
        try:
            import psutil
        except Exception:
            return
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                if not psutil.pid_exists(pid):
                    return
            except Exception:
                return
            time.sleep(0.05)
        try:
            proc = psutil.Process(pid)
            if ctime and abs(float(proc.create_time()) - ctime) > 1.0:
                return
            proc.kill()
        except Exception:
            return

    def kill(self, path_hash: str) -> None:
        """结束该 hash 的子进程。可以不是本 worker 拉起的。不删会话数据。"""
        h = self._norm_hash(path_hash)
        if not h:
            return
        with self._lock:
            proc = self._procs.pop(h, None)
            self._local_engines.pop(h, None)
            self._started_at.pop(h, None)
        rec = self._read_slot(h)
        if proc is None and rec is None:
            return
        try:
            self._get_redis().lpush(
                rk.fileplay_ctrl_key(h, self.channel),
                json.dumps({'op': 'stop'}, ensure_ascii=False),
            )
        except Exception:
            pass
        if proc is not None:
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        else:
            self._kill_pid(rec)
        pid = _as_int((rec or {}).get('pid'))
        if pid <= 0 and proc is not None:
            pid = _as_int(getattr(proc, 'pid', 0))
        try:
            self.release(h, pid)
        except Exception:
            pass

    def list_live(self) -> list[dict[str, Any]]:
        """当前占用槽位的 hash（含子进程、Redis 槽位与进程内引擎）。"""
        self._reap()
        hashes = self._slot_hashes()
        out: list[dict[str, Any]] = []
        now = time.time()
        for h in hashes:
            out.append(
                {
                    'pathHash': h,
                    'startedAt': int(self._started_at.get(h) or now),
                    'alive': True,
                }
            )
        return out

    def shutdown(self) -> None:
        """先 Redis stop，再 wait/kill。lifespan 必须在关 Redis 之前调用。"""
        with self._lock:
            hashes = list(self._procs.keys())
        for h in hashes:
            self.kill(h)
        with self._lock:
            self._procs.clear()
            self._local_engines.clear()
            self._started_at.clear()
            self._local_engine = None
            self._use_local = False
            self._close_redis()
