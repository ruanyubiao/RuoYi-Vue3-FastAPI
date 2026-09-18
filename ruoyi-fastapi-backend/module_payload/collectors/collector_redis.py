"""采集子进程用的 Redis 封装：写入缓冲 + 定时刷出 + 定时裁剪。

- 写：``write_batch`` 只入内存队列；刷写线程按 ``2ms`` 节拍、满 ``20`` 条、或积压
  超过 ``100`` 条时把**当前缓冲全部**打成 pipeline 一次交互（可跨设备跨 key）。
- 读与需要返回值的命令（``get`` / ``lpop`` / ``incr`` …）同名转发、立刻执行；
  连接池会另借一条连接，不与刷写线程的 pipeline 抢同一条 TCP。
- 有上限的 List / 曲线 ZSet 不在写入路径裁剪，由刷写线程每 ``1s`` 统一 ``LTRIM`` / ``ZREMRANGEBYRANK``。

业务只调 ``write_batch`` 与读接口；命令由
:mod:`module_payload.collectors.redis_cmd_helper` 生成。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Iterable

from module_payload.collectors.redis_cmd_helper import RedisOp, resolve_list_cap, resolve_zset_cap
from module_payload.collectors.redis_sync import create_sync_redis
from module_payload.constants import CURVE_TS_MAX_AHEAD_MS
from module_payload.constants import (
    REDIS_FLUSH_COUNT,
    REDIS_FLUSH_FORCE,
    REDIS_FLUSH_INTERVAL_MS,
    REDIS_PIPE_MAX_OPS,
    REDIS_TRIM_INTERVAL_S,
)

# 追加进有上限 List 的命令；据此登记待裁剪的 key
_APPEND_CMDS = frozenset({'lpush', 'rpush'})


class CollectorRedis:
    """采集进程唯一的 Redis 出口。线程安全：业务线程只碰内存队列。"""

    def __init__(
        self,
        client: Any = None,
        *,
        flush_interval_ms: float = REDIS_FLUSH_INTERVAL_MS,
        flush_count: int = REDIS_FLUSH_COUNT,
        flush_force: int = REDIS_FLUSH_FORCE,
        trim_interval_s: float = REDIS_TRIM_INTERVAL_S,
        pipe_max_ops: int = REDIS_PIPE_MAX_OPS,
        max_pending: int = 0,
        cap_resolver: Callable[[str], int | None] = resolve_list_cap,
        zset_cap_resolver: Callable[[str], int | None] = resolve_zset_cap,
        start_worker: bool = True,
    ) -> None:
        """``client`` 为空则自建同步连接；``start_worker=False`` 供测试手动 ``flush``。"""
        self._client = client if client is not None else create_sync_redis()
        self._flush_interval_s = max(0.0005, float(flush_interval_ms) / 1000.0)
        self._flush_count = max(1, int(flush_count))
        self._flush_force = max(self._flush_count, int(flush_force))
        self._trim_interval_s = max(0.0, float(trim_interval_s))
        self._pipe_max_ops = max(1, int(pipe_max_ops))
        self._max_pending = max(0, int(max_pending))  # 0=不限；Redis 挂了才可能涨
        self._cap_resolver = cap_resolver
        self._zset_cap_resolver = zset_cap_resolver
        self._cond = threading.Condition()  # 保护 _pending / _dirty_lists / _dirty_zsets
        self._exec_lock = threading.Lock()  # 串行化 pipeline 执行，保持 FIFO
        self._pending: list[RedisOp] = []
        self._dirty_lists: dict[str, int] = {}  # 待裁剪 List key -> 上限
        self._dirty_zsets: dict[str, int] = {}  # 待裁剪曲线 ZSet key -> 上限
        self._dropped = 0  # 超出 max_pending 丢弃的命令数
        self._last_trim = time.monotonic()
        self._closed = False
        self._worker: threading.Thread | None = None
        if start_worker:
            self._worker = threading.Thread(target=self._worker_loop, name='redis-flush', daemon=True)
            self._worker.start()

    # ----------------------------------------------------------- 写入（缓冲）
    def write_batch(self, ops: Iterable[RedisOp]) -> None:
        """把命令数组放进缓冲；不阻塞调用方，也不抛异常。"""
        items = list(ops or [])
        if not items or self._closed:
            return
        with self._cond:
            self._pending.extend(items)
            n = len(self._pending)
            if self._max_pending and n > self._max_pending:
                drop = n - self._max_pending
                del self._pending[:drop]  # 丢最旧
                self._dropped += drop
                n = len(self._pending)
            if n >= self._flush_count or n > self._flush_force:
                self._cond.notify()

    def flush(self) -> bool:
        """立刻把缓冲写出（调用方线程执行）。返回是否全部成功。"""
        return self._drain_and_execute()

    @property
    def pending_count(self) -> int:
        """当前缓冲里的命令条数（测试与排查用）。"""
        with self._cond:
            return len(self._pending)

    @property
    def dropped_count(self) -> int:
        """因超出 ``max_pending`` 丢弃的命令数。"""
        return self._dropped

    # ------------------------------------------------- 读 / 需返回值：立刻执行
    def get(self, key: str) -> Any:
        """读字符串键。"""
        return self._client.get(key)

    def mget(self, keys: list[str]) -> Any:
        """批量读字符串键。"""
        return self._client.mget(keys)

    def lpop(self, key: str) -> Any:
        """弹出队首（控制/指令队列）。"""
        return self._client.lpop(key)

    def rpop(self, key: str) -> Any:
        """弹出队尾。"""
        return self._client.rpop(key)

    def lrange(self, key: str, start: int, end: int) -> Any:
        """读 List 区间。"""
        return self._client.lrange(key, start, end)

    def llen(self, key: str) -> Any:
        """List 长度（排查用；写入路径不调）。"""
        return self._client.llen(key)

    def incr(self, key: str) -> Any:
        """自增并返回（预览日志序号）。"""
        return self._client.incr(key)

    def incrby(self, key: str, amount: int) -> Any:
        """按量自增并返回（批量预览日志序号）。"""
        return self._client.incrby(key, amount)

    def exists(self, *keys: str) -> Any:
        """key 是否存在。"""
        return self._client.exists(*keys)

    def ttl(self, key: str) -> Any:
        """剩余 TTL。"""
        return self._client.ttl(key)

    def keys(self, pattern: str) -> Any:
        """按模式列 key（仅排查；批量遍历用 scan_iter）。"""
        return self._client.keys(pattern)

    def scan_iter(self, *args: Any, **kwargs: Any) -> Any:
        """非阻塞遍历 key。"""
        return self._client.scan_iter(*args, **kwargs)

    def hget(self, key: str, field: str) -> Any:
        """读 Hash 字段。"""
        return self._client.hget(key, field)

    def hgetall(self, key: str) -> Any:
        """读整个 Hash。"""
        return self._client.hgetall(key)

    def zrange(self, key: str, start: int, end: int, **kwargs: Any) -> Any:
        """读 ZSet 区间。"""
        return self._client.zrange(key, start, end, **kwargs)

    def zcard(self, key: str) -> Any:
        """ZSet 元素数。"""
        return self._client.zcard(key)

    def ping(self) -> Any:
        """连通性探测。"""
        return self._client.ping()

    # ----------------------------------------------------------- 内部：刷 / 裁
    def _worker_loop(self) -> None:
        """刷写线程：满批被唤醒，否则每 ``flush_interval`` 醒一次，空闲不空转。"""
        while not self._closed:
            with self._cond:
                if len(self._pending) < self._flush_count:
                    self._cond.wait(timeout=self._flush_interval_s)
            self._drain_and_execute()
            self._trim_due()
        self._drain_and_execute()
        self._trim_due(force=True)

    def _drain_and_execute(self) -> bool:
        """取走整个缓冲执行；失败的部分放回队首，下个节拍重试。"""
        with self._cond:
            if not self._pending:
                return True
            ops = self._pending
            self._pending = []
        with self._exec_lock:
            ok, rest = self._execute(ops)
        if rest:
            with self._cond:
                self._pending[:0] = rest
                n = len(self._pending)
                if self._max_pending and n > self._max_pending:
                    drop = n - self._max_pending
                    del self._pending[:drop]
                    self._dropped += drop
        return ok

    def _execute(self, ops: list[RedisOp]) -> tuple[bool, list[RedisOp]]:
        """分段 pipeline 执行；返回 (是否全部成功, 未写出的命令)。"""
        idx = 0
        total = len(ops)
        while idx < total:
            chunk = ops[idx : idx + self._pipe_max_ops]
            try:
                pipe = self._client.pipeline(transaction=False)
                for cmd, args in chunk:
                    getattr(pipe, cmd)(*args)
                pipe.execute()
            except Exception:
                return False, ops[idx:]
            self._note_dirty(chunk)
            idx += len(chunk)
        return True, []

    def _note_dirty(self, ops: list[RedisOp]) -> None:
        """登记本批写过的有上限 List / 曲线 ZSet，供定时裁剪。"""
        dirty_lists: dict[str, int] = {}
        dirty_zsets: dict[str, int] = {}
        for cmd, args in ops:
            if not args:
                continue
            key = str(args[0])
            if cmd in _APPEND_CMDS:
                cap = self._cap_resolver(key)
                if cap:
                    dirty_lists[key] = int(cap)
            elif cmd == 'zadd':
                cap = self._zset_cap_resolver(key)
                if cap:
                    dirty_zsets[key] = int(cap)
        if not dirty_lists and not dirty_zsets:
            return
        with self._cond:
            self._dirty_lists.update(dirty_lists)
            self._dirty_zsets.update(dirty_zsets)

    def _trim_due(self, force: bool = False) -> None:
        """到点对写过的有上限 List / 曲线 ZSet 各裁一次（一次 pipeline）。"""
        now = time.monotonic()
        if not force and now - self._last_trim < self._trim_interval_s:
            return
        self._last_trim = now
        with self._cond:
            if not self._dirty_lists and not self._dirty_zsets:
                return
            dirty_lists = self._dirty_lists
            dirty_zsets = self._dirty_zsets
            self._dirty_lists = {}
            self._dirty_zsets = {}
        with self._exec_lock:
            try:
                pipe = self._client.pipeline(transaction=False)
                for key, cap in dirty_lists.items():
                    pipe.ltrim(key, 0, cap - 1)
                horizon = time.time() * 1000.0 + CURVE_TS_MAX_AHEAD_MS
                for key, cap in dirty_zsets.items():
                    pipe.zremrangebyscore(key, f'({horizon}', '+inf')
                    pipe.zremrangebyrank(key, 0, -(int(cap) + 1))
                pipe.execute()
            except Exception:
                with self._cond:
                    for key, cap in dirty_lists.items():
                        self._dirty_lists.setdefault(key, cap)
                    for key, cap in dirty_zsets.items():
                        self._dirty_zsets.setdefault(key, cap)

    # ----------------------------------------------------------------- 生命周期
    def close(self, flush: bool = True) -> None:
        """排空缓冲、裁一次、停线程并关连接。"""
        if self._closed:
            return
        self._closed = True
        with self._cond:
            self._cond.notify_all()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=2.0)
        self._worker = None
        if flush:
            try:
                self._drain_and_execute()
                self._trim_due(force=True)
            except Exception:
                pass
        try:
            self._client.close()
        except Exception:
            pass


__all__ = ['CollectorRedis']
