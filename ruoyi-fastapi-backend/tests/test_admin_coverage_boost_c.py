"""Raise module_admin coverage: log service + log dao."""

from __future__ import annotations

from contextlib import contextmanager
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from exceptions.exception import ServiceException
from module_admin.dao.log_dao import LoginLogDao, OperationLogDao
from module_admin.entity.vo.log_vo import (
    DeleteLoginLogModel,
    DeleteOperLogModel,
    LogininforModel,
    LoginLogPageQueryModel,
    OperLogModel,
    OperLogPageQueryModel,
    UnlockUser,
)
from module_admin.service.dict_service import DictDataService
from module_admin.service.log_service import (
    LogAggregatorService,
    LoginLogService,
    LogQueueService,
    OperationLogService,
)


@contextmanager
def expect_service_error(substr: str):
    with pytest.raises(ServiceException) as ei:
        yield
    assert substr in (ei.value.message or '')


def _request_with_redis(redis: object | None = None) -> Request:
    redis = redis if redis is not None else AsyncMock()
    app = SimpleNamespace(state=SimpleNamespace(redis=redis))
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0'},
        'http_version': '1.1',
        'method': 'GET',
        'scheme': 'http',
        'path': '/',
        'raw_path': b'/',
        'query_string': b'',
        'headers': [],
        'client': ('127.0.0.1', 1),
        'server': ('test', 80),
        'root_path': '',
        'app': app,
    }
    return Request(scope)


def _db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# operation / login log services
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_operation_log_service() -> None:
    db = _db()
    with patch.object(OperationLogDao, 'get_operation_log_list', new=AsyncMock(return_value=[])):
        await OperationLogService.get_operation_log_list_services(db, OperLogPageQueryModel(), False)

    with patch.object(OperationLogDao, 'add_operation_log_dao', new=AsyncMock()):
        assert (await OperationLogService.add_operation_log_services(db, OperLogModel(title='t'))).is_success
    with patch.object(OperationLogDao, 'add_operation_log_dao', new=AsyncMock(side_effect=RuntimeError('e'))):
        with pytest.raises(RuntimeError):
            await OperationLogService.add_operation_log_services(db, OperLogModel(title='t'))

    with expect_service_error('为空'):
        await OperationLogService.delete_operation_log_services(db, DeleteOperLogModel(operIds=''))
    with patch.object(OperationLogDao, 'delete_operation_log_dao', new=AsyncMock()):
        assert (
            await OperationLogService.delete_operation_log_services(db, DeleteOperLogModel(operIds='1,2'))
        ).is_success
    with patch.object(OperationLogDao, 'delete_operation_log_dao', new=AsyncMock(side_effect=RuntimeError('e'))):
        with pytest.raises(RuntimeError):
            await OperationLogService.delete_operation_log_services(db, DeleteOperLogModel(operIds='1'))

    with patch.object(OperationLogDao, 'clear_operation_log_dao', new=AsyncMock()):
        assert (await OperationLogService.clear_operation_log_services(db)).is_success
    with patch.object(OperationLogDao, 'clear_operation_log_dao', new=AsyncMock(side_effect=RuntimeError('e'))):
        with pytest.raises(RuntimeError):
            await OperationLogService.clear_operation_log_services(db)

    req = _request_with_redis()
    with (
        patch.object(
            DictDataService,
            'query_dict_data_list_from_cache_services',
            new=AsyncMock(return_value=[{'dictLabel': '新增', 'dictValue': '1'}]),
        ),
        patch('module_admin.service.log_service.ExcelUtil.export_list2excel', return_value=b'op'),
    ):
        assert (
            await OperationLogService.export_operation_log_list_services(
                req,
                [{'status': 0, 'businessType': '1'}, {'status': 1, 'businessType': '9'}],
            )
            == b'op'
        )


@pytest.mark.asyncio
async def test_login_log_service() -> None:
    db = _db()
    with patch.object(LoginLogDao, 'get_login_log_list', new=AsyncMock(return_value=[])):
        await LoginLogService.get_login_log_list_services(db, LoginLogPageQueryModel(), False)

    with patch.object(LoginLogDao, 'add_login_log_dao', new=AsyncMock()):
        assert (await LoginLogService.add_login_log_services(db, LogininforModel(userName='u'))).is_success
    with patch.object(LoginLogDao, 'add_login_log_dao', new=AsyncMock(side_effect=RuntimeError('e'))):
        with pytest.raises(RuntimeError):
            await LoginLogService.add_login_log_services(db, LogininforModel(userName='u'))

    with expect_service_error('为空'):
        await LoginLogService.delete_login_log_services(db, DeleteLoginLogModel(infoIds=''))
    with patch.object(LoginLogDao, 'delete_login_log_dao', new=AsyncMock()):
        assert (await LoginLogService.delete_login_log_services(db, DeleteLoginLogModel(infoIds='1'))).is_success
    with patch.object(LoginLogDao, 'delete_login_log_dao', new=AsyncMock(side_effect=RuntimeError('e'))):
        with pytest.raises(RuntimeError):
            await LoginLogService.delete_login_log_services(db, DeleteLoginLogModel(infoIds='1'))

    with patch.object(LoginLogDao, 'clear_login_log_dao', new=AsyncMock()):
        assert (await LoginLogService.clear_login_log_services(db)).is_success
    with patch.object(LoginLogDao, 'clear_login_log_dao', new=AsyncMock(side_effect=RuntimeError('e'))):
        with pytest.raises(RuntimeError):
            await LoginLogService.clear_login_log_services(db)

    redis = AsyncMock()
    redis.get = AsyncMock(return_value='1')
    redis.delete = AsyncMock()
    req = _request_with_redis(redis)
    assert (await LoginLogService.unlock_user_services(req, UnlockUser(userName='u'))).is_success
    redis.get = AsyncMock(return_value=None)
    with expect_service_error('未锁定'):
        await LoginLogService.unlock_user_services(req, UnlockUser(userName='u'))

    with patch('module_admin.service.log_service.ExcelUtil.export_list2excel', return_value=b'lg'):
        assert (
            await LoginLogService.export_login_log_list_services([{'status': '0'}, {'status': '1'}]) == b'lg'
        )


# ---------------------------------------------------------------------------
# log queue / aggregator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_queue_service() -> None:
    assert len(LogQueueService._build_event_id('', 'login', 'src')) == 32
    eid = LogQueueService._build_event_id('req-1', 'login', 'src')
    assert eid == LogQueueService._build_event_id('req-1', 'login', 'src')

    redis = AsyncMock()
    redis.xadd = AsyncMock()
    with (
        patch('module_admin.service.log_service.TraceCtx.get_request_id', return_value='r1'),
        patch('module_admin.service.log_service.TraceCtx.get_trace_id', return_value='t1'),
        patch('module_admin.service.log_service.TraceCtx.get_span_id', return_value='s1'),
    ):
        await LogQueueService._xadd_event(redis, 'login', {'a': 1}, 'src')
        redis.xadd.assert_awaited()

    req = _request_with_redis(redis)
    with patch.object(LogQueueService, '_xadd_event', new=AsyncMock()) as xadd:
        await LogQueueService.enqueue_login_log(req, LogininforModel(userName='u'), 'web')
        await LogQueueService.enqueue_operation_log(req, OperLogModel(title='t'), 'web')
        assert xadd.await_count == 2


@pytest.mark.asyncio
async def test_log_aggregator_helpers_and_process() -> None:
    redis = AsyncMock()
    redis.xgroup_create = AsyncMock()
    await LogAggregatorService._ensure_group(redis)

    redis.xgroup_create = AsyncMock(side_effect=Exception('BUSYGROUP Consumer Group name already exists'))
    await LogAggregatorService._ensure_group(redis)

    redis.xgroup_create = AsyncMock(side_effect=Exception('OTHER'))
    with pytest.raises(Exception, match='OTHER'):
        await LogAggregatorService._ensure_group(redis)

    assert await LogAggregatorService._acquire_dedup(redis, '') is False
    redis.set = AsyncMock(return_value=True)
    assert await LogAggregatorService._acquire_dedup(redis, 'eid') is True

    await LogAggregatorService._release_dedup(redis, '')
    redis.delete = AsyncMock()
    await LogAggregatorService._release_dedup(redis, 'eid')
    redis.delete.assert_awaited()

    with patch('module_admin.service.log_service.LogConfig') as cfg:
        cfg.log_stream_claim_idle_ms = 0
        await LogAggregatorService._claim_pending(redis, 'c1')

    with patch('module_admin.service.log_service.LogConfig') as cfg:
        cfg.log_stream_key = 'stream'
        cfg.log_stream_group = 'g'
        cfg.log_stream_claim_idle_ms = 1000
        cfg.log_stream_claim_batch_size = 10
        redis.xautoclaim = AsyncMock(return_value=None)
        await LogAggregatorService._claim_pending(redis, 'c1')

        redis.xautoclaim = AsyncMock(return_value=('0-0', []))
        await LogAggregatorService._claim_pending(redis, 'c1')

        messages = [('1-0', {'event_type': 'login', 'event_id': 'e1', 'payload': '{}'})]
        redis.xautoclaim = AsyncMock(side_effect=[('1-0', messages), ('1-0', [])])
        with patch.object(LogAggregatorService, '_process_messages', new=AsyncMock()) as proc:
            await LogAggregatorService._claim_pending(redis, 'c1')
            proc.assert_awaited()


@pytest.mark.asyncio
async def test_log_aggregator_process_messages() -> None:
    redis = AsyncMock()
    redis.xack = AsyncMock()
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)

    with patch('module_admin.service.log_service.AsyncSessionLocal', return_value=cm):
        await LogAggregatorService._process_messages(redis, 'stream', [])

        with (
            patch.object(LogAggregatorService, '_acquire_dedup', new=AsyncMock(return_value=True)),
            patch.object(LoginLogDao, 'add_login_log_dao', new=AsyncMock()),
            patch.object(OperationLogDao, 'add_operation_log_dao', new=AsyncMock()),
        ):
            await LogAggregatorService._process_messages(
                redis,
                'stream',
                [
                    ('1-0', {'event_type': 'other', 'event_id': 'e0', 'payload': '{}'}),
                    ('1-1', {'event_type': 'login', 'event_id': 'e1', 'payload': json.dumps({'userName': 'u'})}),
                    (
                        '1-2',
                        {'event_type': 'operation', 'event_id': 'e2', 'payload': json.dumps({'title': 't'})},
                    ),
                ],
            )
            redis.xack.assert_awaited()

        with patch.object(LogAggregatorService, '_acquire_dedup', new=AsyncMock(return_value=False)):
            await LogAggregatorService._process_messages(
                redis,
                'stream',
                [('2-0', {'event_type': 'login', 'event_id': 'dup', 'payload': '{}'})],
            )

        with (
            patch.object(LogAggregatorService, '_acquire_dedup', new=AsyncMock(return_value=True)),
            patch.object(LoginLogDao, 'add_login_log_dao', new=AsyncMock(side_effect=RuntimeError('db'))),
            patch.object(LogAggregatorService, '_release_dedup', new=AsyncMock()) as release,
        ):
            with pytest.raises(RuntimeError):
                await LogAggregatorService._process_messages(
                    redis,
                    'stream',
                    [('3-0', {'event_type': 'login', 'event_id': 'e3', 'payload': '{}'})],
                )
            release.assert_awaited()


@pytest.mark.asyncio
async def test_log_aggregator_consume_stream_loop() -> None:
    redis = AsyncMock()
    call_count = {'n': 0}

    async def fake_read(**_kwargs):
        call_count['n'] += 1
        if call_count['n'] == 1:
            return []
        if call_count['n'] == 2:
            return [('stream', [('1-0', {'event_type': 'login', 'event_id': 'e', 'payload': '{}'})])]
        raise asyncio.CancelledError()

    with (
        patch.object(LogAggregatorService, '_ensure_group', new=AsyncMock()),
        patch.object(LogAggregatorService, '_claim_pending', new=AsyncMock()),
        patch.object(LogAggregatorService, '_process_messages', new=AsyncMock()),
        patch('module_admin.service.log_service.LogConfig') as cfg,
    ):
        cfg.log_stream_consumer_prefix = 'c'
        cfg.log_stream_claim_interval_ms = 0
        cfg.log_stream_key = 'stream'
        cfg.log_stream_group = 'g'
        cfg.log_stream_batch_size = 10
        cfg.log_stream_block_ms = 1
        redis.xreadgroup = AsyncMock(side_effect=fake_read)
        with pytest.raises(asyncio.CancelledError):
            await LogAggregatorService.consume_stream(redis)

    # exception path then cancel
    n = {'i': 0}

    async def boom_then_cancel(**_k):
        n['i'] += 1
        if n['i'] == 1:
            raise RuntimeError('boom')
        raise asyncio.CancelledError()

    with (
        patch.object(LogAggregatorService, '_ensure_group', new=AsyncMock()),
        patch.object(LogAggregatorService, '_claim_pending', new=AsyncMock()),
        patch('module_admin.service.log_service.LogConfig') as cfg,
        patch('module_admin.service.log_service.asyncio.sleep', new=AsyncMock()),
    ):
        cfg.log_stream_consumer_prefix = 'c'
        cfg.log_stream_claim_interval_ms = 999999
        cfg.log_stream_key = 'stream'
        cfg.log_stream_group = 'g'
        cfg.log_stream_batch_size = 10
        cfg.log_stream_block_ms = 1
        redis.xreadgroup = AsyncMock(side_effect=boom_then_cancel)
        with pytest.raises(asyncio.CancelledError):
            await LogAggregatorService.consume_stream(redis)


# ---------------------------------------------------------------------------
# log dao
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_dao_lists_and_crud() -> None:
    db = _db()
    with patch('module_admin.dao.log_dao.PageUtil.paginate', new=AsyncMock(return_value=[])):
        await OperationLogDao.get_operation_log_list(
            db,
            OperLogPageQueryModel(
                title='t',
                operName='u',
                businessType='1',
                status='0',
                beginTime='2024-01-01',
                endTime='2024-01-02',
                isAsc='ascending',
                orderByColumn='operTime',
            ),
            True,
        )
        await OperationLogDao.get_operation_log_list(
            db,
            OperLogPageQueryModel(isAsc='descending', orderByColumn='operTime'),
            False,
        )
        await OperationLogDao.get_operation_log_list(db, OperLogPageQueryModel(), False)

        await LoginLogDao.get_login_log_list(
            db,
            LoginLogPageQueryModel(
                ipaddr='1',
                userName='u',
                status='0',
                beginTime='2024-01-01',
                endTime='2024-01-02',
                isAsc='ascending',
                orderByColumn='loginTime',
            ),
            True,
        )
        await LoginLogDao.get_login_log_list(
            db,
            LoginLogPageQueryModel(isAsc='descending', orderByColumn='loginTime'),
            False,
        )
        await LoginLogDao.get_login_log_list(db, LoginLogPageQueryModel(), False)

    db.add = MagicMock()
    db.flush = AsyncMock()
    await OperationLogDao.add_operation_log_dao(db, OperLogModel(title='t'))
    await LoginLogDao.add_login_log_dao(db, LogininforModel(userName='u'))
    db.execute = AsyncMock()
    await OperationLogDao.delete_operation_log_dao(db, OperLogModel(operId=1))
    await OperationLogDao.clear_operation_log_dao(db)
    await LoginLogDao.delete_login_log_dao(db, LogininforModel(infoId=1))
    await LoginLogDao.clear_login_log_dao(db)
