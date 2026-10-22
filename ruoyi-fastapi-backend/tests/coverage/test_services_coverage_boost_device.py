"""Coverage boost: device / CAN / serial / net service branches."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from exceptions.exception import ServiceException
from module_payload.entity.vo.payload_device_vo import CanOpenModel, NetOpenModel, SerialOpenModel
from module_payload.service.device_can import DeviceCanMixin
from module_payload.service.device_net import DeviceNetMixin
from module_payload.service.device_serial import DeviceSerialMixin
from module_payload.service.payload_device_service import PayloadDeviceService


def _aio(fn):
    def _wrap(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    _wrap.__name__ = fn.__name__
    return _wrap


# ---------------------------------------------------------------------------
# PayloadDeviceService: alive / close_all / io / snapshot
# ---------------------------------------------------------------------------


def test_is_session_device_alive_branches() -> None:
    mgr = MagicMock()
    mgr.list_opened.return_value = [
        {'type': 'can', 'deviceId': 'can:3:0', 'alive': True, 'channels': [0, 1]},
        {'type': 'serial', 'deviceId': 'serial:COM3', 'alive': True},
        {'type': 'net', 'deviceId': 'udp:0.0.0.0:9000', 'alive': False},
    ]
    with patch(
        'module_payload.service.payload_device_service.CollectorProcessManager.instance',
        return_value=mgr,
    ):
        assert PayloadDeviceService.is_session_device_alive('can:3:0:0') is True
        assert PayloadDeviceService.is_session_device_alive('can:3:0:9') is False
        assert PayloadDeviceService.is_session_device_alive('can:3:0:x') is False
        assert PayloadDeviceService.is_session_device_alive('serial:COM3') is True
        assert PayloadDeviceService.is_session_device_alive('serial:COM9') is False
        assert PayloadDeviceService.is_session_device_alive('udp:0.0.0.0:9000') is False
        assert PayloadDeviceService.is_session_device_alive('tcp:1.2.3.4:80') is False
        assert PayloadDeviceService.is_session_device_alive('http:dev') is True


def test_is_device_alive_serial_net_can() -> None:
    mgr = MagicMock()
    mgr.list_opened.return_value = [
        {'type': 'serial', 'deviceId': 'serial:COM1', 'alive': True},
        {'type': 'net', 'deviceId': 'udp:127.0.0.1:1', 'alive': True},
        {'type': 'can', 'deviceId': 'can:3:0', 'alive': True, 'channels': [2]},
    ]
    with patch(
        'module_payload.service.payload_device_service.CollectorProcessManager.instance',
        return_value=mgr,
    ):
        assert PayloadDeviceService._is_device_alive('serial:COM1') is True
        assert PayloadDeviceService._is_device_alive('serial:COM2') is False
        assert PayloadDeviceService._is_device_alive('udp:127.0.0.1:1') is True
        assert PayloadDeviceService._is_device_alive('tcp:127.0.0.1:1') is False
        assert PayloadDeviceService._is_device_alive('can:3:0:2') is True
        assert PayloadDeviceService._is_device_alive('can:3:0:0') is False
        assert PayloadDeviceService._is_device_alive('weird') is False


def test_close_all_sync_mixed_success_and_fail() -> None:
    mgr = MagicMock()
    mgr.list_opened.return_value = [
        {'type': 'can', 'deviceId': 'bad', 'channels': [0], 'config': {}},
        {
            'type': 'can',
            'deviceId': 'can:3:0',
            'channels': [0, 1],
            'config': {},
        },
        {'type': 'serial', 'deviceId': 'serial:COM3', 'config': {}},
        {
            'type': 'net',
            'deviceId': 'udp:0.0.0.0:9000',
            'config': {'proto': 'udp', 'local_host': '0.0.0.0', 'local_port': 9000},
        },
    ]
    mgr.stop.side_effect = [RuntimeError('stop fail'), None]

    def _close_can(body):
        if body.can_index == 1:
            raise RuntimeError('ch1 fail')
        return {'ok': True}

    with (
        patch(
            'module_payload.service.payload_device_service.CollectorProcessManager.instance',
            return_value=mgr,
        ),
        patch.object(PayloadDeviceService, '_close_can_sync', side_effect=_close_can),
        patch.object(PayloadDeviceService, '_close_serial_sync', side_effect=RuntimeError('ser')),
        patch.object(PayloadDeviceService, '_close_net_sync', return_value={'status': 'closed'}),
    ):
        out = PayloadDeviceService._close_all_sync()
    assert out['ok'] >= 1
    assert out['fail'] >= 1
    assert any(x.startswith('can:') for x in out['closed'])
    assert any(f['deviceId'] == 'serial:COM3' for f in out['failed'])


@_aio
async def test_close_all_uses_thread() -> None:
    with patch.object(
        PayloadDeviceService, '_close_all_sync', return_value={'closed': [], 'failed': [], 'ok': 0, 'fail': 0}
    ):
        out = await PayloadDeviceService.close_all()
    assert out['ok'] == 0


@_aio
async def test_list_alive_sessions_reads_current_snapshot() -> None:
    redis = AsyncMock()
    doc = {'registry': [{'type': 'serial', 'deviceId': 'serial:COM1', 'alive': True}]}
    with (
        patch('module_payload.collector_host.current_collector_host', return_value='lab'),
        patch('module_payload.collectors.redis_sync.create_sync_redis', lambda: MagicMock()),
        patch('module_payload.collectors.snapshot_store.load_snapshot', return_value=doc),
        patch(
            'module_payload.service.payload_session_service.PayloadSessionService.list_sessions',
            AsyncMock(return_value=[{'srcParam': 'serial:COM1'}]),
        ) as listed,
    ):
        out = await PayloadDeviceService.list_alive_sessions(redis)
    assert out == [{'srcParam': 'serial:COM1'}]
    assert listed.await_args.kwargs['host'] == 'lab'
    assert listed.await_args.kwargs['drop_missing'] is True
    alive = listed.await_args.kwargs['is_alive']
    assert alive('serial:COM1') is True
    assert alive('serial:COM9') is False


@_aio
async def test_list_alive_sessions_offline_does_not_scan() -> None:
    redis = AsyncMock()
    with (
        patch('module_payload.collector_host.current_collector_host', return_value='lab'),
        patch('module_payload.collectors.redis_sync.create_sync_redis', lambda: MagicMock()),
        patch('module_payload.collectors.snapshot_store.load_snapshot', return_value=None),
        patch(
            'module_payload.service.payload_session_service.PayloadSessionService.list_sessions',
            AsyncMock(),
        ) as listed,
    ):
        assert await PayloadDeviceService.list_alive_sessions(redis) == []
    listed.assert_not_awaited()


@_aio
async def test_wait_stream_ctrl_no_hb_and_ack() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=[Exception('hb'), b'1', Exception('ack-read')])
    await PayloadDeviceService._wait_stream_ctrl(redis, 'serial:COM1', 'flush')

    redis2 = AsyncMock()
    redis2.get = AsyncMock(side_effect=[b'hb', None, b'ack'])
    redis2.delete = AsyncMock(side_effect=Exception('del'))
    mgr = MagicMock()
    with (
        patch(
            'module_payload.service.payload_device_service.CollectorProcessManager.instance',
            return_value=mgr,
        ),
        patch('module_payload.service.payload_device_service.STREAM_FLUSH_WAIT_S', 0.05),
        patch('module_payload.service.payload_device_service.asyncio.sleep', AsyncMock()),
    ):
        await PayloadDeviceService._wait_stream_ctrl(redis2, 'serial:COM1', 'clear')
    mgr.notify_clear_io_stream.assert_called_once()

    redis3 = AsyncMock()
    redis3.get = AsyncMock(return_value=b'hb')
    mgr2 = MagicMock()
    mgr2.notify_flush_io_stream.side_effect = RuntimeError('gone')
    with patch(
        'module_payload.service.payload_device_service.CollectorProcessManager.instance',
        return_value=mgr2,
    ):
        await PayloadDeviceService._wait_stream_ctrl(redis3, 'serial:COM1', 'flush')


@_aio
async def test_get_and_clear_io_log() -> None:
    entries = [
        json.dumps({'seq': 1, 'msg': 'a'}),
        json.dumps({'seq': 2, 'msg': 'b'}).encode(),
        b'not-json',
        json.dumps({'seq': 3, 'msg': 'c'}),
    ]
    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=list(reversed(entries)))
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock()

    out = await PayloadDeviceService.get_io_log(redis, 'serial:COM1', since_seq=1, limit='bad', kind='stream')
    assert out['kind'] == 'stream'
    assert [i['seq'] for i in out['items']] == [2, 3]

    cleared = await PayloadDeviceService.clear_io_log(redis, 'serial:COM1', kind='stream')
    assert cleared['cleared'] is True
    assert cleared['kind'] == 'stream'


@_aio
async def test_get_device_status_can_and_serial() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=b'hb')
    with (
        patch(
            'module_payload.service.payload_device_service.get_status',
            AsyncMock(return_value={'connected': True, 'state': 'run', 'message': 'ok', 'stats': {}}),
        ),
        patch.object(PayloadDeviceService, '_is_device_alive', return_value=True),
        patch(
            'module_payload.service.payload_device_service.PayloadSessionService.get_session',
            AsyncMock(return_value={'parserId': 'tm_can_biu', 'assemblerId': 'can_biu', 'routes': []}),
        ),
    ):
        can = await PayloadDeviceService.get_device_status(redis, 'can:3:0:0')
        ser = await PayloadDeviceService.get_device_status(redis, 'serial:COM1')
    assert can['connected'] is True
    assert can['parserId'] == 'tm_can_biu'
    assert ser['connected'] is True


class _SnapRedis:
    """只提供会话扫描。"""

    def __init__(self, data: dict[str, str]) -> None:
        self.data = dict(data)
        self.deleted: list[str] = []

    async def scan_iter(self, match: str | None = None, count: int = 100):
        import fnmatch

        del count
        for key in list(self.data):
            if match is None or fnmatch.fnmatch(key, match):
                yield key

    async def get(self, key: str):
        return self.data.get(key)

    async def delete(self, key: str):
        self.deleted.append(key)
        self.data.pop(key, None)


@_aio
async def test_get_snapshot_lists_online_and_named_offline() -> None:
    import json

    from module_payload import redis_keys as rk

    calls: dict[str, object] = {}

    def fake_list(_client, hosts=None):
        calls['hosts'] = hosts
        if hosts:
            return [{
                'host': 'gk3',
                'online': False,
                'serialPorts': [],
                'canVendors': [],
                'defaultCanVendor': 0,
                'localAddrs': [],
                'registry': [],
            }]
        return [{
            'host': 'lab',
            'online': True,
            'serialPorts': [{'device': 'COM1'}],
            'canVendors': [{'key': 'PCIE', 'name': 'p', 'value': 3}],
            'defaultCanVendor': 3,
            'localAddrs': ['127.0.0.1'],
            'serialScanOk': True,
            'registry': [{
                'type': 'serial',
                'deviceId': 'serial:COM1',
                'alive': True,
                'config': {'baudrate': 9600},
            }],
        }]

    class _Client:
        def close(self) -> None:
            return None
    alive = json.dumps({'srcParam': 'serial:COM1', 'srcKind': 'serial', 'assemblerId': 'passthrough', 'routes': []})
    zombie = json.dumps({'srcParam': 'serial:COM9', 'srcKind': 'serial', 'assemblerId': 'passthrough', 'routes': []})
    redis = _SnapRedis({
        f'{rk.PREFIX}:collector:lab:session:serial:COM1': alive,
        f'{rk.PREFIX}:collector:lab:session:serial:COM9': zombie,
        f'{rk.PREFIX}:collector:gk3:session:serial:COM1': alive,
        f'{rk.PREFIX}:collector:other:session:serial:COM9': zombie,
    })

    with (
        patch('module_payload.collectors.redis_sync.create_sync_redis', lambda: _Client()),
        patch('module_payload.collectors.snapshot_store.list_machines', fake_list),
        patch(
            'module_payload.service.payload_device_service.PayloadSessionService.list_parser_options',
            return_value=[{'id': 'p'}],
        ),
        patch(
            'module_payload.service.payload_device_service.PayloadSessionService.list_assembler_options',
            return_value=[{'id': 'a'}],
        ),
    ):
        out = await PayloadDeviceService.get_snapshot(redis, 'can,sessions')
        named = await PayloadDeviceService.get_snapshot(redis, hosts=['gk3'])
    assert calls['hosts'] == ['gk3']
    assert 'parts' not in out
    assert out['parsers'] == [{'id': 'p'}]
    assert [item['host'] for item in out['devices']] == ['lab']
    lab = out['devices'][0]
    assert lab['online'] is True
    assert lab['serialOpened'][0]['port'] == 'COM1'
    assert lab['can'] == []
    assert [item['srcParam'] for item in lab['sessions']] == ['serial:COM1']
    assert f'{rk.PREFIX}:collector:lab:session:serial:COM9' in redis.deleted
    assert f'{rk.PREFIX}:collector:gk3:session:serial:COM1' in redis.data
    assert f'{rk.PREFIX}:collector:other:session:serial:COM9' in redis.data

    row = named['devices'][0]
    assert row['host'] == 'gk3'
    assert row['online'] is False
    assert row['sessions'] == []
    assert row['serialOpened'] == []
    assert row['can'] == []
    assert f'{rk.PREFIX}:collector:gk3:session:serial:COM1' in redis.data


@_aio
async def test_get_snapshot_named_online_does_not_drop_keys() -> None:
    import json

    from module_payload import redis_keys as rk

    def fake_list(_client, hosts=None):
        return [{
            'host': 'lab',
            'online': True,
            'serialPorts': [],
            'canVendors': [],
            'defaultCanVendor': 0,
            'localAddrs': [],
            'registry': [{
                'type': 'serial',
                'deviceId': 'serial:COM1',
                'alive': True,
                'config': {},
            }],
        }]

    class _Client:
        def close(self) -> None:
            return None

    alive = json.dumps({'srcParam': 'serial:COM1', 'srcKind': 'serial', 'assemblerId': 'passthrough', 'routes': []})
    zombie = json.dumps({'srcParam': 'serial:COM9', 'srcKind': 'serial', 'assemblerId': 'passthrough', 'routes': []})
    redis = _SnapRedis({
        f'{rk.PREFIX}:collector:lab:session:serial:COM1': alive,
        f'{rk.PREFIX}:collector:lab:session:serial:COM9': zombie,
    })
    with (
        patch('module_payload.collectors.redis_sync.create_sync_redis', lambda: _Client()),
        patch('module_payload.collectors.snapshot_store.list_machines', fake_list),
        patch(
            'module_payload.service.payload_device_service.PayloadSessionService.list_parser_options',
            return_value=[],
        ),
        patch(
            'module_payload.service.payload_device_service.PayloadSessionService.list_assembler_options',
            return_value=[],
        ),
    ):
        out = await PayloadDeviceService.get_snapshot(redis, hosts=['lab'])
    assert [item['srcParam'] for item in out['devices'][0]['sessions']] == ['serial:COM1']
    assert redis.deleted == []
    assert f'{rk.PREFIX}:collector:lab:session:serial:COM9' in redis.data


@_aio
async def test_get_snapshot_redis_down_returns_offline_without_raising() -> None:
    from redis.exceptions import ConnectionError as RedisConnectionError

    def boom():
        raise RedisConnectionError('down')

    with (
        patch('module_payload.collectors.redis_sync.create_sync_redis', boom),
        patch(
            'module_payload.service.payload_device_service.PayloadSessionService.list_parser_options',
            return_value=[{'id': 'p'}],
        ),
        patch(
            'module_payload.service.payload_device_service.PayloadSessionService.list_assembler_options',
            return_value=[{'id': 'a'}],
        ),
    ):
        named = await PayloadDeviceService.get_snapshot(AsyncMock(), hosts=['gk3'])
        plain = await PayloadDeviceService.get_snapshot(AsyncMock())
    assert named['parsers'] == [{'id': 'p'}]
    assert named['assemblers'] == [{'id': 'a'}]
    assert named['devices'][0]['host'] == 'gk3'
    assert named['devices'][0]['online'] is False
    assert named['devices'][0]['sessions'] == []
    assert plain['devices'] == []
    assert plain['parsers'] == [{'id': 'p'}]


@_aio
async def test_get_snapshot_unnamed_skips_timed_out_row() -> None:
    def fake_list(_client, hosts=None):
        return [
            {'host': 'lab', 'online': True},
            {'host': 'gk3', 'online': True},
        ]

    async def row(_redis, item, *, drop_missing=True):
        if item.get('host') == 'gk3':
            raise asyncio.TimeoutError()
        return {'host': item.get('host'), 'online': True, 'sessions': []}

    class _Client:
        def close(self) -> None:
            return None

    with (
        patch('module_payload.collectors.redis_sync.create_sync_redis', lambda: _Client()),
        patch('module_payload.collectors.snapshot_store.list_machines', fake_list),
        patch.object(PayloadDeviceService, '_device_row', row),
        patch(
            'module_payload.service.payload_device_service.PayloadSessionService.list_parser_options',
            return_value=[{'id': 'p'}],
        ),
        patch(
            'module_payload.service.payload_device_service.PayloadSessionService.list_assembler_options',
            return_value=[],
        ),
    ):
        out = await PayloadDeviceService.get_snapshot(AsyncMock())
    assert [item['host'] for item in out['devices']] == ['lab']
    assert out['parsers'] == [{'id': 'p'}]


# ---------------------------------------------------------------------------
# DeviceCanMixin
# ---------------------------------------------------------------------------


def test_pick_default_can_vendor() -> None:
    from module_payload.collectors.hardware import pick_default_can_vendor

    assert pick_default_can_vendor([]) == 0
    assert pick_default_can_vendor([{'key': 'A', 'name': 'x', 'value': 1}]) == 1
    assert (
        pick_default_can_vendor(
            [{'key': 'USB', 'name': 'u', 'value': 2}, {'key': 'PCIE', 'name': 'p', 'value': 3}]
        )
        == 3
    )


def test_build_can_vendors_from_sdk() -> None:
    class V:
        PCIE = 1
        USB = 2

        def __iter__(self):
            return iter([SimpleNamespace(name='PCIE', value=1), SimpleNamespace(name='USB', value=2)])

        # emulate IntEnum members
        def __init__(self):
            pass

    # Use real enum-like: objects that int() works on
    class Member:
        def __init__(self, name, value):
            self.name = name
            self._v = value

        def __int__(self):
            return self._v

    members = [Member('PCIE', 1), Member('USB', 2), Member('X', 3)]
    info_map = {
        1: None,
        2: 'usb-name',
        3: SimpleNamespace(name='named', channel_count='bad'),
    }

    class FakeVendorType:
        def __iter__(self):
            return iter(members)

    fake_gpcan = MagicMock()
    fake_gpcan.CanSdkClient.get_supported_device_list.return_value = info_map
    fake_gpcan.CanVendorType = FakeVendorType()
    with patch.dict('sys.modules', {'gpcan': fake_gpcan}):
        from module_payload.collectors.hardware import build_can_vendors

        vendors = build_can_vendors()
    assert len(vendors) == 3
    assert vendors[0]['name'] == 'PCIE'
    assert vendors[1]['name'] == 'usb-name'
    assert vendors[2]['channelCount'] == 2


def test_list_can_vendors_fallback() -> None:
    with patch(
        'module_payload.collectors.snapshot_store.sync_snapshot',
        return_value=None,
    ):
        out = DeviceCanMixin.list_can_vendors()
    assert out['vendors'] == []
    assert out['defaultVendor'] == 0


def test_list_can_channels_demo_and_real() -> None:
    mgr = MagicMock()
    mgr.list_opened.return_value = []
    with patch(
        'module_payload.service.device_can.CollectorProcessManager.instance',
        return_value=mgr,
    ):
        demo = DeviceCanMixin.list_can_channels()
    assert demo[0]['demo'] is True

    mgr.list_opened.return_value = [
        {
            'type': 'serial',
            'deviceId': 'serial:COM1',
            'channels': [],
            'config': {},
            'alive': True,
        },
        {
            'type': 'can',
            'deviceId': 'can:3:0',
            'channels': [0, 1],
            'alive': True,
            'config': {
                'baud_rate': 500,
                'channels': [
                    {'can_index': 0, 'baud_rate': 1000},
                    {'can_index': 'bad'},
                    'skip',
                ],
            },
        },
    ]
    with patch(
        'module_payload.service.device_can.CollectorProcessManager.instance',
        return_value=mgr,
    ):
        ch = DeviceCanMixin.list_can_channels()
    assert any(c['deviceId'] == 'can:3:0:0' and c['baudRate'] == 1000 for c in ch)
    assert any(c['deviceId'] == 'can:3:0:1' for c in ch)


def test_open_close_set_can_cable_sync() -> None:
    mgr = MagicMock()
    mgr.open_can_channel.return_value = ('can:3:0:0', True)
    mgr.set_can_cable.side_effect = [RuntimeError('ignore'), None, RuntimeError('boom')]
    r = MagicMock()
    body = CanOpenModel(vendor=3, dev_index=0, can_index=0, cable_flag=1, parser_id='')

    with (
        patch('module_payload.service.device_can.CollectorProcessManager.instance', return_value=mgr),
        patch('module_payload.service.device_can.redis_sync.create_sync_redis', return_value=r),
        patch(
            'module_payload.service.device_can.PayloadSessionService.open_session_sync',
            return_value={'srcParam': 'can:3:0:0'},
        ),
        patch(
            'module_payload.service.device_can.PayloadSessionService.validate_assembler_id',
            return_value='can_biu',
        ),
    ):
        out = DeviceCanMixin._open_can_sync(body)
    assert out['status'] == 'already_open'
    mgr.notify_session_changed.assert_called_once()

    mgr.open_can_channel.side_effect = RuntimeError('hw')
    with (
        patch('module_payload.service.device_can.CollectorProcessManager.instance', return_value=mgr),
        pytest.raises(ServiceException),
    ):
        DeviceCanMixin._open_can_sync(body)

    mgr.open_can_channel.side_effect = None
    mgr.open_can_channel.return_value = ('can:3:0:0', False)
    with (
        patch('module_payload.service.device_can.CollectorProcessManager.instance', return_value=mgr),
        patch('module_payload.service.device_can.redis_sync.create_sync_redis', return_value=r),
        patch(
            'module_payload.service.device_can.PayloadSessionService.open_session_sync',
            side_effect=ValueError('bad parser'),
        ),
        patch(
            'module_payload.service.device_can.PayloadSessionService.validate_assembler_id',
            return_value='can_biu',
        ),
        pytest.raises(ServiceException),
    ):
        DeviceCanMixin._open_can_sync(body)

    with (
        patch('module_payload.service.device_can.CollectorProcessManager.instance', return_value=mgr),
        patch('module_payload.service.device_can.redis_sync.create_sync_redis', return_value=r),
        patch('module_payload.service.device_can.PayloadSessionService.close_session_sync'),
    ):
        closed = DeviceCanMixin._close_can_sync(body)
    assert closed['status'] == 'closed'

    cable_body = SimpleNamespace(
        vendor=None,
        dev_index=None,
        can_index=None,
        device_id='can:3:0:1',
        node_addr_to=0x0D,
        cable_flag=None,
    )
    with patch('module_payload.service.device_can.CollectorProcessManager.instance', return_value=mgr):
        ok = DeviceCanMixin._set_can_cable_sync(cable_body)
    assert ok['deviceId'] == 'can:3:0:1'

    bad = SimpleNamespace(
        vendor=None,
        dev_index=None,
        can_index=None,
        device_id='',
        node_addr_to=None,
        cable_flag=None,
    )
    with pytest.raises(ServiceException) as ei:
        DeviceCanMixin._set_can_cable_sync(bad)
    assert '缺少' in (ei.value.message or '')

    both_none = SimpleNamespace(
        vendor=3,
        dev_index=0,
        can_index=0,
        device_id='',
        node_addr_to=None,
        cable_flag=None,
    )
    with pytest.raises(ServiceException) as ei:
        DeviceCanMixin._set_can_cable_sync(both_none)
    assert '至少' in (ei.value.message or '')

    with patch('module_payload.service.device_can.CollectorProcessManager.instance', return_value=mgr):
        with pytest.raises(ServiceException) as ei:
            DeviceCanMixin._set_can_cable_sync(
                SimpleNamespace(
                    vendor=3,
                    dev_index=0,
                    can_index=0,
                    device_id='',
                    node_addr_to=1,
                    cable_flag=0,
                )
            )
    assert 'boom' in (ei.value.message or '')


@_aio
async def test_can_async_wrappers() -> None:
    body = CanOpenModel()
    with patch.object(DeviceCanMixin, '_open_can_sync', return_value={'ok': 1}):
        assert (await DeviceCanMixin.open_can(body))['ok'] == 1
    with patch.object(DeviceCanMixin, '_close_can_sync', return_value={'ok': 2}):
        assert (await DeviceCanMixin.close_can(body))['ok'] == 2
    with patch.object(DeviceCanMixin, '_set_can_cable_sync', return_value={'ok': 3}):
        assert (await DeviceCanMixin.set_can_cable(body))['ok'] == 3


# ---------------------------------------------------------------------------
# DeviceSerialMixin
# ---------------------------------------------------------------------------


def test_serial_enumerate_and_reconcile() -> None:
    with patch(
        'module_payload.collectors.hw_probe.call_with_timeout',
        side_effect=ImportError('no'),
    ):
        DeviceSerialMixin._reconcile_missing_serial_ports()

    mgr = MagicMock()
    mgr.list_opened.return_value = [
        {'type': 'can', 'deviceId': 'can:3:0', 'alive': True},
        {'type': 'serial', 'deviceId': 'serial:COM9', 'alive': True},
        {'type': 'serial', 'deviceId': 'serial:COM1', 'alive': True},
        {'type': 'serial', 'deviceId': 'serial:', 'alive': True},
        {'type': 'serial', 'deviceId': 'serial:COM2', 'alive': False},
    ]
    with (
        patch(
            'module_payload.collectors.hw_probe.call_with_timeout',
            return_value=[SimpleNamespace(device='COM1')],
        ),
        patch(
            'module_payload.service.device_serial.CollectorProcessManager.instance',
            return_value=mgr,
        ),
        patch.object(DeviceSerialMixin, '_close_serial_sync', side_effect=RuntimeError('x')),
    ):
        DeviceSerialMixin._reconcile_missing_serial_ports()


def test_list_serial_opened_and_ports() -> None:
    mgr = MagicMock()
    mgr.list_opened.return_value = [
        {
            'type': 'serial',
            'deviceId': 'serial:COM3',
            'alive': True,
            'config': {
                'baudrate': 115200,
                'data_bits': 8,
                'stop_bits': 1,
                'parity': 'N',
                'flow_control': 'NONE',
            },
        },
        {'type': 'can', 'deviceId': 'can:3:0', 'alive': True, 'config': {}},
    ]
    with (
        patch.object(DeviceSerialMixin, '_reconcile_missing_serial_ports'),
        patch(
            'module_payload.service.device_serial.CollectorProcessManager.instance',
            return_value=mgr,
        ),
    ):
        opened = DeviceSerialMixin.list_serial_opened()
    assert opened[0]['port'] == 'COM3'

    with patch(
        'module_payload.collectors.snapshot_store.sync_snapshot',
        return_value={'serialPorts': [{'port': 'COM1', 'description': 'd'}]},
    ):
        assert DeviceSerialMixin.list_serial_ports()[0]['port'] == 'COM1'
    with patch(
        'module_payload.collectors.snapshot_store.sync_snapshot',
        return_value=None,
    ):
        assert DeviceSerialMixin.list_serial_ports() == []


def test_norm_flow_unknown_and_open_serial_paths() -> None:
    assert DeviceSerialMixin._norm_flow('CUSTOM') == 'CUSTOM'
    assert DeviceSerialMixin._serial_config_matches(
        {'baudrate': 1, 'data_bits': 8, 'stop_bits': 1, 'parity': 'N', 'flow_control': 'NONE'},
        {'baudrate': 1, 'data_bits': 7, 'stop_bits': 1, 'parity': 'N', 'flow_control': 'NONE'},
    ) is False
    assert DeviceSerialMixin._serial_config_matches(
        {'baudrate': 1, 'data_bits': 8, 'stop_bits': 1, 'parity': 'N', 'flow_control': 'NONE'},
        {'baudrate': 1, 'data_bits': 8, 'stop_bits': 2, 'parity': 'N', 'flow_control': 'NONE'},
    ) is False
    assert DeviceSerialMixin._serial_config_matches(
        {'baudrate': 1, 'data_bits': 8, 'stop_bits': 1, 'parity': 'E', 'flow_control': 'NONE'},
        {'baudrate': 1, 'data_bits': 8, 'stop_bits': 1, 'parity': 'N', 'flow_control': 'NONE'},
    ) is False
    assert DeviceSerialMixin._serial_config_matches(
        {'baudrate': 1, 'data_bits': 8, 'stop_bits': 1, 'parity': 'N', 'flow_control': 'RTS/CTS'},
        {'baudrate': 1, 'data_bits': 8, 'stop_bits': 1, 'parity': 'N', 'flow_control': 'NONE'},
    ) is False

    mgr = MagicMock()
    mgr.start_serial.return_value = ('serial:COM3', True)
    mgr.list_opened.return_value = [
        {
            'type': 'serial',
            'deviceId': 'serial:COM3',
            'config': {
                'baudrate': 9600,
                'data_bits': 8,
                'stop_bits': 1,
                'parity': 'N',
                'flow_control': 'NONE',
            },
        }
    ]
    body = SerialOpenModel(port='COM3', baudrate=115200)
    r = MagicMock()
    with patch('module_payload.service.device_serial.CollectorProcessManager.instance', return_value=mgr):
        with pytest.raises(ServiceException) as ei:
            DeviceSerialMixin._open_serial_sync(body)
    assert '不一致' in (ei.value.message or '')

    mgr.list_opened.return_value = [
        {
            'type': 'serial',
            'deviceId': 'serial:COM3',
            'config': {
                'baudrate': 115200,
                'data_bits': 8,
                'stop_bits': 1,
                'parity': 'N',
                'flow_control': 'none',
            },
        }
    ]
    with (
        patch('module_payload.service.device_serial.CollectorProcessManager.instance', return_value=mgr),
        patch('module_payload.service.device_serial.redis_sync.create_sync_redis', return_value=r),
        patch(
            'module_payload.service.device_serial.PayloadSessionService.open_session_sync',
            return_value={'srcParam': 'serial:COM3'},
        ),
        patch(
            'module_payload.service.device_serial.PayloadSessionService.validate_assembler_id',
            return_value='passthrough',
        ),
    ):
        out = DeviceSerialMixin._open_serial_sync(body)
    assert out['status'] == 'already_open'
    mgr.notify_session_changed.assert_called()

    mgr.start_serial.return_value = ('serial:COM3', False)
    with (
        patch('module_payload.service.device_serial.CollectorProcessManager.instance', return_value=mgr),
        patch('module_payload.service.device_serial.redis_sync.create_sync_redis', return_value=r),
        patch(
            'module_payload.service.device_serial.PayloadSessionService.open_session_sync',
            side_effect=ValueError('bad'),
        ),
        patch(
            'module_payload.service.device_serial.PayloadSessionService.validate_assembler_id',
            return_value='passthrough',
        ),
        pytest.raises(ServiceException),
    ):
        DeviceSerialMixin._open_serial_sync(body)

    with (
        patch('module_payload.service.device_serial.CollectorProcessManager.instance', return_value=mgr),
        patch('module_payload.service.device_serial.redis_sync.create_sync_redis', return_value=r),
        patch('module_payload.service.device_serial.PayloadSessionService.close_session_sync'),
    ):
        closed = DeviceSerialMixin._close_serial_sync('COM3')
    assert closed['status'] == 'closed'


@_aio
async def test_serial_async_wrappers() -> None:
    with patch.object(DeviceSerialMixin, '_open_serial_sync', return_value={'a': 1}):
        assert (await DeviceSerialMixin.open_serial(SerialOpenModel(port='COM1')))['a'] == 1
    with patch.object(DeviceSerialMixin, '_close_serial_sync', return_value={'b': 2}):
        assert (await DeviceSerialMixin.close_serial('COM1'))['b'] == 2


# ---------------------------------------------------------------------------
# DeviceNetMixin
# ---------------------------------------------------------------------------


def test_list_local_addresses_and_normalize() -> None:
    addrs = DeviceNetMixin.list_local_addresses()
    assert '0.0.0.0' in addrs
    assert '127.0.0.1' in addrs

    assert DeviceNetMixin._normalize_udp_remote(None, None) == ('', 0)
    assert DeviceNetMixin._normalize_udp_remote('1.2.3.4', 0) == ('1.2.3.4', 0)
    with pytest.raises(ValueError):
        DeviceNetMixin._normalize_udp_remote(None, 'bad')
    with pytest.raises(ValueError):
        DeviceNetMixin._normalize_udp_remote('', 70000)
    with pytest.raises(ValueError):
        DeviceNetMixin._normalize_udp_remote('', 80)


def test_open_close_net_sync() -> None:
    mgr = MagicMock()
    mgr.start_net.return_value = ('udp:0.0.0.0:9000', True)
    r = MagicMock()
    body = NetOpenModel(local_port=9000, remote_host='1.1.1.1', remote_port=53)
    with (
        patch('module_payload.service.device_net.CollectorProcessManager.instance', return_value=mgr),
        patch('module_payload.service.device_net.redis_sync.create_sync_redis', return_value=r),
        patch(
            'module_payload.service.device_net.PayloadSessionService.open_session_sync',
            return_value={'srcParam': 'udp:0.0.0.0:9000'},
        ),
        patch(
            'module_payload.service.device_net.PayloadSessionService.validate_assembler_id',
            return_value='passthrough',
        ),
    ):
        out = DeviceNetMixin._open_net_sync(body)
    assert out['status'] == 'already_open'
    mgr.apply_net_reuse_params.assert_called_once()

    mgr.start_net.return_value = ('udp:0.0.0.0:9000', False)
    with (
        patch('module_payload.service.device_net.CollectorProcessManager.instance', return_value=mgr),
        patch('module_payload.service.device_net.redis_sync.create_sync_redis', return_value=r),
        patch(
            'module_payload.service.device_net.PayloadSessionService.open_session_sync',
            side_effect=ValueError('bad'),
        ),
        patch(
            'module_payload.service.device_net.PayloadSessionService.validate_assembler_id',
            return_value='passthrough',
        ),
        pytest.raises(ServiceException),
    ):
        DeviceNetMixin._open_net_sync(body)

    with (
        patch('module_payload.service.device_net.CollectorProcessManager.instance', return_value=mgr),
        patch('module_payload.service.device_net.redis_sync.create_sync_redis', return_value=r),
        patch('module_payload.service.device_net.PayloadSessionService.close_session_sync'),
    ):
        closed = DeviceNetMixin._close_net_sync('udp', '0.0.0.0', 9000)
    assert closed['status'] == 'closed'

    mgr.list_opened.return_value = [
        {
            'type': 'net',
            'deviceId': 'udp:0.0.0.0:9000',
            'alive': True,
            'config': {
                'proto': 'udp',
                'local_host': '0.0.0.0',
                'local_port': 9000,
                'remote_host': '',
                'remote_port': 0,
            },
        },
        {'type': 'can', 'deviceId': 'can:3:0', 'alive': True, 'config': {}},
    ]
    with patch('module_payload.service.device_net.CollectorProcessManager.instance', return_value=mgr):
        opened = DeviceNetMixin.list_net_opened()
    assert len(opened) == 1


@_aio
async def test_net_async_wrappers() -> None:
    with patch.object(DeviceNetMixin, '_open_net_sync', return_value={'x': 1}):
        assert (await DeviceNetMixin.open_net(NetOpenModel(local_port=1)))['x'] == 1
    with patch.object(DeviceNetMixin, '_close_net_sync', return_value={'y': 2}):
        assert (await DeviceNetMixin.close_net('udp', '0.0.0.0', 1))['y'] == 2
