"""设备服务：网口 ID、fullDuplex 写入采集配置。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from module_payload.collectors.duplex import resolve_full_duplex
from module_payload.entity.vo.payload_device_vo import NetOpenModel, SerialOpenModel
from module_payload.service.payload_device_service import PayloadDeviceService


def test_close_net_device_id() -> None:
    mgr = MagicMock()
    redis = MagicMock()
    with (
        patch.object(PayloadDeviceService, '_is_device_alive', return_value=False),
        patch(
            'module_payload.collectors.process_manager.CollectorProcessManager.instance',
            return_value=mgr,
        ),
        patch(
            'module_payload.collectors.redis_sync.create_sync_redis',
            return_value=redis,
        ),
        patch(
            'module_payload.service.payload_session_service.PayloadSessionService.close_session_sync',
        ) as close_sess,
    ):
        out = PayloadDeviceService._close_net_sync('UDP', '10.0.0.1', 9000)
    assert out == {'deviceId': 'udp:10.0.0.1:9000', 'status': 'closed'}
    mgr.stop.assert_called_once_with('udp:10.0.0.1:9000')
    close_sess.assert_called()


def test_open_net_rejects_non_udp() -> None:
    with pytest.raises(ValueError, match='暂不支持'):
        PayloadDeviceService._open_net_sync(NetOpenModel(proto='tcp', local_port=9))
    with pytest.raises(ValueError, match='端口无效'):
        PayloadDeviceService._open_net_sync(NetOpenModel(proto='udp', local_port=0))


def test_normalize_udp_remote_host_without_port() -> None:
    """可只填远程地址、端口为 0；空地址则端口也须为 0。"""
    assert PayloadDeviceService._normalize_udp_remote('127.0.0.1', 0) == ('127.0.0.1', 0)
    assert PayloadDeviceService._normalize_udp_remote('', 0) == ('', 0)
    assert PayloadDeviceService._normalize_udp_remote('10.0.0.1', 99) == ('10.0.0.1', 99)
    with pytest.raises(ValueError, match='端口须为 0'):
        PayloadDeviceService._normalize_udp_remote('', 99)


def test_open_net_passes_full_duplex_and_id() -> None:
    mgr = MagicMock()
    mgr.start_net.return_value = ('udp:127.0.0.1:9000', False)
    redis = MagicMock()
    body = NetOpenModel(
        proto='udp',
        local_host='127.0.0.1',
        local_port=9000,
        source='home',
        full_duplex=True,
    )
    with (
        patch(
            'module_payload.collectors.process_manager.CollectorProcessManager.instance',
            return_value=mgr,
        ),
        patch(
            'module_payload.collectors.redis_sync.create_sync_redis',
            return_value=redis,
        ),
        patch(
            'module_payload.service.payload_session_service.PayloadSessionService.open_session_sync',
            return_value={'srcParam': 'udp:127.0.0.1:9000'},
        ),
    ):
        out = PayloadDeviceService._open_net_sync(body)
    assert out['deviceId'] == 'udp:127.0.0.1:9000'
    cfg = mgr.start_net.call_args.args[3]
    assert cfg['full_duplex'] is True
    assert resolve_full_duplex(source='home', explicit=True) is True
    mgr.notify_session_changed.assert_not_called()


def test_open_net_already_open_applies_page_params() -> None:
    """本机地址+端口已占用时不重启进程，仍写会话并把本页远程对端推给采集。"""
    mgr = MagicMock()
    mgr.start_net.return_value = ('udp:127.0.0.1:66', True)
    redis = MagicMock()
    body = NetOpenModel(
        proto='udp',
        local_host='127.0.0.1',
        local_port=66,
        remote_host='127.0.0.1',
        remote_port=99,
        source='xl_udp_dj',
    )
    with (
        patch(
            'module_payload.collectors.process_manager.CollectorProcessManager.instance',
            return_value=mgr,
        ),
        patch(
            'module_payload.collectors.redis_sync.create_sync_redis',
            return_value=redis,
        ),
        patch(
            'module_payload.service.payload_session_service.PayloadSessionService.open_session_sync',
            return_value={'srcParam': 'udp:127.0.0.1:66'},
        ),
    ):
        out = PayloadDeviceService._open_net_sync(body)
    assert out['status'] == 'already_open'
    mgr.apply_net_reuse_params.assert_called_once_with(
        'udp:127.0.0.1:66',
        remote_host='127.0.0.1',
        remote_port=99,
    )
    mgr.notify_session_changed.assert_not_called()


def test_serial_open_model_feeds_resolve() -> None:
    body = SerialOpenModel(port='COM4', source='camera_ctrl', full_duplex=None)
    assert resolve_full_duplex(source=body.source, explicit=body.full_duplex) is True
    body2 = SerialOpenModel(port='COM4', source='camera_ctrl', full_duplex=False)
    assert resolve_full_duplex(source=body2.source, explicit=body2.full_duplex) is False
