"""相机服务：启动把 image_no 写入控制队列；查询透出 Redis meta。"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from exceptions.exception import ServiceException
from module_payload import redis_keys as rk
from module_payload.collectors.process_manager import CollectorProcessManager
from module_payload.entity.vo.payload_camera_vo import CameraStartModel
from module_payload.entity.vo.payload_sequence_vo import PayloadSequenceModel
from module_payload.service.payload_camera_service import PayloadCameraService


def test_camera_start_model_accepts_camel_image_no() -> None:
    body = CameraStartModel.model_validate(
        {'port': 'COM4', 'imageNo': 6, 'resolution': '256×256', 'once': True}
    )
    assert body.image_no == 6
    assert body.once is True


def test_camera_start_model_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        CameraStartModel.model_validate({'port': 'COM4', 'imageNo': 0})
    with pytest.raises(ValidationError):
        CameraStartModel.model_validate({'port': 'COM4', 'imageNo': 65})


def test_start_requires_opened_serial() -> None:
    mgr = MagicMock()
    mgr.list_opened.return_value = []
    with patch.object(CollectorProcessManager, 'instance', return_value=mgr):
        with pytest.raises(ServiceException) as ei:
            PayloadCameraService.start(CameraStartModel(port='COM4', image_no=3))
    assert '未打开' in str(ei.value.message)


def test_start_pushes_image_no_on_ctrl_queue() -> None:
    mgr = MagicMock()
    mgr.list_opened.return_value = [{'deviceId': rk.serial_id('COM4'), 'alive': True}]
    redis = MagicMock()
    with patch.object(CollectorProcessManager, 'instance', return_value=mgr):
        with patch(
            'module_payload.collectors.redis_sync.create_sync_redis',
            return_value=redis,
        ):
            result = PayloadCameraService.start(
                CameraStartModel.model_validate(
                    {'port': 'COM4', 'imageNo': 6, 'resolution': '128×128', 'once': True}
                )
            )
    assert result['deviceId'] == 'serial:COM4'
    assert result['once'] is True
    redis.delete.assert_called()
    ctrl_raw = redis.lpush.call_args[0][1]
    msg = json.loads(ctrl_raw)
    assert msg['op'] == 'camera_start'
    assert msg['config']['image_no'] == 6
    assert msg['config']['resolution'] == '128×128'
    assert msg['config']['once'] is True
    redis.close.assert_called_once()


def test_stop_pushes_camera_stop_and_deletes_cache() -> None:
    redis = MagicMock()
    with patch(
        'module_payload.collectors.redis_sync.create_sync_redis',
        return_value=redis,
    ):
        result = PayloadCameraService.stop('COM4')
    assert result['status'] == 'stopped'
    raw = redis.lpush.call_args[0][1]
    assert json.loads(raw)['op'] == 'camera_stop'
    redis.delete.assert_called()


def test_get_image_returns_meta_image_no() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value='base64png')
    meta = {'imageNo': 5, 'width': 64, 'height': 64, 'format': 'png', 'phase': 'ready'}

    async def _run():
        with patch(
            'module_payload.service.payload_camera_service.get_image_meta',
            AsyncMock(return_value=meta),
        ):
            with patch(
                'module_payload.service.payload_camera_service.get_status',
                AsyncMock(return_value={'connected': True, 'state': 'running', 'message': 'ok'}),
            ):
                return await PayloadCameraService.get_image(redis, 'COM4')

    out = asyncio.run(_run())
    assert out['image']['meta']['imageNo'] == 5
    assert out['image']['data'] == 'base64png'
    assert out['status']['imagePhase'] == 'ready'
    assert out['status']['connected'] is True


def test_sequence_commands_json_keeps_values() -> None:
    commands = json.dumps(
        {
            'defaultInterval': 2000,
            'items': [
                {'name': '', 'hex': 'AA BB', 'interval': -1, 'orderId': 'D1501', 'values': [1, 'AA']}
            ],
        },
        ensure_ascii=False,
    )
    m = PayloadSequenceModel(seq_name='t1', commands=commands)
    parsed = json.loads(m.commands or '')
    assert parsed['items'][0]['values'] == [1, 'AA']
    dumped = m.model_dump(by_alias=True)
    assert 'seqName' in dumped
