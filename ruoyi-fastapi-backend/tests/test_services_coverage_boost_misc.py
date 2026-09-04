"""Coverage boost: fileplay / config / telemetry / calc / canplay / camera / lvds / partition."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from exceptions.exception import ServiceException
from module_payload.service.payload_camera_service import PayloadCameraService
from module_payload.service.payload_canplay_service import PayloadCanPlayService
from module_payload.service.payload_config_file_service import PayloadConfigFileService
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.service.payload_fileplay_service import PayloadFilePlayService, _safe_filename
from module_payload.service.payload_lvds_service import PayloadLvdsService
from module_payload.service.payload_telemetry_service import PayloadTelemetryService
from module_payload.service.payload_tm_calc_service import PayloadTmCalcService
from module_payload.service import payload_tm_partition_service as part


def _aio(fn):
    def _wrap(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    _wrap.__name__ = fn.__name__
    return _wrap


# ---------------------------------------------------------------------------
# FilePlay
# ---------------------------------------------------------------------------


def test_safe_filename_and_browse_locate() -> None:
    assert _safe_filename('a/b/c.dat') == 'c.dat'
    with pytest.raises(ValueError):
        _safe_filename('..')
    with patch(
        'module_payload.service.payload_fileplay_service.list_dir',
        return_value={'entries': []},
    ):
        assert PayloadFilePlayService.browse('upload')['entries'] == []
    with patch(
        'module_payload.service.payload_fileplay_service.locate_play_file',
        return_value={'found': False},
    ):
        assert PayloadFilePlayService.locate('/x')['found'] is False


async def test_fileplay_upload_chunk(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.service.payload_fileplay_service.get_upload_log_data_dir',
        lambda: tmp_path,
    )

    class UF:
        filename = 'demo_recv.bin'

        def __init__(self, chunks):
            self._chunks = list(chunks)

        async def read(self, _n):
            if not self._chunks:
                return b''
            return self._chunks.pop(0)

    out1 = await PayloadFilePlayService.upload_chunk(
        UF([b'ab', b'cd']), 'demo_recv.bin', chunk_index=0, total_chunks=2
    )
    assert out1['done'] is False
    assert out1['path'].endswith('.part')
    out2 = await PayloadFilePlayService.upload_chunk(
        UF([b'ef']), 'demo_recv.bin', chunk_index=1, total_chunks=2
    )
    assert out2['done'] is True
    assert (tmp_path / 'demo_recv.bin').read_bytes() == b'abcdef'


async def test_fileplay_parse_status_frame_curve(tmp_path, monkeypatch) -> None:
    path = tmp_path / 'x_recv.bin'
    path.write_bytes(b'\x00')
    monkeypatch.setattr(
        'module_payload.service.payload_fileplay_service.resolve_play_path',
        lambda p: path,
    )
    mgr = MagicMock()
    redis = AsyncMock()
    meta_ready = json.dumps(
        {
            'status': 'ready',
            'type': 'FF',
            'frameCount': 2,
            'frameCountExact': True,
            'hasTimestamp': False,
            'startTsMs': 0,
            'kind': 'can',
            'path': str(path),
        }
    )
    meta_err = json.dumps({'status': 'error', 'error': 'bad', 'frameCount': 0})
    frame = json.dumps({'rows': []})

    redis.hget = AsyncMock(side_effect=[meta_ready, frame])
    with patch(
        'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
        return_value=mgr,
    ):
        parsed = await PayloadFilePlayService.parse(redis, 'ff', str(path))
    assert parsed['status'] == 'ready'
    assert parsed['frame']['rows'] == []

    redis.hget = AsyncMock(side_effect=[meta_err])
    err = await PayloadFilePlayService.get_status(redis, str(path))
    assert err['status'] == 'error'
    assert err['error'] == 'bad'

    redis.hget = AsyncMock(side_effect=[meta_ready, frame])
    st = await PayloadFilePlayService.get_status(redis, str(path))
    assert st['frame']

    # get_frame waits then finds
    redis.hget = AsyncMock(side_effect=[None, None, frame, meta_ready])
    with (
        patch(
            'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
            return_value=mgr,
        ),
        patch('module_payload.service.payload_fileplay_service.asyncio.sleep', AsyncMock()),
        patch.object(PayloadFilePlayService, 'FRAME_WAIT_S', 0.01),
    ):
        fr = await PayloadFilePlayService.get_frame(redis, str(path), 1)
    assert fr['frame']
    mgr.ensure_frame.assert_called()

    # curve empty fields
    redis.hget = AsyncMock(return_value=meta_ready)
    empty = await PayloadFilePlayService.get_curve(redis, {'path': str(path), 'items': []})
    assert empty['items'] == []

    # curve with fields ready immediately
    points = json.dumps([{'t': 1, 'v': 2}])
    redis.hget = AsyncMock(
        side_effect=lambda key, field: {
            'c:A': points,
            'meta': meta_ready,
        }.get(field, meta_ready if field == 'meta' or field.startswith('m') else points)
    )
    # simpler: custom hget
    store_meta = {'meta': meta_ready, 'c:A': points, 'c:B': points}

    async def _hget(key, field):
        from module_payload.fileplay import store as stmod

        if field == stmod.META_FIELD:
            return store_meta['meta']
        return store_meta.get(field)

    redis.hget = _hget
    with (
        patch(
            'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
            return_value=mgr,
        ),
        patch.object(PayloadFilePlayService, 'CURVE_WAIT_S', 0.01),
    ):
        curve = await PayloadFilePlayService.get_curve(
            redis,
            {
                'path': str(path),
                'items': [{'field': 'A'}, {'Field': 'B'}],
                'startIndex': 1,
                'endIndex': 2,
            },
        )
    assert len(curve['items']) == 2
    mgr.send.assert_called()


# ---------------------------------------------------------------------------
# Config file service
# ---------------------------------------------------------------------------


def test_config_file_service_paths(tmp_path, monkeypatch) -> None:
    row = {'name': 'cfg_device_connect.json'}
    fake = tmp_path / 'cfg_device_connect.json'
    fake.write_text('{"a":1}\n', encoding='utf-8')
    with (
        patch(
            'module_payload.service.payload_config_file_service.list_config_file_info',
            return_value=[row],
        ),
        patch(
            'module_payload.service.payload_config_file_service.resolve_config_file',
            return_value=fake,
        ),
    ):
        paths = PayloadConfigFileService.discover_files()
        assert paths[0] == fake
        assert PayloadConfigFileService.list_files() == [row]
        assert PayloadConfigFileService.resolve_safe('cfg_device_connect.json') == fake

    with (
        patch(
            'module_payload.service.payload_config_file_service.require_config_name',
            return_value='missing.json',
        ),
        patch(
            'module_payload.service.payload_config_file_service.resolve_config_file',
            return_value=tmp_path / 'nope.json',
        ),
        pytest.raises(FileNotFoundError),
    ):
        PayloadConfigFileService.resolve_safe('missing.json')

    with (
        patch(
            'module_payload.service.payload_config_file_service.stat_config_file',
            return_value={'name': 'x.json', 'mtime': 1},
        ),
        patch(
            'module_payload.service.payload_config_file_service.read_config_text',
            return_value='{}',
        ),
    ):
        info = PayloadConfigFileService.read_text('x.json')
    assert info['content'] == '{}'

    with (
        patch.object(PayloadConfigFileService, 'resolve_safe', return_value=fake),
        patch(
            'module_payload.service.payload_config_file_service.require_config_name',
            return_value='cfg_device_connect.json',
        ),
        patch(
            'module_payload.service.payload_config_file_service.save_config_text',
        ) as save,
        patch.object(PayloadConfigFileService, 'reload_one', return_value={}),
        patch.object(
            PayloadConfigFileService,
            'read_text',
            return_value={'name': 'cfg_device_connect.json'},
        ),
    ):
        PayloadConfigFileService.save_text('cfg_device_connect.json', '{"k":1}')
        saved = save.call_args.args[1]
        assert 'datetime' in saved

    with (
        patch.object(PayloadConfigFileService, 'resolve_safe', return_value=fake),
        patch(
            'module_payload.service.payload_config_file_service.require_config_name',
            return_value='x.json',
        ),
        pytest.raises(ValueError, match='JSON'),
    ):
        PayloadConfigFileService.save_text('x.json', 'not-json')

    with (
        patch.object(PayloadConfigFileService, 'resolve_safe', return_value=fake),
        patch(
            'module_payload.service.payload_config_file_service.require_config_name',
            return_value='x.json',
        ),
        pytest.raises(ValueError, match='根节点'),
    ):
        PayloadConfigFileService.save_text('x.json', '"str"')

    mgr = MagicMock()
    with (
        patch(
            'module_payload.service.payload_config_file_service.PayloadConfigLoader.reload_all'
        ),
        patch(
            'module_payload.collectors.process_manager.CollectorProcessManager.instance',
            return_value=mgr,
        ),
        patch.object(PayloadConfigFileService, 'list_files', return_value=[{'name': 'a'}]),
    ):
        out = PayloadConfigFileService.reload_runtime()
    assert out['count'] == 1
    mgr.notify_reload_tm_cfg.assert_called()

    with (
        patch(
            'module_payload.service.payload_config_file_service.PayloadConfigLoader.reload_all'
        ),
        patch(
            'module_payload.collectors.process_manager.CollectorProcessManager.instance',
            side_effect=RuntimeError('no'),
        ),
        patch.object(PayloadConfigFileService, 'list_files', return_value=[]),
    ):
        PayloadConfigFileService.reload_runtime()

    tm_path = tmp_path / 'biu-TeleMetryCfg.json'
    tm_path.write_text('{}', encoding='utf-8')
    with (
        patch.object(PayloadConfigFileService, 'resolve_safe', return_value=tm_path),
        patch(
            'module_payload.service.payload_config_file_service.PayloadConfigLoader.reload_file',
            return_value='key',
        ),
        patch(
            'module_payload.collectors.process_manager.CollectorProcessManager.instance',
            return_value=mgr,
        ),
        patch.object(PayloadConfigFileService, 'read_text', return_value={'mtime': 1, 'datetime': 'd'}),
    ):
        one = PayloadConfigFileService.reload_one(tm_path.name)
    assert one['cacheKey'] == 'key'

    with (
        patch.object(PayloadConfigFileService, 'resolve_safe', return_value=tm_path),
        patch(
            'module_payload.service.payload_config_file_service.PayloadConfigLoader.reload_file',
            return_value='key',
        ),
        patch(
            'module_payload.collectors.process_manager.CollectorProcessManager.instance',
            side_effect=RuntimeError('x'),
        ),
        patch.object(PayloadConfigFileService, 'read_text', return_value={}),
    ):
        PayloadConfigFileService.reload_one(tm_path.name)


def test_export_orders_defaults_branches() -> None:
    cfg = {
        'page': [{'orderList': ['o1', 'o1', '']}],
        'order': {
            'o1': {
                'id': 'o1',
                'name': 'n',
                'component': [{'componentType': 'fixed', 'defaultVal': 'AA'}],
            },
            'o2': 'bad',
            'o3': {
                'id': 'o3',
                'name': 'fail',
                'component': [{'componentType': 'fixed', 'defaultVal': 'BB'}],
            },
        },
    }
    with (
        patch(
            'module_payload.service.payload_config_file_service.require_config_name',
            return_value='biu-TeleControlCfg.json',
        ),
        patch(
            'module_payload.service.payload_config_file_service.read_config_json',
            return_value=cfg,
        ),
        patch(
            'module_payload.cfg.telecontrol_cfg.TeleControlCfgManager.assemble_order_dict',
            side_effect=[
                {'hex': 'AA BB', 'length': 0},
                RuntimeError('asm fail'),
            ],
        ),
        patch(
            'module_payload.cfg.telecontrol_cfg.cfg_id_from_filename',
            return_value='biu-tc',
        ),
    ):
        rows = PayloadConfigFileService.export_orders_defaults('biu-TeleControlCfg.json')
    assert any(r['len'] == 2 for r in rows)
    assert any(r.get('error') for r in rows)

    with (
        patch(
            'module_payload.service.payload_config_file_service.require_config_name',
            return_value='x.json',
        ),
        pytest.raises(ValueError, match='仅支持遥控'),
    ):
        PayloadConfigFileService.export_orders_defaults('x.json')

    with (
        patch(
            'module_payload.service.payload_config_file_service.require_config_name',
            return_value='biu-TeleControlCfg.json',
        ),
        patch(
            'module_payload.service.payload_config_file_service.read_config_json',
            return_value=[],
        ),
        pytest.raises(ValueError, match='根节点'),
    ):
        PayloadConfigFileService.export_orders_defaults('biu-TeleControlCfg.json')

    with (
        patch(
            'module_payload.service.payload_config_file_service.require_config_name',
            return_value='biu-TeleControlCfg.json',
        ),
        patch(
            'module_payload.service.payload_config_file_service.read_config_json',
            return_value={'order': {}},
        ),
    ):
        assert PayloadConfigFileService.export_orders_defaults('biu-TeleControlCfg.json') == []


# ---------------------------------------------------------------------------
# Telemetry / config / calc / camera / canplay / lvds / partition
# ---------------------------------------------------------------------------


@_aio
async def test_telemetry_curve_batch_and_inject_errors() -> None:
    redis = AsyncMock()
    with patch(
        'module_payload.service.payload_telemetry_service.get_curve_points',
        AsyncMock(return_value=[{'t': 1, 'v': 1.0}]),
    ):
        # hit name/unit from table row
        fields = PayloadTelemetryService.get_fields('D8')
        fid = fields[0]['id'] if fields else 'x'
        one = await PayloadTelemetryService.get_curve_data(redis, 'D8', fid)
        assert one['points']
        batch = await PayloadTelemetryService.get_curve_data_batch(
            redis, [{'type': 'D8', 'field': fid, 'limit': 10, 'since_t': 0}]
        )
        assert len(batch) == 1

    with (
        patch(
            'module_payload.parsers.biu_can_tm.BiuCanTmIngest.ingest_hex_async',
            AsyncMock(side_effect=ValueError('bad')),
        ),
        pytest.raises(ServiceException),
    ):
        await PayloadTelemetryService.inject_can_yc(redis, 'AA')

    with (
        patch(
            'module_payload.parsers.biu_can_tm.BiuCanTmIngest.ingest_hex_async',
            AsyncMock(side_effect=RuntimeError('rt')),
        ),
        pytest.raises(ServiceException),
    ):
        await PayloadTelemetryService.inject_can_yc(redis, 'AA')

    with pytest.raises(ServiceException) as ei:
        await PayloadTelemetryService.inject_pipeline(redis, 'AA', 'passthrough', '')
    assert '解析器' in (ei.value.message or '')

    with pytest.raises(ServiceException) as ei:
        await PayloadTelemetryService.inject_pipeline(redis, 'AA', 'passthrough', 'no_such_parser')
    assert '未知' in (ei.value.message or '') or '不可用' in (ei.value.message or '')

    with pytest.raises(ServiceException) as ei:
        await PayloadTelemetryService.inject_pipeline(
            redis, 'ZZ', 'passthrough', 'tm_can_biu'
        )
    assert 'HEX' in (ei.value.message or '')

    with pytest.raises(ServiceException) as ei:
        await PayloadTelemetryService.inject_pipeline(
            redis, '', 'passthrough', 'tm_can_biu'
        )
    assert '空' in (ei.value.message or '')


@_aio
async def test_inject_pipeline_assembler_and_parser_errors() -> None:
    redis = AsyncMock()
    ingest = MagicMock()
    ingest.ingest_bytes_async = AsyncMock(side_effect=ValueError('parse'))
    ingest._d9_mux_cache = {'http:devtest': 1}

    class Asm:
        def __init__(self):
            pass

    with (
        patch('module_payload.assemblers.create_assembler', return_value=Asm()),
        patch('module_payload.parsers.resolve_parser', return_value=ingest),
        patch(
            'module_payload.pipeline.feed_assembler',
            side_effect=RuntimeError('asm boom'),
        ),
    ):
        with pytest.raises(ServiceException) as ei:
            await PayloadTelemetryService.inject_pipeline(
                redis, 'AA BB', 'passthrough', 'tm_can_biu'
            )
    assert '组装异常' in (ei.value.message or '')

    payload = SimpleNamespace(data=b'\x01\x02', meta={})
    with (
        patch('module_payload.assemblers.create_assembler', return_value=Asm()),
        patch('module_payload.parsers.resolve_parser', return_value=ingest),
        patch(
            'module_payload.pipeline.feed_assembler',
            return_value=([payload], ['warn']),
        ),
        patch('module_payload.pipeline.write_assembled_async', AsyncMock()),
    ):
        with pytest.raises(ServiceException) as ei:
            await PayloadTelemetryService.inject_pipeline(
                redis, 'AA BB', 'passthrough', 'tm_can_biu'
            )
    assert 'parse' in (ei.value.message or '')

    ingest.ingest_bytes_async = AsyncMock(side_effect=RuntimeError('rt'))
    with (
        patch('module_payload.assemblers.create_assembler', return_value=Asm()),
        patch('module_payload.parsers.resolve_parser', return_value=ingest),
        patch(
            'module_payload.pipeline.feed_assembler',
            return_value=([payload], []),
        ),
        patch('module_payload.pipeline.write_assembled_async', AsyncMock()),
    ):
        with pytest.raises(ServiceException) as ei:
            await PayloadTelemetryService.inject_pipeline(
                redis, 'AA BB', 'passthrough', 'tm_can_biu'
            )
    assert 'rt' in (ei.value.message or '')

    with (
        patch('module_payload.assemblers.create_assembler', return_value=Asm()),
        patch('module_payload.parsers.resolve_parser', return_value=ingest),
        patch(
            'module_payload.pipeline.feed_assembler',
            return_value=([], ['缺子包']),
        ),
    ):
        with pytest.raises(ServiceException) as ei:
            await PayloadTelemetryService.inject_pipeline(
                redis, 'AA BB', 'passthrough', 'tm_can_biu'
            )
    assert '缺子包' in (ei.value.message or '')

    empty_payload = SimpleNamespace(data=b'', meta={})
    ingest.ingest_bytes_async = AsyncMock(return_value={'dataType': 'FF'})
    with (
        patch('module_payload.assemblers.create_assembler', return_value=Asm()),
        patch('module_payload.parsers.resolve_parser', return_value=ingest),
        patch(
            'module_payload.pipeline.feed_assembler',
            return_value=([empty_payload], []),
        ),
        patch('module_payload.pipeline.write_assembled_async', AsyncMock()),
    ):
        with pytest.raises(ServiceException) as ei:
            await PayloadTelemetryService.inject_pipeline(
                redis, 'AA BB', 'passthrough', 'tm_can_biu'
            )
    assert '未产出' in (ei.value.message or '')


@_aio
async def test_get_table_need_cfg_name_fill() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    with patch(
        'module_payload.service.payload_telemetry_service.PayloadConfigService.get_telemetry_table_def',
        return_value={'name': '表名', 'row': [{'id': 'A', 'name': 'a', 'unit': ''}]},
    ):
        # force empty name in cfg_meta path via get_table internals — need_cfg True
        out = await PayloadTelemetryService.get_table(redis, 'D8', need_cfg=True)
    assert out['rows']


def test_config_camera_and_board_telemetry() -> None:
    cam = PayloadConfigService.get_camera_telemetry_config()
    assert 'page' in cam and 'table' in cam
    board = PayloadConfigService.get_xl_board_telemetry_config('rkdj')
    assert board['board'] == 'rkdj'
    assert 'tableKey' in board


@_aio
async def test_tm_calc_remaining_branches() -> None:
    assert PayloadTmCalcService._find_row_cfg('D8', '') is None
    row = {'id': 'X', 'bits': 8, 'bytepos': 3, 'name': 'n', 'unit': 'u'}
    with patch(
        'TeleMetryParser.parse_line_hex',
        return_value=SimpleNamespace(
            id='X', name='n', unit='u', show='1', calc_val=1, hex='01', err=False, val=None
        ),
    ):
        ln = PayloadTmCalcService._parse_line(row, '01')
    assert ln.show == '1'

    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=[None, b'', '{"a":1}'])
    hist = await PayloadTmCalcService.get_history(redis)
    assert hist == [{'a': 1}]
    redis.delete = AsyncMock()
    await PayloadTmCalcService.clear_history(redis)
    redis.delete.assert_awaited()

    with (
        patch.object(PayloadTmCalcService, '_find_row_cfg', return_value=row),
        patch.object(
            PayloadTmCalcService,
            '_parse_line',
            side_effect=RuntimeError('parse boom'),
        ),
    ):
        with pytest.raises(ServiceException) as ei:
            await PayloadTmCalcService.calculate(
                redis, table_type='D8', field_id='X', hex_text='01'
            )
    assert '解析失败' in (ei.value.message or '')


@_aio
async def test_camera_bytes_and_status() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=b'YmFzZTY0')
    with (
        patch(
            'module_payload.service.payload_camera_service.get_image_meta',
            AsyncMock(return_value={'format': 'png', 'phase': 'p'}),
        ),
        patch(
            'module_payload.service.payload_camera_service.get_status',
            AsyncMock(return_value={'connected': False, 'message': '', 'state': ''}),
        ),
    ):
        img = await PayloadCameraService.get_image(redis, 'COM4')
    assert img['image']['data'] == 'YmFzZTY0'

    with patch(
        'module_payload.service.payload_camera_service.get_status',
        AsyncMock(return_value={'connected': True, 'message': 'ok', 'state': 'run'}),
    ):
        st = await PayloadCameraService.get_camera_status(redis, 'COM4')
    assert st['connected'] is True
    assert st['deviceId'] == 'serial:COM4'


def test_canplay_row_to_snap_raw_hex_paths() -> None:
    parsed = SimpleNamespace(fields=[{'id': 'A', 'name': 'A', 'value': 1, 'show': '1', 'unit': '', 'hex': ''}], name='N')
    row = SimpleNamespace(
        raw_hex='AA BB',
        parsed_json={},
        points_json={},
        ts_ms=1_700_000_000_000,
        src_param='mysql',
    )
    with patch(
        'module_payload.service.payload_canplay_service.BiuCanTmIngest.parse_hex',
        return_value=parsed,
    ):
        snap = PayloadCanPlayService._row_to_snap(row, 'BIU:FF', 1)
    assert snap['name'] == 'N'
    assert snap['rows']

    with patch(
        'module_payload.service.payload_canplay_service.BiuCanTmIngest.parse_hex',
        side_effect=RuntimeError('bad'),
    ):
        snap2 = PayloadCanPlayService._row_to_snap(
            SimpleNamespace(
                raw_hex='AA',
                parsed_json={'name': 'from-json'},
                points_json={'P': 3},
                ts_ms=0,
                src_param='x',
            ),
            'BIU:FF',
            2,
        )
    assert snap2['name'] == 'from-json'
    assert snap2['rows']


def test_lvds_skips_empty_id() -> None:
    with patch(
        'module_payload.service.payload_lvds_service.PayloadConfigService.get_telemetry_table_def',
        return_value={'row': [{'id': '', 'name': 'x'}, {'id': 's1', 'name': 'S1', 'unit': 'u'}]},
    ):
        signals = PayloadLvdsService.list_signals('7E9B')
    assert [s['id'] for s in signals] == ['s1']


@_aio
async def test_tm_partition_helpers_and_ensure() -> None:
    assert part._next_month(2026, 12) == (2027, 1)
    assert part._partition_name(2026, 3) == 'p202603'
    assert part._month_start_ms(2026, 1) > 0

    db = AsyncMock()
    result = MagicMock()
    result.scalar.return_value = 2
    result.all.return_value = [
        ('p202601', '100'),
        ('pmax', 'MAXVALUE'),
        ('', '1'),
        ('pbad', 'xx'),
    ]
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()

    assert await part._table_is_partitioned(db, 'payload_tm_frame') is True
    existing = await part._existing_partitions(db, 'payload_tm_frame')
    assert existing['pmax'] is None
    assert existing['p202601'] == 100
    assert existing['pbad'] is None

    with patch.object(part.DataBaseConfig, 'db_type', 'sqlite'):
        assert await part.ensure_month_partitions(db) == []

    with (
        patch.object(part.DataBaseConfig, 'db_type', 'mysql'),
        patch.object(part, '_table_is_partitioned', AsyncMock(return_value=True)),
        patch.object(
            part,
            '_existing_partitions',
            AsyncMock(return_value={'pmax': None}),
        ),
    ):
        actions = await part.ensure_month_partitions(db, months_ahead=0)
    assert actions
    db.commit.assert_awaited()

    class _Sess:
        def __init__(self):
            self.db = AsyncMock()
            self.db.rollback = AsyncMock()

        async def __aenter__(self):
            return self.db

        async def __aexit__(self, *a):
            return False

    with (
        patch('config.database.AsyncSessionLocal', _Sess),
        patch.object(part, 'ensure_month_partitions', AsyncMock(return_value=['t:p'])),
    ):
        await part.run_partition_maintenance()

    with (
        patch('config.database.AsyncSessionLocal', _Sess),
        patch.object(
            part,
            'ensure_month_partitions',
            AsyncMock(side_effect=RuntimeError('fail')),
        ),
    ):
        await part.run_partition_maintenance()
