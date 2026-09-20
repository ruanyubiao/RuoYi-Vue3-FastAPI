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

    def _reap(self) -> None:
        """丢掉已退出的子进程槽位。"""
        dead = [h for h, p in list(self._procs.items()) if p is None or p.poll() is not None]
        for h in dead:
            self._procs.pop(h, None)
            self._started_at.pop(h, None)

    def _is_alive(self, path_hash: str = '') -> bool:
        """指定 hash 的子进程仍在运行；空 hash 表示是否有任意活进程。"""
        self._reap()
        h = self._norm_hash(path_hash)
        if h:
            proc = self._procs.get(h)
            return proc is not None and proc.poll() is None
        return any(p.poll() is None for p in self._procs.values())

    def worker_count(self) -> int:
        """正在占用的槽位数（活进程 + 进程内引擎）。"""
        self._reap()
        n = len(self._procs) + len(self._local_engines)
        if self._local_engine is not None and self._local_engine not in self._local_engines.values():
            n += 1
        return n

    def can_accept(self, path_hash: str) -> bool:
        """该 hash 已有槽，或尚未满 5 个。"""
        h = self._norm_hash(path_hash)
        if not h:
            return False
        if self._is_alive(h) or h in self._local_engines:
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

    def ensure_worker(self, path_hash: str) -> bool:
        """拉起该 hash 的子进程；起不来或秒退则退化为当前进程内引擎。"""
        h = self._norm_hash(path_hash)
        if not h:
            return False
        with self._lock:
            if self._is_alive(h) or h in self._local_engines:
                return True
            if self._use_local and self._local_engine is not None:
                self._local_engines.setdefault(h, self._local_engine)
                return True
            if not self.can_accept(h):
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
            except Exception:
                _LOG.exception('拉起 fileplay 子进程失败')
                self._start_local_engine(h)
                return True
            if self._wait_worker_heartbeat(h):
                return True
            if not self._is_alive(h):
                _LOG.error('fileplay 子进程已退出，回退进程内解析')
                self._procs.pop(h, None)
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
        with self._lock:
            proc = self._procs.pop(h, None)
            self._local_engines.pop(h, None)
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
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

    def kill(self, path_hash: str) -> None:
        """janitor / 关停：结束该 hash 的子进程，不删 Redis（由调用方删）。"""
        h = self._norm_hash(path_hash)
        with self._lock:
            proc = self._procs.pop(h, None)
            self._local_engines.pop(h, None)
            self._started_at.pop(h, None)
        if proc is None:
            return
        try:
            self._get_redis().lpush(
                rk.fileplay_ctrl_key(h, self.channel),
                json.dumps({'op': 'stop'}, ensure_ascii=False),
            )
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def list_live(self) -> list[dict[str, Any]]:
        """当前占用槽位的 hash（含子进程与进程内引擎）。"""
        self._reap()
        hashes = set(self._procs) | set(self._local_engines)
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
