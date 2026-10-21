"""文件回放子进程：绑定一个 pathHash，BRPOP 该文件控制队列。

入口 ``python worker.py history|curve {pathHash}``。Ctrl+C 在 Windows 上忽略，
由主进程 JobObject / stop 命令回收。
命令：parse（拆文件+第 1 帧）、ensure（记下跳转帧，下一批插队）、curve（抽点）、stop（退出循环）。
精确索引后：history 把每一帧解码进 Redis，curve 把万帧块写齐；全部写完才写 parsedDone 并退出。
1 小时无访问由 janitor 回收。禁止 clear_channel。
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
    channel = rk.fileplay_channel(str(msg.get('channel') or ''))
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
            'frameCountExact': False,
            'parsedDone': False,
        },
        channel=channel,
    )


def _queue_len(redis, key: str) -> int:
    try:
        n = redis.llen(key)
    except Exception:
        return 0
    try:
        return int(n or 0)
    except (TypeError, ValueError):
        return 0


def _raise_system_exit(*_args: object) -> None:
    """把 SIGTERM / Ctrl+Break 转成 SystemExit，让 finally 里的清理能跑到。"""
    raise SystemExit(0)


def _cleanup(redis, channel: str, path_hash: str, status_key: str) -> None:
    """删心跳并按 pid 释放槽位。每一步单独吞异常，避免一步失败跳过后面的。"""
    if redis is None:
        try:
            from module_payload.collectors.redis_sync import create_sync_redis

            redis = create_sync_redis()
        except Exception:
            return
    try:
        if status_key:
            redis.delete(status_key)
    except Exception:
        pass
    try:
        from module_payload.fileplay.manager import release_fileplay_slot

        release_fileplay_slot(redis, channel, path_hash, os.getpid())
    except Exception:
        pass
    try:
        redis.close()
    except Exception:
        pass


def main() -> None:
    """子进程入口：忽略 Ctrl+C，由主进程 JobObject 回收。"""
    _bootstrap()
    import signal

    if sys.platform == 'win32':
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, _raise_system_exit)
    else:
        signal.signal(signal.SIGTERM, _raise_system_exit)

    from module_payload import redis_keys as rk

    channel = rk.fileplay_channel(sys.argv[1] if len(sys.argv) > 1 else 'history')
    path_hash = str(sys.argv[2] if len(sys.argv) > 2 else '').strip().lower()
    redis = None
    status_key = rk.fileplay_worker_status_key(path_hash, channel) if path_hash else ''
    try:
        from module_payload.collectors.redis_sync import create_sync_redis, dumps_json
        from module_payload.fileplay.engine import FilePlayEngine, parse_force

        redis = create_sync_redis()
        from module_payload.fileplay import store

        engine = FilePlayEngine(redis, channel=channel)
        ctrl = rk.fileplay_ctrl_key(path_hash, channel)
        if path_hash:
            meta = store.read_meta(redis, path_hash, channel=channel) or {}
            path = str(meta.get('path') or '')
            table = str(meta.get('type') or '')
            if path:
                try:
                    engine.bind_existing(path_hash, path, table)
                except Exception:
                    pass

        _run_loop(redis, engine, store, channel, path_hash, ctrl, status_key, dumps_json, parse_force)
    finally:
        _cleanup(redis, channel, path_hash, status_key)


def _run_loop(redis, engine, store, channel, path_hash, ctrl, status_key, dumps_json, parse_force) -> None:
    while True:
        try:
            redis.set(
                status_key,
                dumps_json({'ts': time.time(), 'alive': True, 'pathHash': path_hash}),
                ex=15,
            )
            item = redis.brpop(ctrl, timeout=1)
        except Exception:
            time.sleep(0.5)
            continue
        if item:
            _raw = item[1] if isinstance(item, (list, tuple)) else item
            try:
                msg = json.loads(_raw)
            except (TypeError, json.JSONDecodeError):
                msg = None
            if isinstance(msg, dict):
                op = str(msg.get('op') or '')
                if op == 'stop':
                    break
                want = str(msg.get('pathHash') or path_hash).strip().lower()
                if path_hash and want and want != path_hash:
                    continue
                try:
                    if op == 'parse':
                        engine.parse(
                            str(msg.get('type') or ''),
                            str(msg.get('path') or ''),
                            force=parse_force(msg.get('force')),
                            parse_id=str(msg.get('parseId') or msg.get('parse_id') or ''),
                        )
                        meta = store.read_meta(redis, path_hash, channel=channel) or {}
                        if str(meta.get('status') or '') == 'error':
                            break
                    elif op == 'ensure':
                        engine.request_jump(str(msg.get('pathHash') or path_hash), int(msg.get('index') or 0))
                    elif op == 'curve':
                        fields = msg.get('fields') or []
                        engine.curve_points(
                            str(msg.get('pathHash') or path_hash),
                            [str(f) for f in fields],
                            chunks=msg.get('chunks'),
                            start_index=int(msg.get('startIndex') or 0),
                            end_index=int(msg['endIndex']) if msg.get('endIndex') not in (None, '') else None,
                        )
                except Exception as e:
                    _write_parse_error(redis, {**msg, 'pathHash': path_hash, 'channel': channel}, e)
                    if op == 'parse':
                        break
        if path_hash:
            if channel == 'history':
                try:
                    engine.fill_missing_frames(path_hash, limit=32)
                except Exception:
                    pass
            if engine.all_frames_parsed() is True and _queue_len(redis, ctrl) == 0:
                meta = store.read_meta(redis, path_hash, channel=channel) or {}
                if str(meta.get('status') or '') != 'error':
                    meta['parsedDone'] = True
                    store.write_meta(redis, path_hash, meta, channel=channel)
                break


if __name__ == '__main__':  # pragma: no cover
    main()
