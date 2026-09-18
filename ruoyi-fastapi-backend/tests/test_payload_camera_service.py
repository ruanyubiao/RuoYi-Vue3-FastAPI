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
    # 图片在磁盘、全部保留：start 只标记 acquiring，不删旧图
    redis.delete.assert_not_called()
    meta_key, meta_raw = redis.set.call_args[0][:2]
    assert meta_key.endswith(':image:meta')
    assert json.loads(meta_raw)['phase'] == 'acquiring'
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
    deleted = redis.delete.call_args[0]
    assert deleted == (f'{rk.PREFIX}:serial:COM4:image:meta',)


def _get_image(meta: dict, since: str = '', b64: str = 'base64png') -> dict:
    """跑 get_image；磁盘读取用桩替掉。"""
    redis = AsyncMock()

    async def _run():
        with (
            patch(
                'module_payload.service.payload_camera_service.get_image_meta',
                AsyncMock(return_value=meta),
            ),
            patch(
                'module_payload.service.payload_camera_service.get_status',
                AsyncMock(return_value={'connected': True, 'state': 'running', 'message': 'ok'}),
            ),
            patch.object(PayloadCameraService, '_read_image_b64', return_value=b64),
        ):
            return await PayloadCameraService.get_image(redis, 'COM4', since)

    return asyncio.run(_run())


def test_get_image_returns_file_data_when_path_is_new() -> None:
    meta = {
        'imageNo': 5,
        'width': 64,
        'height': 64,
        'format': 'png',
        'phase': 'ready',
        'path': 'camera/2026/08/12/COM4_1.png',
    }
    out = _get_image(meta)
    assert out['image']['meta']['imageNo'] == 5
    assert out['image']['path'] == 'camera/2026/08/12/COM4_1.png'
    assert out['image']['changed'] is True
    assert out['image']['data'] == 'base64png'
    assert out['status']['imagePhase'] == 'ready'
    assert out['status']['connected'] is True


def test_get_image_same_path_does_not_read_disk() -> None:
    """轮询 300ms：路径没变就只回状态，不读盘也不回传图片。"""
    path = 'camera/2026/08/12/COM4_1.png'
    out = _get_image({'phase': 'ready', 'path': path}, since=path)
    assert out['image']['changed'] is False
    assert out['image']['data'] == ''
    assert out['image']['path'] == path


def test_get_image_accepts_backslash_since() -> None:
    path = 'camera/2026/08/12/COM4_1.png'
    out = _get_image({'phase': 'ready', 'path': path}, since='camera\\2026\\08\\12\\COM4_1.png')
    assert out['image']['changed'] is False


def test_get_image_missing_file_is_not_changed() -> None:
    out = _get_image({'phase': 'ready', 'path': 'camera/x.png'}, b64='')
    assert out['image']['changed'] is False
    assert out['image']['data'] == ''


def test_get_image_acquiring_without_path() -> None:
    out = _get_image({'phase': 'acquiring'})
    assert out['image']['changed'] is False
    assert out['image']['path'] == ''
    assert out['status']['imagePhase'] == 'acquiring'


def test_read_image_b64_rejects_escape(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr('module_payload.store.image_store.image_root', lambda: tmp_path)
    (tmp_path / 'camera').mkdir()
    target = tmp_path / 'camera' / 'a.png'
    target.write_bytes(b'\x89PNG')
    assert PayloadCameraService._read_image_b64('camera/a.png') == 'iVBORw=='
    assert PayloadCameraService._read_image_b64('../secret.txt') == ''
    assert PayloadCameraService._read_image_b64('') == ''
    assert PayloadCameraService._read_image_b64('camera/missing.png') == ''


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
