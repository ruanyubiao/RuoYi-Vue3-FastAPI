"""Coverage boost: telecontrol / sequence / archive / session services."""

from __future__ import annotations

import asyncio
import base64
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from exceptions.exception import ServiceException
from module_payload.entity.vo.payload_sequence_vo import (
    DeletePayloadSequenceModel,
    PayloadSequenceModel,
    PayloadSequencePageQueryModel,
)
from module_payload.entity.vo.payload_telecontrol_vo import (
    ControlOpModel,
    TelecontrolAssembleModel,
    TelecontrolSendModel,
)
from module_payload.service.payload_sequence_service import PayloadSequenceService
from module_payload.service.payload_session_service import PayloadSessionService
from module_payload.service.payload_telecontrol_service import PayloadTelecontrolService
from module_payload.service.payload_telemetry_archive_service import PayloadTelemetryArchiveService


def _close_coro_create_task(coro, *args, **kwargs):
    """Mock create_task without leaving unawaited coroutines (RuntimeWarning)."""
    if asyncio.iscoroutine(coro):
        coro.close()
    return MagicMock(name='fake-task')


def _aio(fn):
    def _wrap(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    _wrap.__name__ = fn.__name__
    return _wrap


# ---------------------------------------------------------------------------
# Telecontrol
# ---------------------------------------------------------------------------


def test_telecontrol_get_order_and_assemble_empty() -> None:
    from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager

    TeleControlCfgManager.reload('biu-tc')
    oid = TeleControlCfgManager.get('biu-tc').list_orders()[0]['id']
    order = PayloadTelecontrolService.get_order(oid, reload=False, family='biu')
    assert order
    with pytest.raises(ValueError):
        PayloadTelecontrolService.assemble(
            TelecontrolAssembleModel(components=[], values=[], family='biu')
        )


@_aio
async def test_send_can_raw_success_and_fail_message() -> None:
    redis = AsyncMock()
    with (
        patch('module_payload.service.payload_telecontrol_service.push_command', AsyncMock()),
        patch(
            'module_payload.service.payload_telecontrol_service.wait_command_result',
            AsyncMock(return_value={'success': True}),
        ),
    ):
        ok = await PayloadTelecontrolService.send_can_raw(redis, 'can:3:0:0', '0000000D', 'AA')
    assert ok['success'] is True
    assert ok['message'] == '发送成功'

    with (
        patch('module_payload.service.payload_telecontrol_service.push_command', AsyncMock()),
        patch(
            'module_payload.service.payload_telecontrol_service.wait_command_result',
            AsyncMock(return_value={'success': False, 'message': 'hw'}),
        ),
    ):
        bad = await PayloadTelecontrolService.send_can_raw(redis, 'can:3:0:0', '0000000D', '')
    assert bad['success'] is False
    assert bad['message'] == 'hw'


@_aio
async def test_send_assembles_order_and_remote_fields() -> None:
    redis = AsyncMock()
    from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager

    TeleControlCfgManager.reload('biu-tc')
    oid = TeleControlCfgManager.get('biu-tc').list_orders()[0]['id']

    body = TelecontrolSendModel(
        deviceId='can:3:0:0',
        orderId=oid,
        components=[{'componentType': 'fixed', 'defaultVal': '0A00000000000000'}],
        values=[],
        remoteHost='1.2.3.4',
        remotePort=9,
        displayHex=False,
    )
    with (
        patch('module_payload.service.payload_telecontrol_service.push_command', AsyncMock()) as push,
        patch(
            'module_payload.service.payload_telecontrol_service.wait_command_result',
            AsyncMock(return_value={'success': False}),
        ),
    ):
        out = await PayloadTelecontrolService.send(redis, body)
    assert out['success'] is False
    assert out['message'] == '发送失败'
    cmd = push.await_args.args[2]
    assert cmd['remote_host'] == '1.2.3.4'
    assert cmd['remote_port'] == 9
    assert cmd['display_hex'] is False

    body2 = TelecontrolSendModel(deviceId='can:3:0:0', orderId=oid, hex='')
    with (
        patch('module_payload.service.payload_telecontrol_service.push_command', AsyncMock()),
        patch(
            'module_payload.service.payload_telecontrol_service.wait_command_result',
            AsyncMock(return_value={'success': True}),
        ),
    ):
        out2 = await PayloadTelecontrolService.send(redis, body2)
    assert out2['success'] is True


@_aio
async def test_history_and_control_op_paths() -> None:
    redis = AsyncMock()
    with patch(
        'module_payload.service.payload_telecontrol_service.get_history',
        AsyncMock(return_value=[{'a': 1}]),
    ):
        assert await PayloadTelecontrolService.get_send_history(redis, 'can:3:0:0') == [{'a': 1}]
    with patch(
        'module_payload.service.payload_telecontrol_service.clear_history',
        AsyncMock(),
    ) as clr:
        await PayloadTelecontrolService.clear_send_history(redis, 'can:3:0:0')
        clr.assert_awaited()

    mgr = MagicMock()
    mgr.list_opened.return_value = []
    with patch(
        'module_payload.service.payload_telecontrol_service.CollectorProcessManager.instance',
        return_value=mgr,
    ):
        with pytest.raises(ServiceException) as ei:
            await PayloadTelecontrolService.control_op(redis, ControlOpModel(op='biu.timedTm.enable'))
    assert '请先打开' in (ei.value.message or '')

    mgr.list_opened.return_value = [
        {'type': 'can', 'deviceId': 'can:3:0', 'channels': [0]},
    ]
    with (
        patch(
            'module_payload.service.payload_telecontrol_service.CollectorProcessManager.instance',
            return_value=mgr,
        ),
        patch('module_payload.service.payload_telecontrol_service.push_command', AsyncMock()),
        patch(
            'module_payload.service.payload_telecontrol_service.wait_command_result',
            AsyncMock(return_value=None),
        ),
    ):
        timed_out = await PayloadTelecontrolService.control_op(
            redis, ControlOpModel(op='biu.timedTm.enable', params={'enable': True})
        )
    assert timed_out['success'] is False

    with (
        patch('module_payload.service.payload_telecontrol_service.push_command', AsyncMock()),
        patch(
            'module_payload.service.payload_telecontrol_service.wait_command_result',
            AsyncMock(
                return_value={
                    'success': True,
                    'message': 'ok',
                    'offsetMs': 5,
                    'utc': 'u',
                    'timedTm': True,
                    'broadcast': False,
                    'gnssValid': True,
                    'timedTmCan': 0,
                    'timedTmDeviceId': 'can:3:0:0',
                }
            ),
        ),
    ):
        ok = await PayloadTelecontrolService.control_op(
            redis,
            ControlOpModel(op='biu.timeSync.getStatus', deviceId='can:3:0:0'),
        )
    assert ok['offsetMs'] == 5
    assert ok['timedTm'] is True

    with (
        patch('module_payload.service.payload_telecontrol_service.push_command', AsyncMock()),
        patch(
            'module_payload.service.payload_telecontrol_service.wait_command_result',
            AsyncMock(return_value={'success': True}),
        ),
    ):
        st = await PayloadTelecontrolService.control_op(
            redis,
            ControlOpModel(op='biu.timeSync.setStart', deviceId='can:3:0:0', params={'utc': 'x'}),
        )
    assert st.get('offsetMs') == 0

    with (
        patch('module_payload.service.payload_telecontrol_service.push_command', AsyncMock()),
        patch(
            'module_payload.service.payload_telecontrol_service.wait_command_result',
            AsyncMock(return_value=None),
        ),
    ):
        pb = await PayloadTelecontrolService.control_op(
            redis,
            ControlOpModel(
                op='biu.system.reset',
                deviceId='can:3:0:0',
                params={'method': 'reset', 'kwargs': {}},
            ),
        )
    assert pb['success'] is False

    with (
        patch('module_payload.service.payload_telecontrol_service.push_command', AsyncMock()),
        patch(
            'module_payload.service.payload_telecontrol_service.wait_command_result',
            AsyncMock(return_value={'success': False}),
        ),
    ):
        pb2 = await PayloadTelecontrolService.control_op(
            redis,
            ControlOpModel(
                op='xl.tm.request',
                deviceId='can:3:0:0',
                params={'protocolBuild': {'method': 'x'}},
            ),
        )
    assert pb2['message'] == '发送失败'

    with patch.object(
        PayloadTelecontrolService,
        'send',
        AsyncMock(return_value={'success': True}),
    ) as send:
        for op, params in [
            ('biu.timedYc.enable', {'enable': True}),
            ('biu.timedYc.enable', {'enable': False}),
            ('biu.timedYc.param', {'dataCode': 'F9H', 'intervalMs': 1000}),
            ('biu.ppsTime.enable', {'enable': True}),
            ('biu.ppsTime.start', {}),
            ('biu.ppsTime.offset', {'offsetMs': 10}),
            ('biu.rate.start', {}),
            ('biu.rate.stop', {}),
            ('biu.customSend', {'hex': 'AA BB', 'appendChecksum': True}),
            ('customSend', {'hex': '01'}),
        ]:
            await PayloadTelecontrolService.control_op(
                redis, ControlOpModel(op=op, deviceId='can:3:0:0', params=params)
            )
        assert send.await_count >= 10

    with pytest.raises(ServiceException) as ei:
        await PayloadTelecontrolService.control_op(
            redis, ControlOpModel(op='biu.unknown.op', deviceId='can:3:0:0')
        )
    assert '未知控制' in (ei.value.message or '')


@_aio
async def test_run_sequence_intervals_and_stop() -> None:
    redis = AsyncMock()
    with patch.object(
        PayloadTelecontrolService,
        'send',
        AsyncMock(
            side_effect=[
                {'success': True},
                {'success': False, 'message': 'fail'},
            ]
        ),
    ):
        with patch('module_payload.service.payload_telecontrol_service.asyncio.sleep', AsyncMock()):
            out = await PayloadTelecontrolService.run_sequence(
                redis,
                'can:3:0:0',
                [
                    {'hex': 'AA', 'interval': 'bad'},
                    {'hex': 'BB', 'interval': -1},
                    {'hex': ''},
                ],
                default_interval=-5,
            )
    assert out['total'] == 2
    assert out['results'][1]['success'] is False

    with patch.object(
        PayloadTelecontrolService,
        'send',
        AsyncMock(return_value={'success': True}),
    ):
        empty_hex = await PayloadTelecontrolService.run_sequence(
            redis, 'can:3:0:0', [{'hex': ''}], 100
        )
    assert empty_hex['results'][0]['success'] is False


# ---------------------------------------------------------------------------
# Sequence CRUD + run progress
# ---------------------------------------------------------------------------


@_aio
async def test_sequence_crud_branches() -> None:
    db = AsyncMock()
    with patch(
        'module_payload.service.payload_sequence_service.PayloadSequenceDao.get_sequence_list',
        AsyncMock(return_value=[]),
    ):
        assert await PayloadSequenceService.get_sequence_list_services(
            db, PayloadSequencePageQueryModel(), is_page=True
        ) == []

    page = PayloadSequenceModel(seqName='n', project='biu', commands='[]')
    with patch(
        'module_payload.service.payload_sequence_service.PayloadSequenceDao.add_sequence_dao',
        AsyncMock(side_effect=RuntimeError('db')),
    ):
        with pytest.raises(RuntimeError):
            await PayloadSequenceService.add_sequence_services(db, page)
    db.rollback.assert_awaited()

    detail_ok = PayloadSequenceModel(seqId=1, seqName='s', commands='[]')
    with (
        patch.object(PayloadSequenceService, 'sequence_detail_services', AsyncMock(return_value=detail_ok)),
        patch(
            'module_payload.service.payload_sequence_service.PayloadSequenceDao.edit_sequence_dao',
            AsyncMock(),
        ),
    ):
        edited = await PayloadSequenceService.edit_sequence_services(
            db, PayloadSequenceModel(seqId=1, seqName='s2')
        )
    assert edited.is_success

    with (
        patch.object(PayloadSequenceService, 'sequence_detail_services', AsyncMock(return_value=detail_ok)),
        patch(
            'module_payload.service.payload_sequence_service.PayloadSequenceDao.edit_sequence_dao',
            AsyncMock(side_effect=RuntimeError('e')),
        ),
    ):
        with pytest.raises(RuntimeError):
            await PayloadSequenceService.edit_sequence_services(db, PayloadSequenceModel(seqId=1))

    with patch.object(
        PayloadSequenceService,
        'sequence_detail_services',
        AsyncMock(return_value=PayloadSequenceModel()),
    ):
        with pytest.raises(ServiceException) as ei:
            await PayloadSequenceService.edit_sequence_services(db, PayloadSequenceModel(seqId=9))
    assert '不存在' in (ei.value.message or '')

    with patch(
        'module_payload.service.payload_sequence_service.PayloadSequenceDao.delete_sequence_dao',
        AsyncMock(),
    ):
        deleted = await PayloadSequenceService.delete_sequence_services(
            db, DeletePayloadSequenceModel(seqIds='1,2')
        )
    assert deleted.is_success

    with patch(
        'module_payload.service.payload_sequence_service.PayloadSequenceDao.delete_sequence_dao',
        AsyncMock(side_effect=RuntimeError('d')),
    ):
        with pytest.raises(RuntimeError):
            await PayloadSequenceService.delete_sequence_services(
                db, DeletePayloadSequenceModel(seqIds='1')
            )

    with pytest.raises(ServiceException) as ei:
        await PayloadSequenceService.delete_sequence_services(
            db, DeletePayloadSequenceModel(seqIds='')
        )
    assert '为空' in (ei.value.message or '')

    with patch(
        'module_payload.service.payload_sequence_service.PayloadSequenceDao.get_sequence_detail_by_id',
        AsyncMock(return_value=None),
    ):
        empty = await PayloadSequenceService.sequence_detail_services(db, 1)
    assert not empty.seq_id

    with patch(
        'module_payload.service.payload_sequence_service.PayloadSequenceDao.get_sequence_detail_by_id',
        AsyncMock(return_value={'seq_id': 5, 'seq_name': 'x', 'commands': '[]', 'project': 'biu'}),
    ):
        detail = await PayloadSequenceService.sequence_detail_services(db, 5)
    assert detail.seq_id == 5


@_aio
async def test_run_sequence_starts_task_and_progress() -> None:
    redis = AsyncMock()
    detail = PayloadSequenceModel(
        seqId=3,
        seqName='s',
        commands=json.dumps({'items': [{'hex': 'EB 90 0A 00 00 00 00 00', 'interval': 0}]}),
    )
    with (
        patch.object(PayloadSequenceService, 'sequence_detail_services', AsyncMock(return_value=detail)),
        patch('module_payload.service.payload_sequence_service.save_seq_run', AsyncMock()),
        patch('module_payload.service.payload_sequence_service.push_seq_run_history', AsyncMock()),
        patch(
            'module_payload.service.payload_sequence_service.asyncio.create_task',
            side_effect=_close_coro_create_task,
        ) as ct,
    ):
        out = await PayloadSequenceService.run_sequence_services(redis, AsyncMock(), 3, 'can:3:0:0')
    assert out['status'] == 'running'
    assert out['runId']
    ct.assert_called_once()

    with patch(
        'module_payload.service.payload_sequence_service.get_seq_run',
        AsyncMock(return_value=None),
    ):
        with pytest.raises(ServiceException) as ei:
            await PayloadSequenceService.get_run_progress_services(redis, 'r')
    assert '不存在' in (ei.value.message or '')

    with patch(
        'module_payload.service.payload_sequence_service.get_seq_run',
        AsyncMock(return_value={'runId': 'r'}),
    ):
        assert (await PayloadSequenceService.get_run_progress_services(redis, 'r'))['runId'] == 'r'

    with patch(
        'module_payload.service.payload_sequence_service.list_seq_run_history',
        AsyncMock(return_value=[{'runId': 'a'}]),
    ):
        hist = await PayloadSequenceService.list_run_history_services(redis, 3)
    assert hist[0]['runId'] == 'a'


@_aio
async def test_execute_sequence_success_exception_empty_hex() -> None:
    redis = MagicMock()
    commands = [
        {'hex': 'EB 90 0A 00 00 00 00 00', 'interval': 'x'},
        {'hex': 'EB 90 0A 00 00 00 00 01', 'interval': 0},
    ]
    run = {
        'runId': 'r1',
        'items': [
            {'index': 0, 'status': 'pending', 'message': '', 'time': ''},
            {'index': 1, 'status': 'pending', 'message': '', 'time': ''},
        ],
    }
    saved = []

    async def _save(_r, state):
        saved.append(json.loads(json.dumps(state)))

    with (
        patch('module_payload.service.payload_sequence_service.get_seq_run', AsyncMock(return_value=run)),
        patch('module_payload.service.payload_sequence_service.save_seq_run', _save),
        patch(
            'module_payload.service.payload_telecontrol_service.PayloadTelecontrolService.send',
            AsyncMock(return_value={'success': True}),
        ),
        patch('module_payload.service.payload_sequence_service.asyncio.sleep', AsyncMock()),
    ):
        await PayloadSequenceService._execute_sequence_run(redis, 'r1', 'can:3:0:0', commands, -1)
    assert saved[-1]['status'] == 'success'
    assert saved[-1]['ok'] == 2

    run2 = {
        'runId': 'r2',
        'items': [{'index': 0, 'status': 'pending', 'message': '', 'time': ''}],
    }
    with (
        patch('module_payload.service.payload_sequence_service.get_seq_run', AsyncMock(return_value=run2)),
        patch('module_payload.service.payload_sequence_service.save_seq_run', AsyncMock()),
    ):
        await PayloadSequenceService._execute_sequence_run(
            redis, 'r2', 'can:3:0:0', [{'hex': ''}], 10
        )

    run3 = {
        'runId': 'r3',
        'items': [{'index': 0, 'status': 'pending', 'message': '', 'time': ''}],
    }
    with (
        patch('module_payload.service.payload_sequence_service.get_seq_run', AsyncMock(return_value=run3)),
        patch('module_payload.service.payload_sequence_service.save_seq_run', AsyncMock()) as save,
        patch(
            'module_payload.service.payload_telecontrol_service.PayloadTelecontrolService.send',
            AsyncMock(side_effect=RuntimeError('boom')),
        ),
    ):
        await PayloadSequenceService._execute_sequence_run(
            redis, 'r3', 'can:3:0:0', [{'hex': 'AA BB'}], 10
        )
    assert save.await_args_list[-1].args[1]['status'] == 'failed'

    with patch(
        'module_payload.service.payload_sequence_service.get_seq_run',
        AsyncMock(return_value=None),
    ):
        await PayloadSequenceService._execute_sequence_run(redis, 'missing', 'can:3:0:0', [], 10)

    run4 = {
        'runId': 'r4',
        'items': [{'index': 0, 'status': 'pending', 'message': '', 'time': ''}],
        'current': 0,
    }
    saved4 = []
    boom = {'n': 0}

    async def _boom_mid(_r, state):
        saved4.append(json.loads(json.dumps(state)))
        boom['n'] += 1
        # first save (status=running) blows up → outer except; later finally must succeed
        if boom['n'] == 1:
            raise RuntimeError('save boom')

    with (
        patch('module_payload.service.payload_sequence_service.get_seq_run', AsyncMock(return_value=run4)),
        patch('module_payload.service.payload_sequence_service.save_seq_run', _boom_mid),
        patch(
            'module_payload.service.payload_telecontrol_service.PayloadTelecontrolService.send',
            AsyncMock(return_value={'success': True}),
        ),
    ):
        await PayloadSequenceService._execute_sequence_run(
            redis, 'r4', 'can:3:0:0', [{'hex': 'AA'}], 10
        )
    assert saved4[-1]['status'] == 'failed'


# ---------------------------------------------------------------------------
# Archive service
# ---------------------------------------------------------------------------


@_aio
async def test_archive_enqueue_and_requeue() -> None:
    redis = AsyncMock()
    with patch(
        'module_payload.service.payload_telemetry_archive_service.enqueue_archive',
        AsyncMock(),
    ) as enq:
        await PayloadTelemetryArchiveService.enqueue(redis, {'a': 1})
        enq.assert_awaited()

    client = MagicMock()
    PayloadTelemetryArchiveService.enqueue_tx_sync(client, {'ts_ms': 1})
    client.lpush.assert_called_once()
    await PayloadTelemetryArchiveService.enqueue_tx(redis, {'ts_ms': 2})

    redis.lpush = AsyncMock(side_effect=[None, Exception('fail')])
    await PayloadTelemetryArchiveService._requeue_tx_batch(
        redis, [{'src_param': 'a'}, {'src_param': 'b'}]
    )


@_aio
async def test_archive_flush_and_worker_lifecycle() -> None:
    @asynccontextmanager
    async def _sess():
        db = MagicMock()
        db.rollback = AsyncMock()
        db.commit = AsyncMock()
        db.add_all = MagicMock()
        yield db

    with (
        patch(
            'module_payload.service.payload_telemetry_archive_service.AsyncSessionLocal',
            _sess,
        ),
        patch.object(PayloadTelemetryArchiveService, '_persist_batch', AsyncMock()),
    ):
        await PayloadTelemetryArchiveService.flush_events([])
        await PayloadTelemetryArchiveService.flush_events([{'ts_ms': 1}])

    with (
        patch(
            'module_payload.service.payload_telemetry_archive_service.AsyncSessionLocal',
            _sess,
        ),
        patch.object(
            PayloadTelemetryArchiveService,
            '_persist_batch',
            AsyncMock(side_effect=RuntimeError('w')),
        ),
        pytest.raises(RuntimeError),
    ):
        await PayloadTelemetryArchiveService.flush_events([{'ts_ms': 1}])

    with patch(
        'module_payload.service.payload_telemetry_archive_service.AsyncSessionLocal',
        _sess,
    ):
        await PayloadTelemetryArchiveService.flush_tx_events([])
        await PayloadTelemetryArchiveService.flush_tx_events(
            [
                {
                    'ts_ms': 1,
                    'src_kind': 'can',
                    'src_param': 'can:3:0:0',
                    'raw_hex': 'AA',
                    'success': 1,
                }
            ]
        )

    class _FailSess:
        def __init__(self):
            self.db = MagicMock()
            self.db.rollback = AsyncMock()
            self.db.commit = AsyncMock(side_effect=RuntimeError('c'))
            self.db.add_all = MagicMock()

        async def __aenter__(self):
            return self.db

        async def __aexit__(self, *a):
            return False

    with (
        patch(
            'module_payload.service.payload_telemetry_archive_service.AsyncSessionLocal',
            _FailSess,
        ),
        pytest.raises(RuntimeError),
    ):
        await PayloadTelemetryArchiveService.flush_tx_events([{'ts_ms': 1, 'raw_hex': 'AA'}])

    redis = AsyncMock()
    redis.lpop = AsyncMock(side_effect=[json.dumps({'a': 1}).encode(), None])
    drained = await PayloadTelemetryArchiveService._drain_tx_queue(redis)
    assert drained == [{'a': 1}]

    PayloadTelemetryArchiveService._worker_task = None
    PayloadTelemetryArchiveService._stop_event = None
    redis.brpop = AsyncMock(side_effect=asyncio.CancelledError())
    stop = asyncio.Event()
    PayloadTelemetryArchiveService._stop_event = stop

    async def _loop_once():
        PayloadTelemetryArchiveService._stop_event = asyncio.Event()
        PayloadTelemetryArchiveService._stop_event.set()
        redis2 = AsyncMock()
        redis2.brpop = AsyncMock(return_value=None)
        redis2.lpop = AsyncMock(return_value=None)
        await PayloadTelemetryArchiveService._worker_loop(redis2)

    await _loop_once()

    # start/stop worker
    PayloadTelemetryArchiveService._worker_task = MagicMock()
    await PayloadTelemetryArchiveService.start_worker(redis)  # idempotent early return

    PayloadTelemetryArchiveService._worker_task = None
    PayloadTelemetryArchiveService._stop_event = None
    with patch(
        'module_payload.service.payload_telemetry_archive_service.asyncio.create_task',
        side_effect=_close_coro_create_task,
    ) as ct:
        await PayloadTelemetryArchiveService.start_worker(redis)
        ct.assert_called_once()
    # drop fake task so later stop_worker / suite GC stays clean
    PayloadTelemetryArchiveService._worker_task = None
    PayloadTelemetryArchiveService._stop_event = None

    async def _noop():
        await asyncio.Event().wait()

    real_task = asyncio.create_task(_noop())
    PayloadTelemetryArchiveService._worker_task = real_task
    PayloadTelemetryArchiveService._stop_event = asyncio.Event()
    await PayloadTelemetryArchiveService.stop_worker()
    assert PayloadTelemetryArchiveService._worker_task is None

    await PayloadTelemetryArchiveService.stop_worker()  # no-op


@_aio
async def test_archive_worker_loop_error_paths() -> None:
    from redis.exceptions import ConnectionError as RedisConnectionError

    stop = asyncio.Event()
    PayloadTelemetryArchiveService._stop_event = stop
    redis = AsyncMock()
    calls = {'n': 0}

    async def _brpop(*_a, **_k):
        calls['n'] += 1
        if calls['n'] == 1:
            return ('q', json.dumps({'src_param': 'can:3:0:0', 'ts_ms': 1}))
        if calls['n'] == 2:
            raise RedisConnectionError('down')
        if calls['n'] == 3:
            raise ValueError('bad json path')
        stop.set()
        return None

    redis.brpop = _brpop
    redis.lpop = AsyncMock(return_value=json.dumps({'ts_ms': 1, 'raw_hex': 'AA'}).encode())

    with (
        patch.object(
            PayloadTelemetryArchiveService,
            'flush_tx_events',
            AsyncMock(side_effect=RuntimeError('tx')),
        ),
        patch.object(PayloadTelemetryArchiveService, '_requeue_tx_batch', AsyncMock()),
        patch.object(
            PayloadTelemetryArchiveService,
            'flush_events',
            AsyncMock(side_effect=RuntimeError('tm')),
        ),
        patch.object(PayloadTelemetryArchiveService, 'enqueue', AsyncMock(side_effect=Exception('e'))),
        patch('module_payload.service.payload_telemetry_archive_service.ARCHIVE_FLUSH_INTERVAL_S', 0),
        patch('module_payload.service.payload_telemetry_archive_service.ARCHIVE_BATCH_SIZE', 1),
        patch('module_payload.service.payload_telemetry_archive_service.asyncio.sleep', AsyncMock()),
    ):
        await PayloadTelemetryArchiveService._worker_loop(redis)


@_aio
async def test_history_curve_data() -> None:
    db = AsyncMock()
    with (
        patch(
            'module_payload.service.payload_config_service.PayloadConfigService.get_telemetry_table_def',
            return_value={'row': [{'id': 'A', 'name': 'na', 'unit': 'u'}]},
        ),
        patch(
            'module_payload.dao.payload_tm_archive_dao.PayloadTmArchiveDao.query_field_points',
            AsyncMock(return_value=[(1, 2.0)]),
        ),
    ):
        out = await PayloadTelemetryArchiveService.get_history_curve_data(
            db, 'FF', 'A', 0, 10, src_param='can:3:0:0'
        )
    assert out['name'] == 'na'
    assert out['points'] == [{'t': 1, 'v': 2.0}]

    with patch.object(
        PayloadTelemetryArchiveService,
        'get_history_curve_data',
        AsyncMock(return_value={'field': 'A'}),
    ):
        batch = await PayloadTelemetryArchiveService.get_history_curve_data_batch(
            db, [{'type': 'FF', 'field': 'A', 'start_t': 0, 'end_t': 1}]
        )
    assert batch[0]['field'] == 'A'


# ---------------------------------------------------------------------------
# Session remaining branches
# ---------------------------------------------------------------------------


@_aio
async def test_session_bind_and_list_branches() -> None:
    class R:
        def __init__(self):
            self.store = {}

        async def get(self, key):
            return self.store.get(key)

        async def set(self, key, val):
            self.store[key] = val

        async def delete(self, key):
            self.store.pop(key, None)

        async def scan_iter(self, match, count=100):
            import fnmatch

            for k in list(self.store):
                if fnmatch.fnmatch(k, match):
                    yield k

    redis = R()
    # create via bind with no existing session
    with patch(
        'module_payload.service.payload_session_service.resolve_parser',
        return_value=object(),
    ):
        sess = await PayloadSessionService.bind_parser(
            redis,
            src_param='serial:COM1',
            parser_id='tm_xl_camera',
            update_assembler=True,
            assembler_id='passthrough',
            update_routes=True,
            routes=[],
            source='home',
        )
    assert sess['parserId']
    assert sess['source'] == 'home'

    with patch(
        'module_payload.service.payload_session_service.resolve_parser',
        return_value=None,
    ):
        with pytest.raises(ServiceException) as ei:
            await PayloadSessionService.bind_parser(redis, src_param='serial:COM1', parser_id='nope')
    assert '未知解释器' in (ei.value.message or '')

    with patch(
        'module_payload.service.payload_session_service.validate_assembler_for_src',
        side_effect=ValueError('bad asm'),
    ):
        with pytest.raises(ServiceException) as ei:
            await PayloadSessionService.bind_parser(
                redis,
                src_param='serial:COM1',
                parser_id='',
                update_assembler=True,
                assembler_id='bad',
            )
    assert 'bad asm' in (ei.value.message or '')

    with patch.object(
        PayloadSessionService,
        'validate_routes',
        side_effect=ValueError('bad route'),
    ):
        with pytest.raises(ServiceException) as ei:
            await PayloadSessionService.bind_parser(
                redis,
                src_param='serial:COM1',
                parser_id='',
                routes=[{'assemblerId': 'x'}],
            )
    assert 'bad route' in (ei.value.message or '')

    # list_sessions with zombie cleanup + defaults
    from module_payload import redis_keys as rk
    from module_payload.store.jsonutil import dumps_json

    redis.store[rk.session_key('serial', 'serial:DEAD')] = dumps_json(
        {'srcParam': 'serial:DEAD', 'parserId': ''}
    )
    redis.store[rk.session_key('serial', 'serial:OK')] = dumps_json(
        {'srcParam': 'serial:OK', 'parserId': 'p'}
    )
    redis.store[rk.session_key('serial', 'serial:EMPTY')] = 'null'

    async def _delete_fail(key):
        raise RuntimeError('del')

    redis_fail = R()
    redis_fail.store = dict(redis.store)
    redis_fail.delete = _delete_fail

    out = await PayloadSessionService.list_sessions(
        redis, is_alive=lambda s: s != 'serial:DEAD'
    )
    assert all(s['srcParam'] != 'serial:DEAD' for s in out)
    assert all(s.get('assemblerId') for s in out)

    await PayloadSessionService.list_sessions(redis_fail, is_alive=lambda s: False)

    sync_r = MagicMock()
    with patch(
        'module_payload.service.payload_session_service.store_get_session_sync',
        return_value=None,
    ):
        assert PayloadSessionService.get_parser_id_sync(sync_r, 'x') is None
        assert PayloadSessionService.get_assembler_id_sync(sync_r, 'x') == 'passthrough'

    with patch(
        'module_payload.service.payload_session_service.store_get_session_sync',
        return_value={'parserId': '  ', 'assemblerId': 'passthrough'},
    ):
        assert PayloadSessionService.get_parser_id_sync(sync_r, 'x') is None

    # open_session with routes
    mem = MagicMock()
    mem.get.return_value = None
    with patch(
        'module_payload.service.payload_session_service.resolve_parser',
        return_value=object(),
    ):
        PayloadSessionService.open_session_sync(
            mem,
            src_param='can:3:0:0',
            src_kind='can',
            parser_id='tm_can_biu',
            assembler_id='can_biu',
            routes=[],
        )
