"""遥控服务：组帧、CAN 原始 HEX 规范化、发送超时。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from exceptions.exception import ServiceException
from module_payload.entity.vo.payload_telecontrol_vo import (
    TelecontrolAssembleModel,
    TelecontrolSendModel,
)
from module_payload.service.payload_telecontrol_service import PayloadTelecontrolService


def _aio(fn):
    def _wrap(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    _wrap.__name__ = fn.__name__
    return _wrap


def test_normalize_hex_tokens() -> None:
    n = PayloadTelecontrolService._normalize_hex_tokens
    assert n('') == []
    assert n('AA BB') == [0xAA, 0xBB]
    assert n('A') == [0x0A]
    assert n('A B') == [0x0A, 0x0B]
    assert n('GG') is None
    assert n('AABBCC') == [0xAA, 0xBB, 0xCC]
    assert n('0xAA') is None


def test_assemble_by_order_id() -> None:
    from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager

    TeleControlCfgManager.reload('biu-tc')
    oid = TeleControlCfgManager.get('biu-tc').list_orders()[0]['id']
    body = TelecontrolAssembleModel(orderId=oid, family='biu')
    result = PayloadTelecontrolService.assemble(body)
    assert result.get('hex')
    assert result.get('length', 0) > 0


def test_assemble_explicit_components() -> None:
    body = TelecontrolAssembleModel(
        components=[
            {'componentType': 'fixed', 'defaultVal': '0A00000000000000'},
        ],
        values=[],
        family='biu',
    )
    result = PayloadTelecontrolService.assemble(body)
    assert '0A' in result['hex'].replace(' ', '')


@_aio
async def test_send_can_raw_validates() -> None:
    redis = AsyncMock()
    with pytest.raises(ServiceException) as ei:
        await PayloadTelecontrolService.send_can_raw(redis, 'can:3:0:0', '12 34', 'AA')
    assert '8个十六进制' in (ei.value.message or '')
    with pytest.raises(ServiceException) as ei:
        await PayloadTelecontrolService.send_can_raw(redis, 'can:3:0:0', '12345678', 'GG')
    assert '十六进制' in (ei.value.message or '')
    with pytest.raises(ServiceException) as ei:
        await PayloadTelecontrolService.send_can_raw(redis, 'can:3:0:0', '12345678', '00 11 22 33 44 55 66 77 88')
    assert '最多8' in (ei.value.message or '')


@_aio
async def test_send_can_raw_timeout() -> None:
    redis = AsyncMock()
    with (
        patch('module_payload.service.payload_telecontrol_service.push_command', AsyncMock()),
        patch('module_payload.service.payload_telecontrol_service.wait_command_result', AsyncMock(return_value=None)),
    ):
        out = await PayloadTelecontrolService.send_can_raw(redis, 'can:3:0:0', '0000000D', 'AA')
    assert out['success'] is False
    assert '超时' in out['message']


@_aio
async def test_send_empty_hex_raises() -> None:
    with pytest.raises(ServiceException) as ei:
        await PayloadTelecontrolService.send(
            AsyncMock(),
            TelecontrolSendModel(deviceId='can:3:0:0', hex=''),
        )
    assert '不能为空' in (ei.value.message or '')


@_aio
async def test_send_timeout_and_success() -> None:
    redis = AsyncMock()
    body = TelecontrolSendModel(deviceId='can:3:0:0', hex='EB 90 0A 00 00 00 00 00')
    with (
        patch('module_payload.service.payload_telecontrol_service.push_command', AsyncMock()) as push,
        patch(
            'module_payload.service.payload_telecontrol_service.wait_command_result',
            AsyncMock(return_value={'success': True}),
        ),
    ):
        out = await PayloadTelecontrolService.send(redis, body)
    assert out['success'] is True
    cmd = push.await_args.args[2]
    assert cmd['use_business'] is True
    assert cmd['hex'].replace(' ', '').upper().startswith('EB90')
