"""主进程 Redis 封装：遥测 latest、序列执行、曲线点。"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from module_payload import redis_keys as rk
from module_payload.redis_store import (
    SEQ_RUN_HISTORY_MAX,
    append_curve_points,
    clear_history,
    get_curve_points,
    get_history,
    get_seq_run,
    get_status,
    get_telemetry_latest,
    list_seq_run_history,
    push_seq_run_history,
    save_seq_run,
    set_telemetry,
)


def _aio(fn):
    def _wrap(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    _wrap.__name__ = fn.__name__
    return _wrap


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.lists: dict[str, list] = {}
        self.zsets: dict[str, list[tuple[str, float]]] = {}

    async def set(self, key, value, ex=None):
        self.kv[key] = value

    async def get(self, key):
        return self.kv.get(key)

    async def delete(self, *keys):
        for key in keys:
            self.kv.pop(key, None)
            self.lists.pop(key, None)

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    async def ltrim(self, key, start, end):
        items = self.lists.get(key, [])
        self.lists[key] = items[start : end + 1]

    async def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        if not items:
            return []
        if end < 0:
            end = len(items) + end
        return items[start : end + 1]

    async def expire(self, key, ttl):
        return True

    def pipeline(self, transaction=False):
        return _Pipe(self)


class _Pipe:
    def __init__(self, r: FakeRedis) -> None:
        self.r = r
        self.ops: list = []

    def zadd(self, key, mapping):
        self.ops.append(('zadd', key, mapping))
        return self

    def zremrangebyrank(self, key, start, end):
        self.ops.append(('zrem', key, start, end))
        return self

    async def execute(self):
        for op in self.ops:
            if op[0] == 'zadd':
                _, key, mapping = op
                bucket = self.r.zsets.setdefault(key, [])
                for member, score in mapping.items():
                    bucket.append((str(member), float(score)))
        self.ops.clear()


@_aio
async def test_set_and_get_telemetry() -> None:
    r = FakeRedis()
    stored = await set_telemetry(
        r,
        'd8',
        [{'id': 'a', 'calc_val': 1.0}],
        name='慢遥',
        src_param='serial:COM4',
    )
    assert stored['type'] == 'D8'
    assert stored['srcKind'] == 'serial'
    latest = await get_telemetry_latest(r, 'D8')
    assert latest['name'] == '慢遥'
    assert await get_status(r, 'serial:COM4') is None


@_aio
async def test_seq_run_roundtrip() -> None:
    r = FakeRedis()
    await save_seq_run(r, {'seqId': 1})  # 无 runId 忽略
    await save_seq_run(r, {'runId': 'r1', 'status': 'running'})
    assert (await get_seq_run(r, 'r1'))['status'] == 'running'
    for i in range(SEQ_RUN_HISTORY_MAX + 5):
        await save_seq_run(r, {'runId': f'r{i}', 'i': i})
        await push_seq_run_history(r, 9, f'r{i}')
    hist = await list_seq_run_history(r, 9, limit=10)
    assert len(hist) == 10
    assert hist[0]['runId'] == f'r{SEQ_RUN_HISTORY_MAX + 4}'


@_aio
async def test_curve_and_history() -> None:
    r = FakeRedis()
    await append_curve_points(
        r,
        'FF',
        [{'id': 'J1', 'calc_val': 3.5}, {'id': 'J2', 'show': 'x'}, {'id': ''}],
        '2026-08-25 08:00:00.000',
    )
    key = rk.curve_latest_key('FF', 'J1')
    assert r.zsets[key]

    class ZRedis(FakeRedis):
        async def zrange(self, key, start, end, withscores=True):
            return list(r.zsets.get(key, []))

        async def zrangebyscore(self, key, min=None, max=None, start=0, num=None, withscores=True):
            return list(r.zsets.get(key, []))

    zr = ZRedis()
    zr.zsets = r.zsets
    pts = await get_curve_points(zr, 'FF', 'J1')
    assert pts[0]['v'] == 3.5

    await r.lpush(rk.history_key('serial:COM1'), '{"a":1}')
    assert await get_history(r, 'serial:COM1') == [{'a': 1}]
    await clear_history(r, 'serial:COM1')
    assert await get_history(r, 'serial:COM1') == []
