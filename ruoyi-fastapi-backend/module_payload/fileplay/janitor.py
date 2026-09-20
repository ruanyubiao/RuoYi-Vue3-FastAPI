"""历史文件 Redis 缓存清理：与解析子进程脱钩。

按频道、按 pathHash 的 touch 键判断空闲；超过 IDLE_S 未访问则删除该文件缓存并杀掉对应 worker。
"""

from __future__ import annotations

import asyncio
import logging
import time

from module_payload import redis_keys as rk
from module_payload.fileplay import store

_LOG = logging.getLogger(__name__)

IDLE_S = 3600
INTERVAL_S = 60

_task: asyncio.Task | None = None


def sweep_idle(redis=None, *, now: int | None = None, idle_s: int = IDLE_S) -> int:
    """扫描 touch 键，过期则 delete_session + kill worker。返回清理的文件数。"""
    from module_payload.collectors.redis_sync import create_sync_redis
    from module_payload.fileplay.manager import FilePlayManager

    own = redis is None
    r = redis or create_sync_redis()
    ts_now = int(now if now is not None else time.time())
    dropped = 0
    try:
        for ch in rk.FILEPLAY_CHANNELS:
            pattern = f'{rk.fileplay_channel_prefix(ch)}*:touch'
            for key in store._scan_keys(r, pattern):
                raw = r.get(key)
                try:
                    last = int(raw)
                except (TypeError, ValueError):
                    last = 0
                if last and ts_now - last < idle_s:
                    continue
                h = rk.fileplay_hash_from_leaf_key(key)
                if not h:
                    continue
                store.delete_session(r, h, channel=ch)
                try:
                    FilePlayManager.instance(ch).kill(h)
                except Exception:
                    _LOG.exception('fileplay janitor kill %s/%s 失败', ch, h)
                dropped += 1
    finally:
        if own:
            try:
                r.close()
            except Exception:
                pass
    return dropped


async def janitor_loop() -> None:
    """后台循环：INTERVAL_S 扫一次。"""
    while True:
        try:
            await asyncio.to_thread(sweep_idle)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOG.exception('fileplay janitor 扫描失败')
        await asyncio.sleep(INTERVAL_S)


def start_fileplay_janitor(app) -> asyncio.Task:
    """挂到 FastAPI app.state。"""
    global _task
    task = asyncio.create_task(janitor_loop(), name='fileplay-janitor')
    _task = task
    try:
        app.state.fileplay_janitor_task = task
    except Exception:
        pass
    return task


async def stop_fileplay_janitor(app=None) -> None:
    """取消 janitor 任务。"""
    global _task
    task = None
    if app is not None:
        task = getattr(app.state, 'fileplay_janitor_task', None)
    task = task or _task
    _task = None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
