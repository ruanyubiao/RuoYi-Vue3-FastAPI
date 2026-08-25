"""指令序列：commands JSON 保留控件 values；执行守卫与间隔解析。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from exceptions.exception import ServiceException
from module_payload.entity.vo.payload_sequence_vo import PayloadSequenceModel
from module_payload.service.payload_sequence_service import PayloadSequenceService


def _aio(fn):
    def _wrap(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    _wrap.__name__ = fn.__name__
    return _wrap


def _svc_msg(ei) -> str:
    return ei.value.message or ''


def test_parse_object_format_keeps_values() -> None:
    raw = json.dumps(
        {
            'defaultInterval': 1500,
            'items': [
                {
                    'name': '',
                    'hex': 'EB 90 0A 00 00 00 00 00',
                    'interval': -1,
                    'orderId': 'D1503',
                    'values': [None, None, None, None, '0xAA', 1.5],
                }
            ],
        }
    )
    items, default_interval = PayloadSequenceService._parse_sequence_commands(raw)
    assert default_interval == 1500
    assert items[0]['orderId'] == 'D1503'
    assert items[0]['values'][5] == 1.5
    assert items[0]['hex']


def test_parse_legacy_array_default_interval_2000() -> None:
    items, default_interval = PayloadSequenceService._parse_sequence_commands(
        json.dumps([{'hex': 'AA BB CC DD EE FF 00 11'}])
    )
    assert default_interval == 2000
    assert len(items) == 1


def test_parse_commands_alias_and_bad_interval() -> None:
    items, default_interval = PayloadSequenceService._parse_sequence_commands(
        json.dumps({'default_interval': 'nope', 'commands': [{'hex': '00' * 8}]})
    )
    assert default_interval == 2000
    assert len(items) == 1


def test_parse_negative_default_interval_clamped() -> None:
    _, default_interval = PayloadSequenceService._parse_sequence_commands(
        json.dumps({'defaultInterval': -5, 'items': []})
    )
    assert default_interval == 2000


def test_parse_non_list_items_becomes_empty() -> None:
    items, _ = PayloadSequenceService._parse_sequence_commands(json.dumps({'items': {'a': 1}}))
    assert items == []


def test_parse_unexpected_json_type() -> None:
    items, default_interval = PayloadSequenceService._parse_sequence_commands(json.dumps(123))
    assert items == []
    assert default_interval == 2000


@_aio
async def test_run_rejects_empty_and_broadcast_and_blank_hex() -> None:
    detail = PayloadSequenceModel(
        seqId=1,
        seqName='s',
        commands=json.dumps({'items': []}),
    )
    with patch.object(PayloadSequenceService, 'sequence_detail_services', AsyncMock(return_value=detail)):
        with pytest.raises(ServiceException) as ei:
            await PayloadSequenceService.run_sequence_services(MagicMock(), MagicMock(), 1, 'can:3:0:0')
        assert '为空' in _svc_msg(ei)

    detail.commands = json.dumps({'items': [{'hex': '30 00 00 00 00 00 00 00'}]})
    with patch.object(PayloadSequenceService, 'sequence_detail_services', AsyncMock(return_value=detail)):
        with pytest.raises(ServiceException) as ei:
            await PayloadSequenceService.run_sequence_services(MagicMock(), MagicMock(), 1, 'can:3:0:0')
        assert '广播' in _svc_msg(ei)

    detail.commands = json.dumps({'items': [{'hex': '   '}]})
    with patch.object(PayloadSequenceService, 'sequence_detail_services', AsyncMock(return_value=detail)):
        with pytest.raises(ServiceException) as ei:
            await PayloadSequenceService.run_sequence_services(MagicMock(), MagicMock(), 1, 'can:3:0:0')
        assert '空 HEX' in _svc_msg(ei)


@_aio
async def test_run_rejects_bad_json() -> None:
    detail = PayloadSequenceModel(seqId=1, seqName='s', commands='{')
    with patch.object(PayloadSequenceService, 'sequence_detail_services', AsyncMock(return_value=detail)):
        with pytest.raises(ServiceException) as ei:
            await PayloadSequenceService.run_sequence_services(MagicMock(), MagicMock(), 1, 'serial:COM3')
        assert '格式错误' in _svc_msg(ei)


@_aio
async def test_copy_appends_suffix() -> None:
    detail = PayloadSequenceModel(seqId=9, seqName='主序列', commands='[]')
    with patch.object(PayloadSequenceService, 'sequence_detail_services', AsyncMock(return_value=detail)):
        draft = await PayloadSequenceService.copy_sequence_services(MagicMock(), 9)
    assert draft.seq_id is None
    assert draft.seq_name == '主序列-副本'


@_aio
async def test_copy_missing_raises() -> None:
    with patch.object(
        PayloadSequenceService,
        'sequence_detail_services',
        AsyncMock(return_value=PayloadSequenceModel()),
    ):
        with pytest.raises(ServiceException) as ei:
            await PayloadSequenceService.copy_sequence_services(MagicMock(), 1)
        assert '不存在' in _svc_msg(ei)


@_aio
async def test_add_defaults_unknown_project_to_biu() -> None:
    saved = SimpleNamespace(seq_id=42)
    page = PayloadSequenceModel(seqName='n', project=None, commands='[]')
    db = AsyncMock()
    with patch(
        'module_payload.service.payload_sequence_service.PayloadSequenceDao.add_sequence_dao',
        AsyncMock(return_value=saved),
    ):
        result = await PayloadSequenceService.add_sequence_services(db, page)
    assert page.project == 'biu'
    assert result.is_success is True
    assert result.result == {'seqId': 42}
    db.commit.assert_awaited()


@_aio
async def test_execute_stops_on_fail_and_skips_rest() -> None:
    redis = MagicMock()
    commands = [
        {'hex': 'EB 90 0A 93 00 72 0F 00', 'interval': 0, 'name': 'a'},
        {'hex': 'EB 90 0A 93 00 72 0F 01', 'interval': 0, 'name': 'b'},
    ]
    run = {
        'runId': 'r1',
        'items': [
            {'index': 0, 'status': 'pending', 'message': '', 'time': ''},
            {'index': 1, 'status': 'pending', 'message': '', 'time': ''},
        ],
    }
    saved: list[dict] = []

    async def _get(_r, _id):
        return run

    async def _save(_r, state):
        saved.append(json.loads(json.dumps(state)))

    with (
        patch('module_payload.service.payload_sequence_service.get_seq_run', _get),
        patch('module_payload.service.payload_sequence_service.save_seq_run', _save),
        patch(
            'module_payload.service.payload_telecontrol_service.PayloadTelecontrolService.send',
            AsyncMock(return_value={'success': False, 'message': '超时'}),
        ),
    ):
        await PayloadSequenceService._execute_sequence_run(redis, 'r1', 'can:3:0:0', commands, 10)

    final = saved[-1]
    assert final['status'] == 'failed'
    assert final['fail'] == 1
    assert final['items'][0]['status'] == 'failed'
    assert final['items'][1]['status'] == 'skipped'
    assert '前置失败' in final['items'][1]['message']
