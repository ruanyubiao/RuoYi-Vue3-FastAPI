"""模拟注入管线：HEX → assembler → assembled Redis → ingest。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from exceptions.exception import ServiceException
from module_payload import redis_keys as rk
from module_payload.cfg.hex_text import hex_to_bytes
from module_payload.constants import (
    ASSEMBLER_PASSTHROUGH,
    PARSER_TM_XL_CAMERA,
    PARSER_TM_XL_CAMERA_V17,
    PARSER_TM_CAN_BIU,
)
from module_payload.service.payload_telemetry_service import PayloadTelemetryService

_TESTS_DIR = Path(__file__).resolve().parent
_BACKEND = _TESTS_DIR.parent

_CASES = json.loads((_BACKEND / 'assets' / 'data' / 'tm_golden_cases.json').read_text(encoding='utf-8'))


def _async_redis() -> AsyncMock:
    redis = AsyncMock()
    pipe = MagicMock()
    pipe.zadd.return_value = pipe
    pipe.zremrangebyrank.return_value = pipe
    pipe.execute = AsyncMock(return_value=[])
    redis.pipeline = MagicMock(return_value=pipe)
    redis.set = AsyncMock()
    redis.lpush = AsyncMock()
    redis.ltrim = AsyncMock()
    return redis


def _assembled_payloads(redis: AsyncMock) -> list[dict]:
    key = rk.assembled_latest_key('http:devtest')
    out: list[dict] = []
    for c in redis.set.call_args_list:
        if c.args and c.args[0] == key:
            out.append(json.loads(c.args[1]))
    return out


async def _inject(redis: AsyncMock, hex_text: str, assembler: str, parser: str):
    with patch(
        'module_payload.redis_store.set_telemetry',
        new=AsyncMock(return_value={'fields': [{'id': 'A'}], 'name': 'n', 'ts': 't'}),
    ):
        return await PayloadTelemetryService.inject_pipeline(redis, hex_text, assembler, parser)


def test_inject_pipeline_passthrough_can_golden() -> None:
    hex_text = _CASES['passthrough_biu_ff_1']['hex']
    redis = _async_redis()
    result = asyncio.run(_inject(redis, hex_text, ASSEMBLER_PASSTHROUGH, PARSER_TM_CAN_BIU))
    assert result['parsedCount'] >= 1
    assert result['assemblerId'] == ASSEMBLER_PASSTHROUGH
    assert result['parserId'] == PARSER_TM_CAN_BIU
    entries = _assembled_payloads(redis)
    assert entries
    last = entries[-1]
    assert set(last) >= {'deviceId', 'assemblerId', 'ts', 'len', 'hex', 'meta'}
    assert last['deviceId'] == 'http:devtest'
    assert last['assemblerId'] == ASSEMBLER_PASSTHROUGH
    assert ' ' in last['hex'] or len(last['hex']) == 2
    assert last['len'] > 0


def test_inject_pipeline_passthrough_camera_golden() -> None:
    hex_text = _CASES['passthrough_cam_d8']['hex']
    redis = _async_redis()
    result = asyncio.run(_inject(redis, hex_text, ASSEMBLER_PASSTHROUGH, PARSER_TM_XL_CAMERA))
    assert result['parsedCount'] >= 1
    last = _assembled_payloads(redis)[-1]
    assert last['deviceId'] == 'http:devtest'


def test_inject_pipeline_passthrough_camera_d9_multi() -> None:
    hex_text = _CASES['passthrough_cam_d9_multi']['hex']
    redis = _async_redis()
    result = asyncio.run(_inject(redis, hex_text, ASSEMBLER_PASSTHROUGH, PARSER_TM_XL_CAMERA))
    assert result['parsedCount'] >= 1
    last = _assembled_payloads(redis)[-1]
    assert last['deviceId'] == 'http:devtest'
    assert len(hex_to_bytes(hex_text)) == 18 * 20


def test_inject_pipeline_clears_d9_mux_before_sample() -> None:
    """模拟注入前清掉 http:devtest 的 mux，避免上一条样例污染本条 D9 解析。"""
    from module_payload.parsers.xl_camera_tm import XlCameraTmIngest

    XlCameraTmIngest.reset_mgr()
    # 污染：若不清缓存，单帧 D9 会合并进这些 last-known，CAMF012+ 偏离黄金 0
    XlCameraTmIngest._d9_mux_cache['http:devtest'] = {
        i: bytes([0xAB + i] * 16) for i in range(8)
    }
    hex_text = _CASES['passthrough_cam_d9']['hex']
    expect_fields = (_CASES['passthrough_cam_d9'].get('result') or {}).get('fields') or []
    by_exp = {str(f.get('id')): f for f in expect_fields if f.get('id')}
    captured: list[list[dict]] = []

    async def _capture_set(redis, table_type, fields, name='', **kwargs):
        captured.append(list(fields))
        return {
            'type': table_type,
            'fields': fields,
            'name': name,
            'ts': 't',
            'dataId': 1,
        }

    redis = _async_redis()

    async def _run():
        with patch(
            'module_payload.redis_store.set_telemetry',
            new=AsyncMock(side_effect=_capture_set),
        ):
            return await PayloadTelemetryService.inject_pipeline(
                redis, hex_text, ASSEMBLER_PASSTHROUGH, PARSER_TM_XL_CAMERA
            )

    result = asyncio.run(_run())
    assert result['parsedCount'] >= 1
    assert captured, '应写入遥测 fields'
    by_got = {str(f.get('id')): f for f in captured[-1] if f.get('id')}
    for fid in ('CAMF012', 'CAMF013', 'CAMF014'):
        exp = by_exp[fid]
        got = by_got[fid]
        assert str(got.get('value')) == str(exp.get('value')), (
            f'{fid} 期望={exp.get("value")!r} 实际={got.get("value")!r}（mux 未隔离）'
        )
        assert str(got.get('show')) == str(exp.get('show')), fid


def test_inject_pipeline_passthrough_camera_v17_golden() -> None:
    hex_text = _CASES['passthrough_cam_v17_d8']['hex']
    redis = _async_redis()
    result = asyncio.run(_inject(redis, hex_text, ASSEMBLER_PASSTHROUGH, PARSER_TM_XL_CAMERA_V17))
    assert result['parsedCount'] >= 1
    last = _assembled_payloads(redis)[-1]
    assert last['deviceId'] == 'http:devtest'


def test_inject_pipeline_empty_hex() -> None:
    redis = _async_redis()
    with pytest.raises(ServiceException) as ei:
        asyncio.run(_inject(redis, '   ', ASSEMBLER_PASSTHROUGH, PARSER_TM_CAN_BIU))
    assert 'HEX 为空' in (ei.value.message or '')


def test_inject_pipeline_unknown_parser() -> None:
    redis = _async_redis()
    with pytest.raises(ServiceException) as ei:
        asyncio.run(_inject(redis, '00 01', ASSEMBLER_PASSTHROUGH, 'no_such_parser'))
    assert '未知或不可用' in (ei.value.message or '')


def test_inject_pipeline_incomplete_eng_payload() -> None:
    redis = _async_redis()
    with pytest.raises(ServiceException) as ei:
        asyncio.run(_inject(redis, '1B CF 00 01', 'eng_tm_subpkt', PARSER_TM_CAN_BIU))
    assert ei.value.message
    assert '未组装出完整载荷' in ei.value.message or '组装' in ei.value.message


def test_assembled_entry_hex_max_and_fields() -> None:
    from module_payload.pipeline import assembled_entry

    data = bytes(range(80))
    full = assembled_entry('dev', 'passthrough', data, {'k': 1}, ts='t')
    preview = assembled_entry('dev', 'passthrough', data, {'k': 1}, hex_max=64, ts='t')
    image = assembled_entry('dev', 'camera_image_d6', data, {'kind': 'image'}, ts='t')
    keys = {'deviceId', 'assemblerId', 'ts', 'len', 'hex', 'meta'}
    assert set(full) == keys
    assert set(preview) == keys
    assert full['len'] == 80
    assert len(full['hex'].split()) == 80
    assert len(preview['hex'].split()) == 64
    assert image['hex'] == ''
    assert full['meta']['assemblerId'] == 'passthrough'


def test_feed_assembler_passthrough() -> None:
    from module_payload.assemblers import create_assembler
    from module_payload.pipeline import feed_assembler

    payloads, errors = feed_assembler(create_assembler('passthrough'), b'\x01\x02')
    assert len(payloads) == 1
    assert payloads[0].data == b'\x01\x02'
    assert errors == []
