"""配置服务门面与遥测表查询（假 Redis）。"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.service.payload_telemetry_service import PayloadTelemetryService


def _aio(fn):
    def _wrap(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    _wrap.__name__ = fn.__name__
    return _wrap


def test_config_service_telecontrol_and_pages() -> None:
    tc = PayloadConfigService.get_telecontrol_config(family='biu')
    assert tc['family'] == 'biu'
    assert isinstance(tc['order'], dict)
    pages = PayloadConfigService.get_telemetry_pages(family='xl')
    assert pages['page']
    cam = PayloadConfigService.get_camera_telecontrol_config()
    assert cam['order']
    board = PayloadConfigService.get_xl_board_telecontrol_config('rkdj')
    assert board['board'] == 'rkdj'
    assert board['tableKey'] == 'RKDJ'


def test_get_fields_from_table() -> None:
    fields = PayloadTelemetryService.get_fields('D8')
    assert fields
    assert all(f['id'] for f in fields)


@_aio
async def test_get_table_empty_with_and_without_cfg() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    empty = await PayloadTelemetryService.get_table(redis, 'D8', need_cfg=False)
    assert empty.get('dataId') is None
    assert empty['changed'] is False
    assert empty['srcParam'] == ''
    assert empty['fps'] == 0
    for dropped in ('connected', 'dataKind', 'dataSub', 'srcKind', 'dataSource', 'parserId', 'cfgSource'):
        assert dropped not in empty
    with_cfg = await PayloadTelemetryService.get_table(redis, 'D8', need_cfg=True)
    assert with_cfg['changed'] is True
    assert 'rows' in with_cfg
    stale = await PayloadTelemetryService.get_table(redis, 'D8', data_id='old', need_cfg=False)
    assert stale['changed'] is True
    assert stale['rows'] == []


@_aio
async def test_get_table_same_id_skips_rows() -> None:
    payload = {
        'ts': 't',
        'dataId': 99,
        'name': 'n',
        'fields': [{'id': 'a', 'name': 'A', 'value': 1, 'show': '1', 'unit': '', 'hex': '01'}],
        'dataKind': 'tm',
        'dataSub': 'D8',
        'srcKind': 'serial',
        'srcParam': 'serial:COM4',
        'parserId': 'tm_xl_camera',
    }
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=json.dumps(payload))
    same = await PayloadTelemetryService.get_table(redis, 'D8', data_id='99')
    assert same['changed'] is False
    assert 'rows' not in same
    assert same['srcParam'] == 'serial:COM4'
    assert same['fps'] == 0
    for dropped in ('dataSub', 'dataSource', 'connected', 'dataKind', 'srcKind', 'parserId', 'cfgSource'):
        assert dropped not in same
    changed = await PayloadTelemetryService.get_table(redis, 'D8', data_id='1')
    assert changed['changed'] is True
    assert changed['rows'][0]['id'] == 'a'
    assert changed['srcParam'] == 'serial:COM4'


@_aio
async def test_get_table_non_live_skips_redis() -> None:
    """db/file 不读 Redis 热层，即使热层有实时帧也不回填。"""
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=AssertionError('non-live must not touch Redis'))
    db_out = await PayloadTelemetryService.get_table(redis, 'D8', need_cfg=True, source='db')
    assert db_out.get('dataId') is None
    assert db_out['srcParam'] == ''
    assert 'connected' not in db_out
    assert all(not (r.get('show') or r.get('value')) for r in db_out.get('rows') or [])
    file_out = await PayloadTelemetryService.get_table(redis, 'D8', need_cfg=False, source='file')
    assert file_out['changed'] is False
    assert 'rows' not in file_out
    assert 'fps' not in file_out
    assert 'fps' not in db_out


@_aio
async def test_get_table_returns_fps_even_when_unchanged() -> None:
    """D8 / D9V17 各自读 fps key；changed=false 也带回；脏值当 0。"""
    payload = {
        'ts': 't',
        'dataId': 7,
        'name': 'n',
        'fields': [{'id': 'a', 'name': 'A', 'value': 1, 'show': '1', 'unit': '', 'hex': '01'}],
        'srcParam': 'serial:COM4',
    }

    async def _get(key: str):
        k = str(key)
        if k.endswith(':D8:fps'):
            return b'12'
        if k.endswith(':D9V17:fps'):
            return '600'
        if k.endswith(':latest'):
            return json.dumps(payload)
        return None

    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=_get)
    same = await PayloadTelemetryService.get_table(redis, 'D8', data_id='7')
    assert same['changed'] is False
    assert 'rows' not in same
    assert same['fps'] == 12
    d9 = await PayloadTelemetryService.get_table(redis, 'D9V17', data_id='7')
    assert d9['fps'] == 600
    dirty = AsyncMock()
    dirty.get = AsyncMock(return_value=json.dumps(payload))
    out = await PayloadTelemetryService.get_table(dirty, 'D8', data_id='7')
    assert out['fps'] == 0


@_aio
async def test_get_curve_data_uses_redis() -> None:
    redis = AsyncMock()
    with patch(
        'module_payload.service.payload_telemetry_service.get_curve_points',
        AsyncMock(return_value=[{'t': 1, 'v': 2.0}]),
    ):
        out = await PayloadTelemetryService.get_curve_data(redis, 'D8', 'no_such_field')
    assert out['points'] == [{'t': 1, 'v': 2.0}]
    assert out['type'] == 'D8'
    assert out['field'] == 'no_such_field'


@_aio
async def test_curve_batch_clips_to_first_series_last_t() -> None:
    redis = AsyncMock()

    async def fake_points(_redis, _table, field, _limit=500, since_t=None, until_t=None):
        if field == 'CAMF008':
            return [{'t': 10, 'v': 1.0}, {'t': 20, 'v': 2.0}]
        pts = [{'t': 10, 'v': 1.0}, {'t': 20, 'v': 2.0}, {'t': 30, 'v': 3.0}]
        if until_t is not None:
            pts = [p for p in pts if p['t'] <= until_t]
        return pts

    with patch(
        'module_payload.service.payload_telemetry_service.get_curve_points',
        AsyncMock(side_effect=fake_points),
    ):
        batch = await PayloadTelemetryService.get_curve_data_batch(
            redis,
            [
                {'type': 'D9V17', 'field': 'CAMF008', 'limit': 10000, 'since_t': 0},
                {'type': 'D9V17', 'field': 'CAMF022', 'limit': 10000, 'since_t': 0},
            ],
        )
    assert batch[0]['points'][-1]['t'] == 20
    assert batch[1]['points'][-1]['t'] == 20
    assert [p['t'] for p in batch[1]['points']] == [10, 20]
