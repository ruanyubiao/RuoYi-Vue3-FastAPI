"""文件回放子进程生命周期（仿采集 ``CollectorProcessManager``）。

Windows 下 uvicorn spawn worker 不宜再套 multiprocessing，统一 ``subprocess.Popen``。
切文件先推 ``parse`` 尝试中断当前扫描；子进程若不能迅速接上（卡住 index/curve），
则杀掉重开。子进程秒退或拉起失败时退化为当前进程内 ``FilePlayEngine``。
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
    """按频道长驻解析进程：history / curve 各一个，互不删对方 Redis。"""

    _instances: dict[str, 'FilePlayManager'] = {}
    ACK_WAIT_S = 0.8  # 等 worker 把 parseId 写进 meta；超时则杀进程重开

    def __init__(self, channel: str = 'history') -> None:
        self.channel = rk.fileplay_channel(channel)
        self._proc: Popen | None = None
        self._lock = threading.RLock()
        self._local_engine: FilePlayEngine | None = None
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
        """关掉 history / curve 两个子进程。"""
        for inst in list(cls._instances.values()):
            inst.shutdown()
        cls._instances.clear()

    @classmethod
    def wipe_all_channels(cls) -> None:
        """API 启动时清掉上次留下的 meta/Hash，避免 worker 未拉起时误报已解析完成。"""
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

    def _is_alive(self) -> bool:
        """子进程仍在运行（poll 为 None）。"""
        return self._proc is not None and self._proc.poll() is None

    def _start_local_engine(self) -> None:
        """Popen 失败或子进程秒退：同一进程内解析，结果仍写 Redis Hash。"""
        from module_payload.collectors.redis_sync import create_sync_redis
        from module_payload.fileplay import store

        r = create_sync_redis()
        store.clear_channel(r, self.channel)
        self._use_local = True
        self._local_engine = FilePlayEngine(r, channel=self.channel)
        _LOG.warning('fileplay %s 使用进程内引擎（子进程不可用）', self.channel)

    def _wait_worker_heartbeat(self, timeout_s: float = 8.0) -> bool:
        """等子进程写心跳；进程已死则失败。"""
        deadline = time.monotonic() + timeout_s
        r = self._get_redis()
        while time.monotonic() < deadline:
            if not self._is_alive():
                return False
            try:
                if r.get(rk.fileplay_worker_status_key(self.channel)):
                    return True
            except Exception:
                pass
            time.sleep(0.1)
        return self._is_alive()

    def ensure_worker(self) -> None:
        """拉起子进程；起不来或秒退则退化为当前进程内引擎。"""
        with self._lock:
            if self._is_alive() or (self._use_local and self._local_engine is not None):
                return
            from module_payload.fileplay import store

            try:
                store.clear_channel(self._get_redis(), self.channel)
            except Exception:
                _LOG.exception('fileplay %s 清理残余 Redis 失败', self.channel)
            env = os.environ.copy()
            # 与主进程同一 APP_ENV，避免 worker 连到另一套 Redis，主进程永远等不到 meta
            env['APP_ENV'] = os.environ.get('APP_ENV') or 'dev'
            env['PYTHONUNBUFFERED'] = '1'
            popen_kwargs: dict[str, Any] = {
                'args': [sys.executable, str(_WORKER), self.channel],
                'cwd': str(_BACKEND_ROOT),
                'env': env,
                'stdout': subprocess.DEVNULL,
                'stderr': subprocess.DEVNULL,
            }
            if sys.platform != 'win32':
                popen_kwargs['preexec_fn'] = process_guard.unix_child_preexec
            else:
                # 独立进程组：控制台 Ctrl+C 只打到主进程，避免 worker 半截刷堆栈
                popen_kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                proc = subprocess.Popen(**popen_kwargs)
                process_guard.assign_to_kill_job(proc)
                self._proc = proc
                self._use_local = False
            except Exception:
                _LOG.exception('拉起 fileplay 子进程失败')
                self._start_local_engine()
                return
            if self._wait_worker_heartbeat():
                return
            if not self._is_alive():
                _LOG.error('fileplay 子进程已退出，回退进程内解析')
                self._proc = None
                self._start_local_engine()

    def send(self, msg: dict[str, Any]) -> None:
        """向子进程控制队列推命令；本地模式则直接执行。"""
        self.ensure_worker()
        if self._use_local and self._local_engine is not None:
            op = str(msg.get('op') or '')
            if op == 'parse':
                self._local_engine.parse(
                    str(msg.get('type') or ''),
                    str(msg.get('path') or ''),
                    force=parse_force(msg.get('force')),
                    parse_id=str(msg.get('parseId') or msg.get('parse_id') or ''),
                )
            elif op == 'ensure':
                self._local_engine.ensure_frame(str(msg.get('pathHash') or ''), int(msg.get('index') or 0))
            elif op == 'curve':
                self._local_engine.curve_points(
                    str(msg.get('pathHash') or ''),
                    [str(f) for f in (msg.get('fields') or [])],
                    chunks=msg.get('chunks'),
                    start_index=int(msg.get('startIndex') or 0),
                    end_index=int(msg['endIndex']) if msg.get('endIndex') not in (None, '') else None,
                )
            return
        r = self._get_redis()
        r.lpush(rk.fileplay_ctrl_key(getattr(self, 'channel', 'history')), json.dumps(msg, ensure_ascii=False))

    def parse(self, table_type: str, path: str, *, force: bool = False) -> None:
        """通知本频道拆帧。能迅速中断则复用进程；否则杀子进程重开。"""
        parse_id = str(time.time_ns())
        msg = {
            'op': 'parse',
            'type': table_type,
            'path': path,
            'pathHash': rk.fileplay_path_hash(path),
            'channel': getattr(self, 'channel', 'history'),
            'force': 1 if force else 0,
            'parseId': parse_id,
        }
        self.send(msg)
        if self._use_local:
            return
        if self._wait_parse_ack(parse_id):
            return
        _LOG.warning('fileplay %s 未能迅速中断解析，结束子进程并重开', self.channel)
        self._restart_worker()
        self.send(msg)

    def _wait_parse_ack(self, parse_id: str, timeout_s: float | None = None) -> bool:
        """子进程接到 parse 后会把 parseId 写入 meta。"""
        want = str(parse_id or '')
        if not want:
            return True
        deadline = time.monotonic() + (self.ACK_WAIT_S if timeout_s is None else timeout_s)
        from module_payload.fileplay import store

        r = self._get_redis()
        while time.monotonic() < deadline:
            if not self._is_alive():
                return False
            try:
                meta = store.read_channel_meta(r, channel=self.channel) or {}
                if str(meta.get('parseId') or '') == want:
                    return True
            except Exception:
                pass
            time.sleep(0.05)
        return False

    def _restart_worker(self) -> None:
        """杀掉当前子进程再拉起，用于卡住无法合作中断的解析。"""
        with self._lock:
            proc = self._proc
            self._proc = None
            self._local_engine = None
            self._use_local = False
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        self.ensure_worker()

    def ensure_frame(self, path_hash: str, index: int) -> None:
        """通知本频道解析第 N 帧。"""
        self.send(
            {
                'op': 'ensure',
                'pathHash': path_hash,
                'index': index,
                'channel': getattr(self, 'channel', 'history'),
            }
        )

    def shutdown(self) -> None:
        """先 Redis stop，再 wait/kill。lifespan 必须在关 Redis 之前调用。"""
        with self._lock:
            if self._is_alive():
                try:
                    self._get_redis().lpush(
                        rk.fileplay_ctrl_key(getattr(self, 'channel', 'history')),
                        json.dumps({'op': 'stop'}, ensure_ascii=False),
                    )
                except Exception:
                    pass
                try:
                    self._proc.wait(timeout=2)
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
            self._proc = None
            self._local_engine = None
            self._use_local = False
            self._close_redis()
