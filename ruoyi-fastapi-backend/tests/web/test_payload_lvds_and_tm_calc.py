"""LVDS 演示数据、遥测计算 Hex 补齐。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from exceptions.exception import ServiceException
from module_payload import redis_keys as rk
from module_payload.constants import HISTORY_MAX
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.service.payload_lvds_service import PayloadLvdsService
from module_payload.service.payload_tm_calc_service import PayloadTmCalcService


def _aio(fn):
    def _wrap(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    _wrap.__name__ = fn.__name__
    return _wrap


def test_lvds_list_signals_fallback() -> None:
    signals = PayloadLvdsService.list_signals('NO_SUCH_TABLE')
    ids = {s['id'] for s in signals}
    assert 'qd_x_pos' in ids


def test_lvds_list_signals_from_cfg() -> None:
    # 工程遥测表若存在则带 id；不存在则走 fallback，均非空
    signals = PayloadLvdsService.list_signals('7E9B')
    assert signals
    assert all(s.get('id') for s in signals)


def test_lvds_demo_points() -> None:
    pts = PayloadLvdsService._generate_demo_points('qd_x_pos', 20)
    assert len(pts) == 20
    assert {'t', 'v'} <= set(pts[0])
    a = PayloadLvdsService._generate_demo_points('a', 10)
    b = PayloadLvdsService._generate_demo_points('b', 10)
    assert [p['v'] for p in a] != [p['v'] for p in b]


@_aio
async def test_lvds_get_data_demo_when_empty() -> None:
    class R:
        async def lrange(self, *_a, **_k):
            return []

    out = await PayloadLvdsService.get_data(R(), 'qd_x_pos', limit=8)
    assert out['signal'] == 'qd_x_pos'
    assert out['points']


def test_tm_calc_field_byte_len() -> None:
    assert PayloadTmCalcService._field_byte_len({'bits': 8}) == 1
    assert PayloadTmCalcService._field_byte_len({'bits': 9}) == 2
    assert PayloadTmCalcService._field_byte_len({'bits': 0}) == 1
    assert PayloadTmCalcService._field_byte_len({'bits': 'x'}) == 1


def test_tm_calc_hex_to_bytes_and_pad() -> None:
    assert PayloadTmCalcService._hex_to_bytes('33 01 02') == bytes([0x33, 0x01, 0x02])
    assert PayloadTmCalcService._hex_to_bytes('A') == bytes([0x0A])  # 奇数半字节：末位前补 0
    row = {'bits': 32}
    tail = PayloadTmCalcService._pad_field_hex('33 01 02', row, pad_tail=True)
    head = PayloadTmCalcService._pad_field_hex('33 01 02', row, pad_tail=False)
    assert tail == '33 01 02 00'
    assert head == '00 33 01 02'


def test_tm_calc_hex_empty() -> None:
    assert PayloadTmCalcService._hex_to_bytes('') == b''
    with pytest.raises(ServiceException) as ei:
        PayloadTmCalcService._hex_to_bytes('zz')
    assert 'Hex' in (ei.value.message or '')
    assert PayloadTmCalcService._hex_to_bytes('A') == bytes([0x0A])
    assert PayloadTmCalcService._hex_to_bytes('A B') == bytes([0x0A, 0x0B])


@_aio
async def test_tm_calc_requires_params() -> None:
    redis = object()
    with pytest.raises(ServiceException) as ei:
        await PayloadTmCalcService.calculate(redis, table_type='', field_id='a', hex_text='00')
    assert '遥测表' in (ei.value.message or '')
    with pytest.raises(ServiceException) as ei:
        await PayloadTmCalcService.calculate(redis, table_type='FF', field_id='', hex_text='00')
    assert '遥测量' in (ei.value.message or '')
    with pytest.raises(ServiceException) as ei:
        await PayloadTmCalcService.calculate(redis, table_type='FF', field_id='a', hex_text='  ')
    assert 'Hex' in (ei.value.message or '')


class _AsyncListRedis:
    """最小异步 Redis：仅 lpush/ltrim/lrange。"""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}

    async def lpush(self, key: str, val: str) -> None:
        self.lists.setdefault(key, []).insert(0, val)

    async def ltrim(self, key: str, start: int, end: int) -> None:
        items = self.lists.get(key, [])
        self.lists[key] = items[start : end + 1]

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        items = self.lists.get(key, [])
        if end < 0:
            return items[start:]
        return items[start : end + 1]


def _fake_parse_line(field_id: str = 'CAM001', *, err: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=field_id,
        name='相机指令计数',
        unit='',
        show='42',
        calc_val=42.0,
        hex='2A',
        err=err,
        val=SimpleNamespace(value=lambda: 42.0),
    )


@_aio
async def test_tm_calc_calculate_success_writes_history() -> None:
    table = PayloadConfigService.get_telemetry_table_def('D8')
    rows = table.get('row') or []
    assert rows, 'D8 表应有字段配置'
    field_id = str(rows[0].get('id') or '')
    assert field_id

    redis = _AsyncListRedis()
    fake_line = _fake_parse_line(field_id)

    with patch.object(PayloadTmCalcService, '_parse_line', return_value=fake_line):
        out = await PayloadTmCalcService.calculate(
            redis,
            table_type='D8',
            field_id=field_id,
            hex_text='2A',
            pad_tail=True,
        )

    assert out['err'] is False
    assert out['warnMsg'] == ''
    assert out['row']['id'] == field_id
    assert out['row']['value'] == 42.0
    assert out['row']['inputHex'] == '2A'
    assert out['row']['padTail'] is True
    assert out['row']['tableType'] == 'D8'
    assert out['history'][0]['id'] == field_id

    key = rk.tm_calc_history_key()
    assert len(redis.lists.get(key, [])) == 1
    stored = json.loads(redis.lists[key][0])
    assert stored['id'] == field_id
    assert stored['calc_val'] == 42.0


@_aio
async def test_tm_calc_calculate_pad_tail_false() -> None:
    table = PayloadConfigService.get_telemetry_table_def('D8')
    rows = table.get('row') or []
    wide = next((r for r in rows if int(r.get('bits') or 0) >= 32), rows[0])
    field_id = str(wide.get('id') or 'CAM015')
    redis = _AsyncListRedis()

    with patch.object(PayloadTmCalcService, '_parse_line', return_value=_fake_parse_line(field_id)):
        out = await PayloadTmCalcService.calculate(
            redis,
            table_type='d8',
            field_id=field_id,
            hex_text='33 01 02',
            pad_tail=False,
        )

    assert out['row']['padTail'] is False
    assert out['row']['paddedHex'] == '00 33 01 02'


@_aio
async def test_tm_calc_get_history_skips_corrupt_json() -> None:
    redis = _AsyncListRedis()
    key = rk.tm_calc_history_key()
    await redis.lpush(key, '{"id":"ok"}')
    await redis.lpush(key, 'not-json')
    history = await PayloadTmCalcService.get_history(redis, limit=HISTORY_MAX)
    assert len(history) == 1
    assert history[0]['id'] == 'ok'


@_aio
async def test_tm_calc_unknown_field_raises() -> None:
    redis = _AsyncListRedis()
    with pytest.raises(ServiceException) as ei:
        await PayloadTmCalcService.calculate(
            redis, table_type='D8', field_id='__no_such_field__', hex_text='00'
        )
    assert '字段不存在' in (ei.value.message or '')
