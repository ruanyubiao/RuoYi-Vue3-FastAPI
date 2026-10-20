"""历史 CAN 表回放：时间解析、会话 Hash、取帧带总数、行转快照。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from module_payload import redis_keys as rk
from module_payload.fileplay import store
from module_payload.service.payload_canplay_service import PayloadCanPlayService, _parse_time_ms


class _FakeRedis:
    def __init__(self) -> None:
        self.h: dict[str, dict[str, str]] = {}

    def hset(self, key, field=None, value=None, mapping=None):
        bucket = self.h.setdefault(key, {})
        if mapping:
            bucket.update(mapping)
        if field is not None:
            bucket[field] = value

    def hget(self, key, field):
        return self.h.get(key, {}).get(field)

    def delete(self, key):
        self.h.pop(key, None)


class _AsyncFakeRedis:
    def __init__(self, inner: _FakeRedis | None = None) -> None:
        self.inner = inner or _FakeRedis()

    async def hget(self, key, field):
        return self.inner.hget(key, field)

    async def hset(self, key, field=None, value=None, mapping=None):
        return self.inner.hset(key, field=field, value=value, mapping=mapping)

    async def expire(self, key, ttl):
        return True


def test_parse_time_ms_formats() -> None:
    """毫秒时间戳、秒时间戳、``YYYY-MM-DD HH:mm:ss`` 均可。"""
    assert _parse_time_ms(1_700_000_000_000) == 1_700_000_000_000
    assert _parse_time_ms(1_700_000_000) == 1_700_000_000_000
    ms = _parse_time_ms('2026-01-01 12:00:00')
    assert ms == _parse_time_ms('2026-01-01T12:00:00')
    with pytest.raises(ValueError, match='时间不能为空'):
        _parse_time_ms('')
    with pytest.raises(ValueError, match='无法解析'):
        _parse_time_ms('not-a-time')


def test_row_to_snap_from_points_json() -> None:
    """无 raw_hex 时用 points_json + parsed_json 拼表快照。"""
    row = SimpleNamespace(
        raw_hex=None,
        parsed_json={'name': '慢遥测'},
        points_json={'A1': 1.5, 'B2': 0},
        ts_ms=1_700_000_000_000,
        src_param='mysql',
    )
    snap = PayloadCanPlayService._row_to_snap(row, 'BIU:FF', 3)
    assert snap['type'] == 'BIU:FF'
    assert snap['name'] == '慢遥测'
    assert snap['frameIndex'] == 3
    assert snap['dataSource'] == 'mysql'
    ids = {r['id'] for r in snap['rows']}
    assert ids == {'A1', 'B2'}
    assert snap['ts']


async def test_open_rejects_inverted_range() -> None:
    """起始晚于结束直接失败，不写 Redis。"""
    with pytest.raises(ValueError, match='起始时间'):
        await PayloadCanPlayService.open(
            SimpleNamespace(),
            _AsyncFakeRedis(),
            'BIU:FF',
            '2026-01-02 00:00:00',
            '2026-01-01 00:00:00',
        )


async def test_open_and_get_frame_includes_count(monkeypatch) -> None:
    """open 把精确帧数写入 canplay Hash；get_frame 每次带回 frameCount。"""

    async def _count(*_a, **_k):
        return 4

    monkeypatch.setattr(
        'module_payload.service.payload_canplay_service.PayloadTmArchiveDao.count_frames',
        _count,
    )
    redis = _AsyncFakeRedis()
    meta = await PayloadCanPlayService.open(
        SimpleNamespace(),
        redis,
        'BIU:FF',
        '2026-01-01 00:00:00',
        '2026-01-01 00:10:00',
    )
    assert meta['frameCount'] == 4
    assert meta['frameCountExact'] is True
    assert meta['status'] == 'ready'
    key = rk.canplay_hash_key(meta['session'])
    assert not key.startswith('payload:tm:')
    snap = {'type': 'BIU:FF', 'rows': [], 'frameIndex': 2}
    redis.inner.hset(key, store.frame_field(2), json.dumps(snap, ensure_ascii=False))
    out = await PayloadCanPlayService.get_frame(SimpleNamespace(), redis, meta['session'], 2)
    assert out['frameCount'] == 4
    assert out['frameCountExact'] is True
    assert out['frame']['frameIndex'] == 2
    assert out['session'] == meta['session']


async def test_get_frame_missing_session() -> None:
    """会话过期或不存在时提示重新解析。"""
    with pytest.raises(ValueError, match='不存在或已过期'):
        await PayloadCanPlayService.get_frame(SimpleNamespace(), _AsyncFakeRedis(), 'dead', 1)


async def test_get_frame_loads_from_dao_when_uncached(monkeypatch) -> None:
    """缓存未命中则按 offset 查 MySQL，再写入 Hash。"""
    row = SimpleNamespace(
        raw_hex=None,
        parsed_json={'name': 't'},
        points_json={'X': 9},
        ts_ms=1_700_000_000_000,
        src_param='can',
    )

    async def _get_at(*_a, **_k):
        return row

    monkeypatch.setattr(
        'module_payload.service.payload_canplay_service.PayloadTmArchiveDao.get_frame_at_offset',
        _get_at,
    )
    inner = _FakeRedis()
    redis = _AsyncFakeRedis(inner)
    meta = {
        'session': 'sess01',
        'type': 'BIU:FF',
        'startMs': 1,
        'endMs': 2,
        'frameCount': 1,
        'frameCountExact': True,
        'status': 'ready',
    }
    key = rk.canplay_hash_key('sess01')
    inner.hset(key, mapping={'meta': json.dumps(meta, ensure_ascii=False)})
    out = await PayloadCanPlayService.get_frame(SimpleNamespace(), redis, 'sess01', 1)
    assert out['frameCount'] == 1
    assert out['frame']['rows'][0]['id'] == 'X'
    cached = store.loads(inner.hget(key, store.frame_field(1)))
    assert cached['frameIndex'] == 1
