# -*- coding: utf-8 -*-
"""历史 CAN 回放（canplay）回归：用 ``tests/data/payload_tm_frame.sql`` 实采归档行。

不连真实 MySQL：把 SQL INSERT 解成内存行，替 DAO 的 count / offset 查询；
``get_frame`` 仍走 ``raw_hex → BiuCanTmIngest.parse_hex`` 真解析。
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from module_payload import redis_keys as rk
from module_payload.fileplay import store
from module_payload.parsers.biu_can_tm import BiuCanTmIngest
from module_payload.service.payload_canplay_service import PayloadCanPlayService
from payload_tm_frame_sql import DEFAULT_SQL, load_archive_rows
from tm_points_assert import assert_points_match_calc

_SQL = DEFAULT_SQL


class _FakeRedis:
    def __init__(self) -> None:
        self.h: dict[str, dict[str, str]] = {}

    def hset(self, key, field=None, value=None, mapping=None):
        bucket = self.h.setdefault(key, {})
        if mapping:
            bucket.update({str(k): str(v) for k, v in mapping.items()})
        if field is not None:
            bucket[str(field)] = value

    def hget(self, key, field):
        return self.h.get(key, {}).get(str(field))

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


@pytest.fixture(scope='module')
def archive_rows() -> list[SimpleNamespace]:
    assert _SQL.is_file(), f'缺少归档夹具 {_SQL}'
    rows = load_archive_rows()
    assert len(rows) >= 5
    return rows


@pytest.fixture
def patch_archive_dao(archive_rows, monkeypatch):
    """用内存行实现 count_frames / get_frame_at_offset。"""

    def _filtered(data_sub: str, start_t: int, end_t: int) -> list[SimpleNamespace]:
        key = (data_sub or '').upper()
        return [r for r in archive_rows if r.data_sub == key and start_t <= r.ts_ms <= end_t]

    async def _count(_db, data_sub: str, start_t: int, end_t: int) -> int:
        return len(_filtered(data_sub, start_t, end_t))

    async def _at_offset(_db, data_sub: str, start_t: int, end_t: int, offset: int):
        rows = _filtered(data_sub, start_t, end_t)
        if offset < 0 or offset >= len(rows):
            return None
        return rows[offset]

    monkeypatch.setattr(
        'module_payload.service.payload_canplay_service.PayloadTmArchiveDao.count_frames',
        _count,
    )
    monkeypatch.setattr(
        'module_payload.service.payload_canplay_service.PayloadTmArchiveDao.get_frame_at_offset',
        _at_offset,
    )
    return archive_rows


def test_payload_tm_frame_sql_covers_biu_types(archive_rows) -> None:
    counts = Counter(r.data_sub for r in archive_rows)
    for need in ('BIU:FF', 'BIU:FD', 'BIU:FB', 'BIU:F9', 'BIU:F7', 'BIU:FE', 'BIU:FC'):
        assert counts.get(need, 0) >= 1, need
    assert counts['BIU:FF'] >= 2


@pytest.mark.asyncio
async def test_canplay_open_counts_from_sql_fixture(patch_archive_dao) -> None:
    rows = patch_archive_dao
    start_ms = min(r.ts_ms for r in rows)
    end_ms = max(r.ts_ms for r in rows)
    redis = _AsyncFakeRedis()

    meta_ff = await PayloadCanPlayService.open(
        SimpleNamespace(), redis, 'BIU:FF', start_ms, end_ms
    )
    expect_ff = sum(1 for r in rows if r.data_sub == 'BIU:FF')
    assert meta_ff['frameCount'] == expect_ff
    assert meta_ff['frameCountExact'] is True
    assert meta_ff['status'] == 'ready'

    meta_fd = await PayloadCanPlayService.open(
        SimpleNamespace(), redis, 'BIU:FD', start_ms, end_ms
    )
    assert meta_fd['frameCount'] == sum(1 for r in rows if r.data_sub == 'BIU:FD')


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'table_type,min_rows',
    [
        ('BIU:FF', 100),
        ('BIU:FD', 50),
        ('BIU:FB', 20),
        ('BIU:F9', 20),
        ('BIU:F7', 20),
        ('BIU:FE', 10),
        ('BIU:FC', 10),
    ],
)
async def test_canplay_get_frame_parses_raw_hex(
    patch_archive_dao, table_type: str, min_rows: int
) -> None:
    """open → get_frame：用归档 raw_hex 真解析出遥测表字段。"""
    rows = [r for r in patch_archive_dao if r.data_sub == table_type]
    assert rows
    start_ms = rows[0].ts_ms
    end_ms = rows[-1].ts_ms
    redis = _AsyncFakeRedis()
    meta = await PayloadCanPlayService.open(
        SimpleNamespace(), redis, table_type, start_ms, end_ms
    )
    assert meta['frameCount'] == len(rows)

    out = await PayloadCanPlayService.get_frame(
        SimpleNamespace(), redis, meta['session'], 1
    )
    assert out['frameCount'] == len(rows)
    frame = out['frame']
    assert frame is not None
    assert frame['type'] == table_type
    assert frame['frameIndex'] == 1
    assert frame['tsMs'] == rows[0].ts_ms
    assert len(frame.get('rows') or []) >= min_rows
    assert any(r.get('id') for r in frame['rows'])
    # 来自 raw_hex 解析时应有表名（非仅 points 回退）
    assert frame.get('name')
    # 归档 points_json（calc_val）与 raw_hex 再解析全键对拍
    parsed = BiuCanTmIngest.parse_hex(rows[0].raw_hex)
    assert_points_match_calc(rows[0].points_json, parsed.fields)
    row_ids = {r['id'] for r in frame['rows']}
    assert set(rows[0].points_json) <= row_ids

    # 缓存命中
    key = rk.canplay_hash_key(meta['session'])
    cached = store.loads(redis.inner.hget(key, store.frame_field(1)))
    assert cached['frameIndex'] == 1


@pytest.mark.asyncio
async def test_canplay_all_archive_rows_match_points_json(patch_archive_dao) -> None:
    """夹具内每一行：canplay get_frame 所用 raw_hex 的 calc_val == points_json。"""
    rows = patch_archive_dao
    start_ms = min(r.ts_ms for r in rows)
    end_ms = max(r.ts_ms for r in rows)
    redis = _AsyncFakeRedis()

    by_type: dict[str, list] = {}
    for r in rows:
        by_type.setdefault(r.data_sub, []).append(r)

    for table_type, typed in by_type.items():
        meta = await PayloadCanPlayService.open(
            SimpleNamespace(), redis, table_type, start_ms, end_ms
        )
        assert meta['frameCount'] == len(typed)
        for i, row in enumerate(typed, start=1):
            out = await PayloadCanPlayService.get_frame(
                SimpleNamespace(), redis, meta['session'], i
            )
            frame = out['frame']
            assert frame is not None
            assert frame['tsMs'] == row.ts_ms
            parsed = BiuCanTmIngest.parse_hex(row.raw_hex)
            assert_points_match_calc(row.points_json, parsed.fields)
            assert set(row.points_json) <= {r['id'] for r in frame['rows']}


@pytest.mark.asyncio
async def test_canplay_ff_second_frame_and_fe_fc(patch_archive_dao) -> None:
    rows = patch_archive_dao
    start_ms = min(r.ts_ms for r in rows)
    end_ms = max(r.ts_ms for r in rows)
    redis = _AsyncFakeRedis()

    meta = await PayloadCanPlayService.open(
        SimpleNamespace(), redis, 'BIU:FF', start_ms, end_ms
    )
    assert meta['frameCount'] >= 2
    f1 = (await PayloadCanPlayService.get_frame(SimpleNamespace(), redis, meta['session'], 1))[
        'frame'
    ]
    f2 = (await PayloadCanPlayService.get_frame(SimpleNamespace(), redis, meta['session'], 2))[
        'frame'
    ]
    assert f1['tsMs'] != f2['tsMs'] or f1['rows'][0].get('value') != f2['rows'][0].get('value')

    for tt, fid, expect in (
        ('BIU:FE', 'JGB1001', 1),
        ('BIU:FC', 'JGB1201', 2),
    ):
        m = await PayloadCanPlayService.open(SimpleNamespace(), redis, tt, start_ms, end_ms)
        assert m['frameCount'] >= 1
        snap = (await PayloadCanPlayService.get_frame(SimpleNamespace(), redis, m['session'], 1))[
            'frame'
        ]
        by_id = {r['id']: r for r in snap['rows']}
        assert by_id[fid]['value'] == expect
