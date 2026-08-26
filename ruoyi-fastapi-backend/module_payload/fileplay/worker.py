"""文件回放长驻子进程：BRPOP 控制队列，解析写入 ``payload:fileplay:{hash}``。

入口 ``python worker.py``。Ctrl+C 在 Windows 上忽略，由主进程 JobObject / stop 命令回收。
命令：parse（拆文件+第 1 帧）、ensure（第 N 帧）、curve（抽点）、stop（退出循环）。
解析抛错必须写 meta.status=error，否则前端轮询 /file/status 会一直 parsing 直到超时。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _bootstrap() -> None:
    """cwd / sys.path 对齐后端包根，才能 import module_payload 与 .env。"""
    os.chdir(_BACKEND_ROOT)
    if str(_BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(_BACKEND_ROOT))


def _write_parse_error(redis, msg: dict, err: BaseException) -> None:
    """解析抛错时仍写 meta=error，避免主进程空等到超时。"""
    import traceback

    from module_payload import redis_keys as rk
    from module_payload.fileplay import store

    traceback.print_exc()
    h = str(msg.get('pathHash') or '').strip()
    path = str(msg.get('path') or '')
    if not h and path:
        try:
            from module_payload.fileplay.paths import resolve_play_path

            h = rk.fileplay_path_hash(str(resolve_play_path(path)))
        except Exception:
            h = rk.fileplay_path_hash(path)
    if not h:
        return
    store.write_meta(
        redis,
        h,
        {
            'status': 'error',
            'error': str(err) or type(err).__name__,
            'path': path,
            'type': str(msg.get('type') or ''),
            'frameCount': 0,
            'frameCountExact': True,
        },
    )


def main() -> None:
    """子进程入口：忽略 Ctrl+C，由主进程 JobObject 回收。"""
    _bootstrap()
    if sys.platform == 'win32':
        import signal

        signal.signal(signal.SIGINT, signal.SIG_IGN)

    from module_payload import redis_keys as rk
    from module_payload.collectors.redis_sync import create_sync_redis, dumps_json
    from module_payload.fileplay.engine import FilePlayEngine

    redis = create_sync_redis()
    engine = FilePlayEngine(redis)
    ctrl = rk.fileplay_ctrl_key()
    status_key = rk.fileplay_worker_status_key()
    while True:
        try:
            redis.set(status_key, dumps_json({'ts': time.time(), 'alive': True}), ex=15)
            # timeout=1 以便周期性刷新心跳，主进程 ensure_worker 靠此判断已就绪
            item = redis.brpop(ctrl, timeout=1)
        except Exception:
            time.sleep(0.5)
            continue
        if not item:
            continue
        _raw = item[1] if isinstance(item, (list, tuple)) else item
        try:
            msg = json.loads(_raw)
        except (TypeError, json.JSONDecodeError):
            continue
        op = str(msg.get('op') or '')
        if op == 'stop':
            break
        try:
            if op == 'parse':
                engine.parse(str(msg.get('type') or ''), str(msg.get('path') or ''))
            elif op == 'ensure':
                engine.ensure_frame(str(msg.get('pathHash') or ''), int(msg.get('index') or 0))
            elif op == 'curve':
                fields = msg.get('fields') or []
                engine.curve_points(
                    str(msg.get('pathHash') or ''),
                    [str(f) for f in fields],
                    start_index=int(msg.get('startIndex') or 1),
                    end_index=msg.get('endIndex'),
                )
        except Exception as e:
            _write_parse_error(redis, msg, e)
            continue


if __name__ == '__main__':
    main()
