"""采集 Redis 封装的测试替身：记录 pipeline 里执行过的命令。"""

from __future__ import annotations

import json
from typing import Any

from module_payload.collectors.collector_redis import CollectorRedis


class FakePipeline:
    """收集命令，``execute`` 时并入客户端；``fail`` 时抛错模拟断连。"""

    def __init__(self, client: 'FakeRedisClient') -> None:
        self._client = client
        self._ops: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str):
        def _call(*args: Any, **_kwargs: Any) -> 'FakePipeline':
            self._ops.append((name, args))
            return self

        return _call

    def execute(self) -> list[Any]:
        if self._client.fail:
            raise RuntimeError('redis down')
        self._client.batches.append(list(self._ops))
        self._client.executed.extend(self._ops)
        self._ops = []
        return []


class FakeRedisClient:
    """只实现封装用到的读命令；写命令都经 pipeline。"""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.batches: list[list[tuple[str, tuple[Any, ...]]]] = []
        self.store: dict[str, Any] = {}
        self.zsets: dict[str, list[Any]] = {}
        self.fail = False
        self.closed = False
        self.reads: list[tuple[str, tuple[Any, ...]]] = []
        self._seq: dict[str, int] = {}

    def pipeline(self, transaction: bool = False) -> FakePipeline:
        return FakePipeline(self)

    def get(self, key: str) -> Any:
        self.reads.append(('get', (key,)))
        return self.store.get(key)

    def lpop(self, key: str) -> Any:
        self.reads.append(('lpop', (key,)))
        items = self.store.get(key)
        return items.pop(0) if items else None

    def rpush(self, key: str, *values: Any) -> int:
        lst = self.store.get(key)
        if not isinstance(lst, list):
            lst = []
            self.store[key] = lst
        lst.extend(values)
        return len(lst)

    def lrange(self, key: str, start: int, end: int) -> Any:
        return list(self.store.get(key) or [])

    def incr(self, key: str) -> int:
        self.reads.append(('incr', (key,)))
        self._seq[key] = self._seq.get(key, 0) + 1
        return self._seq[key]

    def incrby(self, key: str, amount: int) -> int:
        self._seq[key] = self._seq.get(key, 0) + int(amount)
        return self._seq[key]

    def zrange(self, key: str, start: int, end: int, **kwargs: Any) -> Any:
        self.reads.append(('zrange', (key, start, end)))
        items = list(self.zsets.get(key, []))
        if not items:
            return []
        if end < 0:
            end = len(items) + end
        return items[start : end + 1]

    def close(self) -> None:
        self.closed = True


def live_collector_redis_or_skip():
    """真 Redis；ping 失败则 skip。返回 (CollectorRedis, 原始客户端)。"""
    import pytest

    from module_payload.collectors.redis_sync import create_sync_redis

    try:
        raw = create_sync_redis()
        raw.ping()
    except Exception as exc:
        pytest.skip(f'Redis 不可用: {exc}')
    return CollectorRedis(raw, start_worker=False), raw


def fake_collector_redis(**kwargs) -> tuple[CollectorRedis, FakeRedisClient]:
    """构造不起线程的封装：测试显式调用 ``flush()`` 才写出。"""
    fake = FakeRedisClient()
    kwargs.setdefault('start_worker', False)
    return CollectorRedis(fake, **kwargs), fake


_WRITE_TO_PIPE = frozenset({'zadd', 'zremrangebyrank', 'set', 'setex'})


def install_write_batch(redis: Any, pipe: Any = None) -> Any:
    """MagicMock：``write_batch(ops)`` 转到 pipeline（曲线/latest）或 redis（List）。"""

    def _write_batch(ops: list) -> None:
        for cmd, args in ops:
            target = pipe if pipe is not None and cmd in _WRITE_TO_PIPE else redis
            getattr(target, cmd)(*args)

    redis.write_batch.side_effect = _write_batch
    return redis


def executed_ops(fake: FakeRedisClient, cmd: str) -> list[tuple[Any, ...]]:
    """取某个命令的全部参数元组（已 flush 的）。"""
    return [args for name, args in fake.executed if name == cmd]


def lpush_entries(fake: FakeRedisClient, key: str | None = None) -> list[dict[str, Any]]:
    """把 LPUSH 的 JSON 串解析成条目，带 ``_key``。"""
    out: list[dict[str, Any]] = []
    for args in executed_ops(fake, 'lpush'):
        target = args[0]
        if key is not None and target != key:
            continue
        for raw in args[1:]:
            try:
                entry = json.loads(raw)
            except (TypeError, ValueError):
                continue
            entry['_key'] = target
            out.append(entry)
    return out


__all__ = [
    'FakePipeline',
    'FakeRedisClient',
    'executed_ops',
    'fake_collector_redis',
    'install_write_batch',
    'live_collector_redis_or_skip',
    'lpush_entries',
]
