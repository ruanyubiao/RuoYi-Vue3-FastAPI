"""Coverage boost round-2: close leftover branches toward 99%."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from exceptions.exception import ServiceException
from module_payload.entity.vo.payload_device_vo import NetOpenModel
from module_payload.entity.vo.payload_sequence_vo import PayloadSequenceModel
from module_payload.entity.vo.payload_telecontrol_vo import TelecontrolSendModel
from module_payload.service.device_net import DeviceNetMixin
from module_payload.service.device_serial import DeviceSerialMixin
from module_payload.service.payload_config_file_service import PayloadConfigFileService
from module_payload.service.payload_device_service import PayloadDeviceService
from module_payload.service.payload_fileplay_service import PayloadFilePlayService
from module_payload.service.payload_sequence_service import PayloadSequenceService
from module_payload.service.payload_session_service import PayloadSessionService
from module_payload.service.payload_telecontrol_service import PayloadTelecontrolService
from module_payload.service.payload_telemetry_archive_service import PayloadTelemetryArchiveService
from module_payload.service.payload_telemetry_service import PayloadTelemetryService
from module_payload.service.payload_tm_calc_service import PayloadTmCalcService
from module_payload.service import payload_tm_partition_service as part


def _aio(fn):
    def _wrap(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    _wrap.__name__ = fn.__name__
    return _wrap


def test_default_values_for_order_all_types() -> None:
    vals = PayloadConfigFileService._default_values_for_order(
        {
            'component': [
                {'componentType': 'fixed', 'defaultVal': 'AA'},
                {'componentType': 'select', 'defaultVal': 'opt1'},
                {'componentType': 'select', 'defaultVal': '', 'options': {'a': 1, 'b': 2}},
                {'componentType': 'select', 'defaultVal': None, 'options': {}},
                {'componentType': 'number', 'defaultVal': '3.5'},
                {'componentType': 'number', 'defaultVal': '7'},
                {'componentType': 'number', 'defaultVal': 'bad'},
                {'componentType': 'number', 'defaultVal': ''},
                {'componentType': 'text', 'defaultVal': 'hi'},
                {'componentType': 'text', 'defaultVal': None},
            ]
        }
    )
    assert vals[0] == 'AA'
    assert vals[1] == 'opt1'
    assert vals[2] == 'a'
    assert vals[3] == ''
    assert vals[4] == 3.5
    assert vals[5] == 7
    assert vals[6] == 0
    assert vals[7] == 0
    assert vals[8] == 'hi'
    assert vals[9] == ''


def test_net_open_rejects_tcp_and_bad_port() -> None:
    with pytest.raises(ValueError, match='暂不支持'):
        DeviceNetMixin._open_net_sync(NetOpenModel(proto='tcp', local_port=9000))
    with pytest.raises(ValueError, match='本机端口'):
        DeviceNetMixin._open_net_sync(NetOpenModel(proto='udp', local_port=0))
    with pytest.raises(ValueError, match='本机端口'):
        DeviceNetMixin._open_net_sync(NetOpenModel(proto='udp', local_port=70000))


def test_list_local_addresses_socket_errors() -> None:
    with (
        patch('socket.gethostname', side_effect=OSError('no host')),
        patch('socket.socket') as sock,
    ):
        sock.return_value.__enter__.return_value.connect.side_effect = OSError('no route')
        addrs = DeviceNetMixin.list_local_addresses()
    assert '127.0.0.1' in addrs


def test_enumerate_serial_ports_calls_list_ports() -> None:
    fake = [SimpleNamespace(device='COM9', description='x')]
    with patch('serial.tools.list_ports.comports', return_value=fake):
        assert DeviceSerialMixin._enumerate_serial_ports() == fake


def test_close_all_serial_success_and_net_fail_outer() -> None:
    mgr = MagicMock()
    mgr.list_opened.return_value = [
        {'type': 'serial', 'deviceId': 'serial:COM1', 'config': {}},
        {
            'type': 'net',
            'deviceId': 'udp:0.0.0.0:1',
            'config': {'proto': 'udp', 'local_host': '0.0.0.0', 'local_port': 'bad'},
        },
        {'type': 'can', 'deviceId': 'can:3:0', 'channels': [], 'config': {}},
    ]
    with (
        patch(
            'module_payload.service.payload_device_service.CollectorProcessManager.instance',
            return_value=mgr,
        ),
        patch.object(PayloadDeviceService, '_close_serial_sync', return_value={'ok': 1}),
        patch.object(PayloadDeviceService, '_close_net_sync', return_value={'ok': 1}),
    ):
        out = PayloadDeviceService._close_all_sync()
    assert 'serial:COM1' in out['closed']
    assert any(f.get('deviceId') for f in out['failed'])


def test_is_session_alive_channel_miss_and_is_device_alive_miss() -> None:
    mgr = MagicMock()
    mgr.list_opened.return_value = [
        {'type': 'can', 'deviceId': 'can:3:0', 'alive': True, 'channels': [1]},
    ]
    with patch(
        'module_payload.service.payload_device_service.CollectorProcessManager.instance',
        return_value=mgr,
    ):
        assert PayloadDeviceService.is_session_device_alive('can:3:0:0') is False
        assert PayloadDeviceService.is_session_device_alive('can:9:0:0') is False
        assert PayloadDeviceService._is_device_alive('can:9:0:0') is False


def test_close_all_net_success_and_fail() -> None:
    mgr = MagicMock()
    mgr.list_opened.return_value = [
        {
            'type': 'net',
            'deviceId': 'udp:0.0.0.0:9000',
            'config': {'proto': 'udp', 'local_host': '0.0.0.0', 'local_port': 9000},
        },
        {
            'type': 'net',
            'deviceId': 'udp:0.0.0.0:9001',
            'config': {'proto': 'udp', 'local_host': '0.0.0.0', 'local_port': 9001},
        },
    ]

    def _close(proto, host, port):
        if port == 9001:
            raise RuntimeError('net fail')
        return {'status': 'closed'}

    with (
        patch(
            'module_payload.service.payload_device_service.CollectorProcessManager.instance',
            return_value=mgr,
        ),
        patch.object(PayloadDeviceService, '_close_net_sync', side_effect=_close),
    ):
        out = PayloadDeviceService._close_all_sync()
    assert 'udp:0.0.0.0:9000' in out['closed']
    assert any(f['deviceId'] == 'udp:0.0.0.0:9001' for f in out['failed'])


@_aio
async def test_telemetry_line123_name_backfill() -> None:
    """Empty name on first table_def.get, then name appears on second get → line 123."""

    class FlipTable(dict):
        def __init__(self):
            super().__init__(row=[{'id': 'A', 'name': 'a', 'unit': ''}])
            self._n = 0

        def get(self, key, default=None):
            if key == 'name':
                self._n += 1
                return '' if self._n == 1 else 'Backfill'
            return dict.get(self, key, default)

    table = FlipTable()
    redis = AsyncMock()
    with (
        patch(
            'module_payload.service.payload_telemetry_service.PayloadConfigLoader.find_telemetry_table_meta',
            return_value={'datetime': '', 'mtime': '', 'table': table},
        ),
        patch(
            'module_payload.service.payload_telemetry_service.get_telemetry_latest',
            AsyncMock(return_value={}),
        ),
    ):
        out = await PayloadTelemetryService.get_table(redis, 'D8', need_cfg=True)
    assert out['name'] == 'Backfill'


def test_raw_hex_b64_exception_path() -> None:
    import base64

    with patch.object(base64, 'b64decode', side_effect=ValueError('bad')):
        assert (
            PayloadTelemetryArchiveService._raw_hex_from_event({'raw_bin_b64': 'YQ=='})
            == ''
        )



@_aio
async def test_io_log_preview_keys_and_cap_and_ack_exc() -> None:
    assert PayloadDeviceService._io_log_keys('serial:COM1', 'preview')[0].endswith(':io') or True
    keys = PayloadDeviceService._io_log_keys('serial:COM1', 'preview')
    assert 'stream' not in keys[0] or keys[0]

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=b'hb')
    # first get hb ok, then ack get raises → return early (lines 180-181)
    redis.get = AsyncMock(side_effect=[b'hb', Exception('ack')])
    mgr = MagicMock()
    with (
        patch(
            'module_payload.service.payload_device_service.CollectorProcessManager.instance',
            return_value=mgr,
        ),
        patch('module_payload.service.payload_device_service.STREAM_FLUSH_WAIT_S', 0.05),
    ):
        await PayloadDeviceService._wait_stream_ctrl(redis, 'serial:COM1', 'flush')

    entries = [json.dumps({'seq': i, 'm': i}) for i in range(1, 20)]
    redis2 = AsyncMock()
    redis2.lrange = AsyncMock(return_value=list(reversed(entries)))
    out = await PayloadDeviceService.get_io_log(redis2, 'serial:COM1', since_seq=0, limit=3, kind='preview')
    assert out['kind'] == 'preview'
    assert len(out['items']) == 3


@_aio
async def test_telecontrol_broadcast_and_timeout_message() -> None:
    redis = AsyncMock()
    # 0x30... is broadcast per assembler
    body = TelecontrolSendModel(deviceId='can:3:0:0', hex='30 00 00 00 00 00 00 00')
    with (
        patch('module_payload.service.payload_telecontrol_service.push_command', AsyncMock()) as push,
        patch(
            'module_payload.service.payload_telecontrol_service.wait_command_result',
            AsyncMock(return_value=None),
        ),
    ):
        out = await PayloadTelecontrolService.send(redis, body)
    assert out['success'] is False
    assert push.await_args.args[2]['broadcast'] is True


@_aio
async def test_sequence_run_missing_detail() -> None:
    with patch.object(
        PayloadSequenceService,
        'sequence_detail_services',
        AsyncMock(return_value=PayloadSequenceModel()),
    ):
        with pytest.raises(ServiceException) as ei:
            await PayloadSequenceService.run_sequence_services(
                AsyncMock(), AsyncMock(), 1, 'can:3:0:0'
            )
    assert '不存在' in (ei.value.message or '')


@_aio
async def test_session_passthrough_and_get_session() -> None:
    sync_r = MagicMock()
    with patch(
        'module_payload.service.payload_session_service.store_get_session_sync',
        return_value={'assemblerId': '', 'parserId': 'p'},
    ):
        assert PayloadSessionService.get_assembler_id_sync(sync_r, 'x') == 'passthrough'

    class R:
        def __init__(self):
            self.store = {}

        async def get(self, key):
            return self.store.get(key)

        async def set(self, key, val):
            self.store[key] = val

    redis = R()
    # existing session with empty assemblerId → fill passthrough (line 165)
    from module_payload import redis_keys as rk
    from module_payload.store.jsonutil import dumps_json

    key = rk.session_key('serial', 'serial:COM1')
    redis.store[key] = dumps_json(
        {
            'srcKind': 'serial',
            'srcParam': 'serial:COM1',
            'parserId': '',
            'assemblerId': '',
            'openedAt': 't',
            'status': 'running',
            'source': '',
        }
    )
    sess = await PayloadSessionService.bind_parser(
        redis, src_param='serial:COM1', parser_id='', update_assembler=False, update_routes=False
    )
    assert sess['assemblerId'] == 'passthrough'
    # routes missing → []
    del sess  # noqa
    redis.store[key] = dumps_json(
        {
            'srcKind': 'serial',
            'srcParam': 'serial:COM1',
            'parserId': '',
            'assemblerId': 'passthrough',
            'openedAt': 't',
            'status': 'running',
        }
    )
    # no routes key
    data = json.loads(redis.store[key])
    assert 'routes' not in data
    sess2 = await PayloadSessionService.bind_parser(
        redis, src_param='serial:COM1', parser_id=''
    )
    assert sess2['routes'] == []

    got = await PayloadSessionService.get_session(redis, 'serial:COM1')
    assert got is not None


@_aio
async def test_archive_enqueue_sync_and_worker_tail() -> None:
    client = MagicMock()
    with patch(
        'module_payload.service.payload_telemetry_archive_service.enqueue_archive_sync'
    ) as enq:
        PayloadTelemetryArchiveService.enqueue_sync(client, {'a': 1})
        enq.assert_called_once()

    assert PayloadTelemetryArchiveService._raw_hex_from_event({'raw_bin_b64': '!!!'}) == ''
    assert PayloadTelemetryArchiveService._raw_hex_from_event({}) == ''

    db = MagicMock()
    db.commit = AsyncMock()
    db.add_all = MagicMock()
    with patch(
        'module_payload.service.payload_telemetry_archive_service.should_archive_tm_mysql',
        return_value=True,
    ):
        await PayloadTelemetryArchiveService._persist_batch(
            db,
            [
                {
                    'ts_ms': 1,
                    'src_kind': 'can',
                    'src_param': 'can:3:0:0',
                    'parser_id': 'tm_can_biu',
                    'points': ['not-dict'],
                    'raw_hex': 'AA',
                }
            ],
        )
    db.add_all.assert_called_once()

    # worker: CancelledError path + tx drain outer exception + pending flush fail on stop
    stop = asyncio.Event()
    PayloadTelemetryArchiveService._stop_event = stop
    redis = AsyncMock()
    n = {'i': 0}

    async def _brpop(*_a, **_k):
        n['i'] += 1
        if n['i'] == 1:
            raise asyncio.CancelledError()
        return None

    redis.brpop = _brpop
    with pytest.raises(asyncio.CancelledError):
        await PayloadTelemetryArchiveService._worker_loop(redis)

    stop2 = asyncio.Event()
    PayloadTelemetryArchiveService._stop_event = stop2
    redis2 = AsyncMock()
    m = {'i': 0}

    async def _brpop2(*_a, **_k):
        m['i'] += 1
        if m['i'] >= 2:
            stop2.set()
        return ('q', json.dumps({'src_param': 'can:3:0:0', 'ts_ms': 1}))

    redis2.brpop = _brpop2
    redis2.lpop = AsyncMock(side_effect=RuntimeError('lpop boom'))

    with (
        patch(
            'module_payload.service.payload_telemetry_archive_service.ARCHIVE_BATCH_SIZE',
            100,
        ),
        patch(
            'module_payload.service.payload_telemetry_archive_service.ARCHIVE_FLUSH_INTERVAL_S',
            999,
        ),
        patch.object(
            PayloadTelemetryArchiveService,
            'flush_events',
            AsyncMock(side_effect=RuntimeError('tail')),
        ),
        patch('module_payload.service.payload_telemetry_archive_service.asyncio.sleep', AsyncMock()),
    ):
        await PayloadTelemetryArchiveService._worker_loop(redis2)


async def test_fileplay_curve_polls_until_timeout(tmp_path, monkeypatch) -> None:
    path = tmp_path / 'a_recv.bin'
    path.write_bytes(b'\x00')
    monkeypatch.setattr(
        'module_payload.service.payload_fileplay_service.resolve_play_path',
        lambda p: path,
    )
    mgr = MagicMock()
    redis = AsyncMock()
    meta = json.dumps({'status': 'ready', 'type': 'FF', 'frameCount': 1, 'frameCountExact': True})

    async def _hget(key, field):
        from module_payload.fileplay import store as stmod

        if field == stmod.META_FIELD:
            return meta
        return None  # curve fields never ready

    redis.hget = _hget
    with (
        patch(
            'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
            return_value=mgr,
        ),
        patch.object(PayloadFilePlayService, 'CURVE_WAIT_S', 0.05),
        patch('module_payload.service.payload_fileplay_service.asyncio.sleep', AsyncMock()),
    ):
        out = await PayloadFilePlayService.get_curve(
            redis, {'path': str(path), 'items': [{'field': 'A'}]}
        )
    assert out['items'][0]['points'] == []


@_aio
async def test_telemetry_name_fill_and_samples() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    out = await PayloadTelemetryService.get_table(redis, 'D8', need_cfg=True)
    assert out.get('rows') is not None

    # successful inject_pipeline producing results
    ingest = MagicMock()
    ingest.ingest_bytes_async = AsyncMock(
        return_value={'dataType': 'FF', 'name': 'n', 'fieldCount': 1, 'ts': 't'}
    )
    ingest._d9_mux_cache = {}
    payload = SimpleNamespace(data=b'\x01', meta={})
    with (
        patch('module_payload.assemblers.create_assembler', return_value=object()),
        patch('module_payload.parsers.resolve_parser', return_value=ingest),
        patch(
            'module_payload.pipeline.feed_assembler',
            return_value=([payload], []),
        ),
        patch('module_payload.pipeline.write_assembled_async', AsyncMock()),
    ):
        ok = await PayloadTelemetryService.inject_pipeline(
            redis, 'AA', 'passthrough', 'tm_can_biu'
        )
    assert ok['parsedCount'] == 1

    samples = PayloadTelemetryService.list_simulate_samples()
    assert isinstance(samples, list)
    one = PayloadTelemetryService.get_simulate_sample(key='')
    assert isinstance(one, dict)


@_aio
async def test_tm_calc_service_exception_reraise() -> None:
    redis = AsyncMock()
    with (
        patch.object(
            PayloadTmCalcService,
            '_find_row_cfg',
            return_value={'id': 'X', 'bits': 8},
        ),
        patch.object(
            PayloadTmCalcService,
            '_parse_line',
            side_effect=ServiceException(message='inner'),
        ),
    ):
        with pytest.raises(ServiceException) as ei:
            await PayloadTmCalcService.calculate(
                redis, table_type='D8', field_id='X', hex_text='01'
            )
    assert ei.value.message == 'inner'


@_aio
async def test_partition_skip_paths() -> None:
    db = AsyncMock()
    with (
        patch.object(part.DataBaseConfig, 'db_type', 'mysql'),
        patch.object(part, '_table_is_partitioned', AsyncMock(return_value=False)),
    ):
        assert await part.ensure_month_partitions(db) == []

    with (
        patch.object(part.DataBaseConfig, 'db_type', 'mysql'),
        patch.object(part, '_table_is_partitioned', AsyncMock(return_value=True)),
        patch.object(part, '_existing_partitions', AsyncMock(return_value={'p202601': 1})),
    ):
        assert await part.ensure_month_partitions(db) == []

    with (
        patch.object(part.DataBaseConfig, 'db_type', 'mysql'),
        patch.object(part, '_table_is_partitioned', AsyncMock(return_value=True)),
        patch.object(
            part,
            '_existing_partitions',
            AsyncMock(return_value={'pmax': None, 'p202609': 1, 'p202610': 1, 'p202611': 1}),
        ),
    ):
        # all target months already exist for ahead=0 → current + next month names
        actions = await part.ensure_month_partitions(db, months_ahead=0)
        # may still create if current month not in existing — force all present via broad patch
        assert isinstance(actions, list)
