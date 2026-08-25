"""LVDS 演示数据、遥测计算 Hex 补齐。"""

from __future__ import annotations

import asyncio

import pytest

from exceptions.exception import ServiceException
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
    assert PayloadTmCalcService._hex_to_bytes('zz') == b''  # 非十六进制字符被剥掉
    assert PayloadTmCalcService._hex_to_bytes('A') == bytes([0x0A])


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
