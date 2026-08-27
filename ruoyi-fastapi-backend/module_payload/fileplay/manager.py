"""文件回放子进程生命周期（仿采集 ``CollectorProcessManager``）。

Windows 下 uvicorn spawn worker 不宜再套 multiprocessing，统一 ``subprocess.Popen``。
切文件只推 ``parse`` 重置会话，不杀进程。子进程秒退或拉起失败时退化为当前进程内
``FilePlayEngine``（单测/异常环境仍能解析，但会占 API 线程）。
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
from typing import Any, TextIO

from module_payload import redis_keys as rk
from module_payload.collectors import process_guard
from module_payload.fileplay.engine import FilePlayEngine

_LOG = logging.getLogger(__name__)
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_WORKER = Path(__file__).resolve().parent / 'worker.py'


class FilePlayManager:
    """长驻文件解析进程：切文件不杀进程，只推 parse 重置会话。"""

    _instance: 'FilePlayManager | None' = None  # 进程内单例，lifespan shutdown 共用

    def __init__(self) -> None:
        self._proc: Popen | None = None  # worker.py 子进程
        self._lock = threading.RLock()
        self._local_engine: FilePlayEngine | None = None  # 子进程不可用时的进程内引擎
        self._use_local = False
        self._log_fp: TextIO | None = None  # 子进程 stdout/stderr 追加到 fileplay_worker.log
        self._redis = None  # 主进程控制队列客户端，shutdown 时关闭
        process_guard.install_shutdown_hooks(self.shutdown)

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
    def instance(cls) -> 'FilePlayManager':
        """进程内单例，供 API / lifespan 共用。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _is_alive(self) -> bool:
        """子进程仍在运行（poll 为 None）。"""
        return self._proc is not None and self._proc.poll() is None

    def _open_worker_log(self) -> TextIO | None:
        """子进程日志落到 ``logs/fileplay_worker.log``，解析失败时便于对照。"""
        try:
            from config.paths import get_logs_dir

            path = get_logs_dir() / 'fileplay_worker.log'
            path.parent.mkdir(parents=True, exist_ok=True)
            self._log_fp = path.open('a', encoding='utf-8')
            return self._log_fp
        except Exception:
            return None

    def _start_local_engine(self) -> None:
        """Popen 失败或子进程秒退：同一进程内解析，结果仍写 Redis Hash。"""
        from module_payload.collectors.redis_sync import create_sync_redis

        self._use_local = True
        self._local_engine = FilePlayEngine(create_sync_redis())
        _LOG.warning('fileplay 使用进程内引擎（子进程不可用）')

    def _wait_worker_heartbeat(self, timeout_s: float = 8.0) -> bool:
        """等子进程写心跳；进程已死则失败。"""
        deadline = time.monotonic() + timeout_s
        r = self._get_redis()
        while time.monotonic() < deadline:
            if not self._is_alive():
                return False
            try:
                if r.get(rk.fileplay_worker_status_key()):
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
            env = os.environ.copy()
            # 与主进程同一 APP_ENV，避免 worker 连到另一套 Redis，主进程永远等不到 meta
            env['APP_ENV'] = os.environ.get('APP_ENV') or 'dev'
            log_fp = self._open_worker_log()
            popen_kwargs: dict[str, Any] = {
                'args': [sys.executable, str(_WORKER)],
                'cwd': str(_BACKEND_ROOT),
                'env': env,
            }
            if log_fp is not None:
                popen_kwargs['stdout'] = log_fp
                popen_kwargs['stderr'] = subprocess.STDOUT
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
                self._local_engine.parse(str(msg.get('type') or ''), str(msg.get('path') or ''))
            elif op == 'ensure':
                self._local_engine.ensure_frame(str(msg.get('pathHash') or ''), int(msg.get('index') or 0))
            elif op == 'curve':
                self._local_engine.curve_points(
                    str(msg.get('pathHash') or ''),
                    [str(f) for f in (msg.get('fields') or [])],
                    start_index=int(msg.get('startIndex') or 1),
                    end_index=msg.get('endIndex'),
                )
            return
        r = self._get_redis()
        r.lpush(rk.fileplay_ctrl_key(), json.dumps(msg, ensure_ascii=False))

    def parse(self, table_type: str, path: str) -> None:
        """通知拆帧。pathHash 一并带上，worker 抛错时也能写 meta=error。"""
        self.send(
            {
                'op': 'parse',
                'type': table_type,
                'path': path,
                'pathHash': rk.fileplay_path_hash(path),
            }
        )

    def ensure_frame(self, path_hash: str, index: int) -> None:
        """通知解析第 N 帧（1-based）；已在 Hash 里则 worker 侧会直接返回缓存。"""
        self.send({'op': 'ensure', 'pathHash': path_hash, 'index': index})

    def shutdown(self) -> None:
        """先 Redis stop，再 wait/kill，关闭日志句柄。lifespan 必须在关 Redis 之前调用。"""
        with self._lock:
            if self._is_alive():
                try:
                    self._get_redis().lpush(
                        rk.fileplay_ctrl_key(), json.dumps({'op': 'stop'}, ensure_ascii=False)
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
            if self._log_fp:
                try:
                    self._log_fp.close()
                except Exception:
                    pass
                self._log_fp = None
