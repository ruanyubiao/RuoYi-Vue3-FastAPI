"""Raise coverage of config/get_scheduler.py toward 99% (heavy mocks)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.get_scheduler import MyCronTrigger, SchedulerUtil, scheduler
from module_admin.entity.vo.job_vo import JobModel
from module_task import scheduler_test


def _job(**kw) -> JobModel:
    data = dict(
        job_id=1,
        job_name='demo',
        job_group='default',
        job_executor='default',
        invoke_target='module_task.scheduler_test.job',
        job_args='a,b',
        job_kwargs='{"x": 1}',
        cron_expression='0 0 12 * * ?',
        misfire_policy='1',
        concurrent='1',
        status='0',
        update_time=datetime(2026, 1, 1, 12, 0, 0),
    )
    data.update(kw)
    # JobModel aliases are camelCase without populate_by_name
    return JobModel.model_construct(**data)


def _reset_scheduler_util() -> None:
    SchedulerUtil._is_leader = False
    SchedulerUtil._redis = None
    SchedulerUtil._job_update_time_cache = {}
    SchedulerUtil._sync_listener_task = None
    SchedulerUtil._lock_lost_task = None
    SchedulerUtil._sync_task = None
    SchedulerUtil._sync_pending = False
    SchedulerUtil._last_sync_at = None
    SchedulerUtil._reacquire_task = None
    SchedulerUtil._sync_async_engine = None
    SchedulerUtil._sync_async_sessionmaker = None
    SchedulerUtil._disposed_sync_engines = False
    SchedulerUtil._jobstore_engine = None
    SchedulerUtil._listener_engine = None
    SchedulerUtil._session_local = None
    SchedulerUtil._scheduler_configured = False
    SchedulerUtil._sync_debounce_seconds = 0.01
    SchedulerUtil._sync_min_interval_seconds = 0.01
    SchedulerUtil._reacquire_interval_seconds = 0.01


@pytest.fixture(autouse=True)
def _clean_scheduler_state():
    _reset_scheduler_util()
    yield
    _reset_scheduler_util()
    if getattr(scheduler, 'running', False):
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# MyCronTrigger
# ---------------------------------------------------------------------------


def test_mycron_trigger_variants() -> None:
    with pytest.raises(ValueError):
        MyCronTrigger.from_crontab('0 0 12')

    assert MyCronTrigger.from_crontab('0 30 8 * * ?') is not None
    assert MyCronTrigger.from_crontab('0 0 12 L * ?') is not None

    def _noop_init(self, **kwargs):
        self._cron_kwargs = kwargs

    with patch.object(MyCronTrigger, '__init__', _noop_init):
        t = MyCronTrigger.from_crontab('0 0 12 * * 5L')
        assert t._cron_kwargs.get('day') == 'last 5'
        t = MyCronTrigger.from_crontab('0 0 12 ? * 2#1')
        assert t._cron_kwargs.get('week') == 1
        t = MyCronTrigger.from_crontab('0 0 12 * * 1 2026')
        assert t._cron_kwargs.get('year') == '2026'
        t = MyCronTrigger.from_crontab('0 0 12 15W * ?')
        assert 'day' in t._cron_kwargs

    with patch('config.get_scheduler.datetime') as dt:
        real = datetime
        dt.now.return_value = real(2026, 9, 5)  # Saturday
        dt.side_effect = lambda *a, **k: real(*a, **k)
        day = MyCronTrigger._MyCronTrigger__find_recent_workday(5)
        assert isinstance(day, int)
        dt.now.return_value = real(2026, 9, 4)  # Friday
        assert MyCronTrigger._MyCronTrigger__find_recent_workday(4) == 4


# ---------------------------------------------------------------------------
# engines / configure / sync helpers
# ---------------------------------------------------------------------------


def test_lazy_engines_and_configure() -> None:
    eng = MagicMock()
    with (
        patch('config.get_scheduler.create_sync_db_engine', return_value=eng) as cse,
        patch('config.get_scheduler.create_sync_session_local', return_value=MagicMock(return_value=MagicMock())),
        patch('config.get_scheduler.SQLAlchemyJobStore'),
        patch('config.get_scheduler.RedisJobStore'),
        patch('config.get_scheduler.MemoryJobStore'),
        patch('config.get_scheduler.AsyncIOExecutor'),
        patch('config.get_scheduler.ProcessPoolExecutor'),
        patch.object(scheduler, 'configure') as conf,
    ):
        assert SchedulerUtil._get_jobstore_engine() is eng
        assert SchedulerUtil._get_jobstore_engine() is eng
        assert SchedulerUtil._get_listener_engine() is eng
        assert SchedulerUtil._get_session_local() is not None
        SchedulerUtil._configure_scheduler()
        SchedulerUtil._configure_scheduler()  # early return
        assert conf.called
        assert cse.call_count >= 1


def test_should_enable_scheduler_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('config.get_scheduler.AppConfig.app_reload', False)
    monkeypatch.setattr('config.get_scheduler.AppConfig.app_workers', 2)
    assert SchedulerUtil._should_enable_scheduler_sync() is True
    monkeypatch.setattr('config.get_scheduler.AppConfig.app_workers', 1)
    assert SchedulerUtil._should_enable_scheduler_sync() is False


def test_job_cache_and_skip_and_import() -> None:
    SchedulerUtil._refresh_job_update_cache('1', None)
    ts = datetime.now()
    SchedulerUtil._refresh_job_update_cache('1', ts)
    assert SchedulerUtil._should_skip_job_update('1', ts) is True
    assert SchedulerUtil._should_skip_job_update('1', None) is False
    assert SchedulerUtil._should_skip_job_update('1', ts + timedelta(seconds=1)) is False
    SchedulerUtil._refresh_job_update_cache('1', None)
    assert '1' not in SchedulerUtil._job_update_time_cache

    fn = SchedulerUtil._import_function('module_task.scheduler_test.job')
    assert callable(fn)


def test_prepare_and_add_and_is_in_sync() -> None:
    job = _job(misfire_policy='3', concurrent='0', job_executor='processpool')
    with patch.object(MyCronTrigger, '__init__', lambda self, **kw: None):
        params = SchedulerUtil._prepare_scheduler_job_add(job)
    assert params['max_instances'] == 3
    assert params['misfire_grace_time'] == 1000000000000

    async_job = _job(invoke_target='module_task.scheduler_test.async_job', job_kwargs=None, job_args=None)
    with patch.object(MyCronTrigger, '__init__', lambda self, **kw: None):
        params2 = SchedulerUtil._prepare_scheduler_job_add(async_job)
    assert params2['executor'] == 'default'
    assert params2['args'] is None

    sched_job = MagicMock()
    sched_job._jobstore_alias = 'default'
    sched_job.__getstate__ = MagicMock(
        return_value={
            'name': job.job_name,
            'executor': 'default',
            'misfire_grace_time': 1000000000000,
            'coalesce': False,
            'max_instances': 3,
            'trigger': 'cron',
            'args': ('a', 'b'),
            'kwargs': {'x': 1},
            'func': str(SchedulerUtil._import_function(job.invoke_target)),
        }
    )
    with patch.object(MyCronTrigger, '__init__', lambda self, **kw: None), patch.object(
        MyCronTrigger, '__str__', return_value='cron'
    ):
        SchedulerUtil._is_job_config_in_sync(sched_job, job)

    with patch.object(MyCronTrigger, '__init__', lambda self, **kw: None), patch.object(
        scheduler, 'get_job', return_value=MagicMock()
    ), patch.object(scheduler, 'remove_job'), patch.object(scheduler, 'add_job'):
        SchedulerUtil._add_job_to_scheduler(job)
    with patch.object(MyCronTrigger, '__init__', lambda self, **kw: None), patch.object(
        scheduler, 'get_job', return_value=None
    ), patch.object(scheduler, 'add_job', side_effect=RuntimeError('x')):
        SchedulerUtil._add_job_to_scheduler(job)

    SchedulerUtil._sync_update_job('1', None, None, None)
    SchedulerUtil._is_leader = True
    with patch.object(SchedulerUtil, '_should_skip_job_update', return_value=True):
        SchedulerUtil._sync_update_job('1', job, sched_job, job.update_time)
    with (
        patch.object(SchedulerUtil, '_should_skip_job_update', return_value=False),
        patch.object(SchedulerUtil, '_is_job_config_in_sync', return_value=False),
        patch.object(scheduler, 'remove_job'),
        patch.object(SchedulerUtil, '_add_job_to_scheduler'),
    ):
        SchedulerUtil._sync_update_job('1', job, sched_job, job.update_time)


@pytest.mark.asyncio
async def test_sync_jobs_from_database_paths() -> None:
    SchedulerUtil._is_leader = False
    await SchedulerUtil._sync_jobs_from_database()

    SchedulerUtil._is_leader = True
    enabled = _job(job_id=1, status='0', update_time=datetime(2026, 1, 2))
    disabled = _job(job_id=2, status='1')
    stale = MagicMock(id='9')
    stale.id = '9'
    keep = MagicMock(id='1')
    keep.id = '1'
    internal = MagicMock(id='_internal')
    internal.id = '_internal'

    session = MagicMock()

    class ACM:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *a):
            return False

    with (
        patch.object(SchedulerUtil, '_get_sync_async_session', return_value=ACM()),
        patch(
            'config.get_scheduler.JobDao.get_all_job_list_for_scheduler',
            new=AsyncMock(return_value=[enabled, disabled, _job(job_id=3, status='0')]),
        ),
        patch.object(scheduler, 'get_jobs', return_value=[stale, keep, internal]),
        patch.object(scheduler, 'remove_job') as rm,
        patch.object(SchedulerUtil, '_add_job_to_scheduler') as add,
        patch.object(SchedulerUtil, '_sync_update_job') as upd,
    ):
        await SchedulerUtil._sync_jobs_from_database()
        assert rm.called and add.called and upd.called

    with (
        patch.object(SchedulerUtil, '_get_sync_async_session', side_effect=RuntimeError('db')),
    ):
        await SchedulerUtil._sync_jobs_from_database()


@pytest.mark.asyncio
async def test_request_sync_and_loops() -> None:
    SchedulerUtil._is_leader = True
    SchedulerUtil._sync_pending = False
    with patch.object(SchedulerUtil, '_ensure_sync_task') as ens:
        await SchedulerUtil.request_scheduler_sync()
        assert SchedulerUtil._sync_pending is True
        ens.assert_called()

    SchedulerUtil._is_leader = False
    redis = AsyncMock()
    SchedulerUtil._redis = redis
    await SchedulerUtil.request_scheduler_sync()
    redis.publish.assert_awaited()

    # ensure sync task early return
    done_task = asyncio.get_event_loop().create_future()
    # running unfinished task mock
    fake = MagicMock()
    fake.done.return_value = False
    SchedulerUtil._sync_task = fake
    SchedulerUtil._ensure_sync_task()

    SchedulerUtil._sync_task = None
    SchedulerUtil._sync_pending = True
    SchedulerUtil._is_leader = True
    with patch.object(SchedulerUtil, '_sync_with_throttle', new=AsyncMock()) as thr:
        task = asyncio.create_task(SchedulerUtil._run_sync_loop())
        await asyncio.sleep(0.05)
        await task
        thr.assert_awaited()

    SchedulerUtil._sync_pending = True
    task = asyncio.create_task(SchedulerUtil._run_sync_loop())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    SchedulerUtil._is_leader = False
    await SchedulerUtil._sync_with_throttle()
    SchedulerUtil._is_leader = True
    SchedulerUtil._last_sync_at = datetime.now()
    with patch.object(SchedulerUtil, '_sync_jobs_from_database', new=AsyncMock()) as sync:
        await SchedulerUtil._sync_with_throttle()
        sync.assert_awaited()


@pytest.mark.asyncio
async def test_listen_sync_channel() -> None:
    class PubSub:
        def __init__(self):
            self._msgs = [
                {'type': 'subscribe'},
                {'type': 'message', 'data': 'w'},
            ]
            self._i = 0

        async def subscribe(self, *a):
            return None

        async def unsubscribe(self, *a):
            return None

        async def close(self):
            return None

        async def listen(self):
            for m in self._msgs:
                yield m
            raise asyncio.CancelledError()

    redis = MagicMock()
    redis.pubsub.return_value = PubSub()
    SchedulerUtil._is_leader = True
    with patch.object(SchedulerUtil, 'request_scheduler_sync', new=AsyncMock()) as req:
        with pytest.raises(asyncio.CancelledError):
            await SchedulerUtil._listen_sync_channel(redis)
        req.assert_awaited()

    class BoomPub:
        async def subscribe(self, *a):
            raise RuntimeError('x')

        async def close(self):
            raise RuntimeError('close')

        async def listen(self):
            if False:
                yield {}
            raise RuntimeError('x')

    class BoomThenCancel(BoomPub):
        async def subscribe(self, *a):
            raise RuntimeError('x')

        async def close(self):
            return None

    redis.pubsub.return_value = BoomThenCancel()
    SchedulerUtil._is_leader = False
    with patch('config.get_scheduler.asyncio.sleep', new=AsyncMock()):
        task = asyncio.create_task(SchedulerUtil._listen_sync_channel(redis))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_dispose_and_reacquire() -> None:
    eng = MagicMock()
    eng.dispose = MagicMock()
    async_eng = MagicMock()
    async_eng.dispose = AsyncMock()
    SchedulerUtil._sync_async_engine = async_eng
    SchedulerUtil._sync_async_sessionmaker = MagicMock()
    await SchedulerUtil._dispose_sync_async_engine()
    assert SchedulerUtil._sync_async_engine is None

    SchedulerUtil._jobstore_engine = eng
    SchedulerUtil._listener_engine = eng
    SchedulerUtil._disposed_sync_engines = False
    SchedulerUtil._dispose_sync_engines()
    SchedulerUtil._dispose_sync_engines()  # early
    assert SchedulerUtil._disposed_sync_engines is True

    SchedulerUtil._redis = None
    SchedulerUtil._ensure_reacquire_task()
    SchedulerUtil._redis = AsyncMock()
    fake = MagicMock()
    fake.done.return_value = False
    SchedulerUtil._reacquire_task = fake
    SchedulerUtil._ensure_reacquire_task()

    SchedulerUtil._reacquire_task = None
    SchedulerUtil._is_leader = False
    SchedulerUtil._redis = None
    task = asyncio.create_task(SchedulerUtil._run_reacquire_loop())
    await asyncio.sleep(0.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    SchedulerUtil._is_leader = False
    SchedulerUtil._redis = AsyncMock()
    with (
        patch('config.get_scheduler.StartupUtil.acquire_startup_log_gate', new=AsyncMock(side_effect=[False, True])),
        patch.object(SchedulerUtil, '_start_scheduler_as_leader', new=AsyncMock()) as start,
    ):
        await SchedulerUtil._run_reacquire_loop()
        start.assert_awaited()


@pytest.mark.asyncio
async def test_init_close_lock_lost() -> None:
    redis = AsyncMock()
    job = _job()

    class ACM:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *a):
            return False

    with (
        patch('config.get_scheduler.StartupUtil.acquire_startup_log_gate', new=AsyncMock(return_value=False)),
    ):
        await SchedulerUtil.init_system_scheduler(redis)
        assert SchedulerUtil._is_leader is False

    with (
        patch('config.get_scheduler.StartupUtil.acquire_startup_log_gate', new=AsyncMock(return_value=True)),
        patch.object(SchedulerUtil, '_configure_scheduler'),
        patch.object(scheduler, 'start'),
        patch.object(scheduler, 'add_listener'),
        patch.object(scheduler, 'add_job'),
        patch.object(SchedulerUtil, '_get_sync_async_session', return_value=ACM()),
        patch('config.get_scheduler.JobDao.get_job_list_for_scheduler', new=AsyncMock(return_value=[job])),
        patch.object(SchedulerUtil, '_add_job_to_scheduler'),
        patch.object(SchedulerUtil, '_should_enable_scheduler_sync', return_value=True),
        patch.object(SchedulerUtil, '_listen_sync_channel', new=AsyncMock()),
    ):
        await SchedulerUtil.init_system_scheduler(redis)
        assert SchedulerUtil._is_leader is True

    SchedulerUtil._is_leader = False
    SchedulerUtil.on_lock_lost()  # early return when not leader
    SchedulerUtil._is_leader = True

    async def fake_handle():
        return None

    with patch.object(SchedulerUtil, '_handle_lock_lost', new=fake_handle):
        SchedulerUtil._lock_lost_task = None
        SchedulerUtil.on_lock_lost()
        assert SchedulerUtil._is_leader is False
        await asyncio.sleep(0.01)

    async def cancellable():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise

    SchedulerUtil._sync_listener_task = asyncio.create_task(cancellable())
    SchedulerUtil._sync_task = asyncio.create_task(cancellable())
    fake_sch = MagicMock()
    fake_sch.running = True
    fake_sch.shutdown = MagicMock()
    with (
        patch('config.get_scheduler.scheduler', fake_sch),
        patch.object(SchedulerUtil, '_dispose_sync_async_engine', new=AsyncMock()),
        patch.object(SchedulerUtil, '_dispose_sync_engines'),
        patch.object(SchedulerUtil, '_ensure_reacquire_task'),
    ):
        await SchedulerUtil._handle_lock_lost()
        fake_sch.shutdown.assert_called()


@pytest.mark.asyncio
async def test_close_system_scheduler() -> None:
    async def sleeper():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise

    SchedulerUtil._sync_listener_task = asyncio.create_task(sleeper())
    SchedulerUtil._sync_task = asyncio.create_task(sleeper())
    SchedulerUtil._reacquire_task = asyncio.create_task(sleeper())
    SchedulerUtil._lock_lost_task = asyncio.create_task(sleeper())
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=SchedulerUtil._worker_id)
    redis.delete = AsyncMock()
    SchedulerUtil._redis = redis
    fake_sch = MagicMock()
    fake_sch.running = False
    fake_sch.shutdown = MagicMock()
    with (
        patch.object(SchedulerUtil, '_dispose_sync_async_engine', new=AsyncMock()),
        patch.object(SchedulerUtil, '_dispose_sync_engines'),
        patch('config.get_scheduler.scheduler', fake_sch),
    ):
        await SchedulerUtil.close_system_scheduler()
        redis.delete.assert_awaited()


@pytest.mark.asyncio
async def test_close_system_scheduler_running_true() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value='other')
    SchedulerUtil._redis = redis
    fake_sch = MagicMock()
    fake_sch.running = True
    fake_sch.shutdown = MagicMock()
    with (
        patch.object(SchedulerUtil, '_dispose_sync_async_engine', new=AsyncMock()),
        patch.object(SchedulerUtil, '_dispose_sync_engines'),
        patch('config.get_scheduler.scheduler', fake_sch),
    ):
        await SchedulerUtil.close_system_scheduler()
        fake_sch.shutdown.assert_called()


def test_public_job_api() -> None:
    job = _job()
    SchedulerUtil._is_leader = False
    SchedulerUtil.add_scheduler_job(job)
    SchedulerUtil.remove_scheduler_job(1)

    SchedulerUtil._is_leader = True
    with patch.object(MyCronTrigger, '__init__', lambda self, **kw: None), patch.object(scheduler, 'add_job') as add:
        SchedulerUtil.add_scheduler_job(job)
        add.assert_called()
    with patch.object(SchedulerUtil, 'get_scheduler_job', return_value=MagicMock()), patch.object(scheduler, 'remove_job') as rm:
        SchedulerUtil.remove_scheduler_job(1)
        rm.assert_called()
    with patch.object(SchedulerUtil, 'get_scheduler_job', return_value=None), patch.object(scheduler, 'remove_job') as rm2:
        SchedulerUtil.remove_scheduler_job(2)
        rm2.assert_not_called()

    with patch.object(scheduler, 'get_job', return_value='J'):
        assert SchedulerUtil.get_scheduler_job(1) == 'J'


def test_execute_scheduler_job_once_paths() -> None:
    job = _job()
    SchedulerUtil._is_leader = False
    with patch.object(SchedulerUtil, '_record_job_execution_log') as rec:
        SchedulerUtil.execute_scheduler_job_once(job)
        rec.assert_called()

    boom_fn = MagicMock(side_effect=RuntimeError('x'))
    with (
        patch.object(SchedulerUtil, '_import_function', return_value=boom_fn),
        patch.object(SchedulerUtil, '_record_job_execution_log') as rec2,
    ):
        SchedulerUtil.execute_scheduler_job_once(_job())
        rec2.assert_called()

    async def _ajob(*a, **k):
        return None

    with (
        patch.object(SchedulerUtil, '_import_function', return_value=_ajob),
        patch('asyncio.create_task', side_effect=lambda coro: (coro.close(), MagicMock())[1]),
    ):
        SchedulerUtil.execute_scheduler_job_once(_job(invoke_target='module_task.scheduler_test.async_job'))

    SchedulerUtil._is_leader = True
    with patch.object(MyCronTrigger, '__init__', lambda self, **kw: None), patch.object(scheduler, 'add_job') as add:
        SchedulerUtil.execute_scheduler_job_once(_job(status='0'))
        add.assert_called()
        SchedulerUtil.execute_scheduler_job_once(_job(status='1', misfire_policy='2', concurrent='0'))
        assert add.call_count == 2


@pytest.mark.asyncio
async def test_execute_async_and_record_log() -> None:
    job = _job(invoke_target='module_task.scheduler_test.async_job', cron_expression='0 0 12 * * ?')

    async def ok(*a, **k):
        return None

    async def bad(*a, **k):
        raise RuntimeError('fail')

    with patch.object(SchedulerUtil, '_record_job_execution_log') as rec:
        await SchedulerUtil._execute_async_job_with_log(ok, job, [], {})
        await SchedulerUtil._execute_async_job_with_log(bad, job, [], {})
        assert rec.call_count == 2

    session = MagicMock()
    factory = MagicMock(return_value=session)
    with (
        patch.object(SchedulerUtil, '_get_session_local', return_value=factory),
        patch.object(MyCronTrigger, 'from_crontab', return_value=MagicMock(__str__=lambda self: 'cron')),
        patch('config.get_scheduler.JobLogService.add_job_log_services') as add,
    ):
        SchedulerUtil._record_job_execution_log(job, 'default', '0', '')
        add.assert_called()
        session.close.assert_called()

    with patch.object(SchedulerUtil, '_get_session_local', side_effect=RuntimeError('x')):
        SchedulerUtil._record_job_execution_log(job, 'default', '1', 'e')


def test_scheduler_event_listener() -> None:
    SchedulerUtil.scheduler_event_listener(SimpleNamespace())

    class JobExecutionEvent:
        def __init__(self, job_id, exception=None):
            self.job_id = job_id
            self.exception = exception

    SchedulerUtil.scheduler_event_listener(JobExecutionEvent('_sys'))

    state = {
        'name': 'n',
        'executor': 'default',
        'func': 'f',
        'args': (1, 2),
        'kwargs': {'a': 1},
        'trigger': 'cron',
    }
    qj = SimpleNamespace(_jobstore_alias='default', __getstate__=lambda: state)
    session = MagicMock()
    with (
        patch.object(SchedulerUtil, 'get_scheduler_job', return_value=qj),
        patch.object(SchedulerUtil, '_get_session_local', return_value=MagicMock(return_value=session)),
        patch('config.get_scheduler.JobLogService.add_job_log_services'),
    ):
        SchedulerUtil.scheduler_event_listener(JobExecutionEvent('1', RuntimeError('x')))

    with patch.object(SchedulerUtil, 'get_scheduler_job', side_effect=RuntimeError('x')):
        SchedulerUtil.scheduler_event_listener(JobExecutionEvent('1', RuntimeError('x')))

    with patch.object(SchedulerUtil, 'get_scheduler_job', return_value=None):
        SchedulerUtil.scheduler_event_listener(JobExecutionEvent('2'))


@pytest.mark.asyncio
async def test_get_sync_async_session() -> None:
    eng = MagicMock()
    sm = MagicMock(return_value='session')
    with (
        patch('config.get_scheduler.create_async_db_engine', return_value=eng),
        patch('config.get_scheduler.create_async_session_local', return_value=sm),
    ):
        assert SchedulerUtil._get_sync_async_session() == 'session'
        assert SchedulerUtil._get_sync_async_session() == 'session'


@pytest.mark.asyncio
async def test_scheduler_leftover_branches() -> None:
    # Sunday so first previous_day is still weekend (covers diff += 1)
    with patch('config.get_scheduler.datetime') as dt:
        real = datetime
        dt.now.return_value = real(2026, 9, 6)  # Sunday
        dt.side_effect = lambda *a, **k: real(*a, **k)
        assert MyCronTrigger._MyCronTrigger__find_recent_workday(6) == 4

    SchedulerUtil._is_leader = True

    async def slow():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise

    prior = asyncio.create_task(slow())
    SchedulerUtil._lock_lost_task = prior

    async def noop():
        return None

    with patch.object(SchedulerUtil, '_handle_lock_lost', new=noop):
        SchedulerUtil.on_lock_lost()
        await asyncio.sleep(0.01)
        assert prior.cancelled() or prior.done()

    async def _ajob(*a, **k):
        return None

    job = _job(invoke_target='module_task.scheduler_test.async_job')
    sched_job = MagicMock()
    sched_job._jobstore_alias = 'default'
    sched_job.__getstate__ = MagicMock(
        return_value={
            'name': job.job_name,
            'executor': 'default',
            'misfire_grace_time': None,
            'coalesce': False,
            'max_instances': 1,
            'trigger': 'cron',
            'args': ('a', 'b'),
            'kwargs': {'x': 1},
            'func': str(_ajob),
        }
    )
    with (
        patch.object(SchedulerUtil, '_import_function', return_value=_ajob),
        patch.object(MyCronTrigger, 'from_crontab', return_value=MagicMock(__str__=lambda s: 'cron')),
    ):
        SchedulerUtil._is_job_config_in_sync(sched_job, job)

    SchedulerUtil._sync_task = None
    SchedulerUtil._sync_pending = False
    with patch.object(SchedulerUtil, '_run_sync_loop', new=AsyncMock()):
        SchedulerUtil._ensure_sync_task()
        assert SchedulerUtil._sync_task is not None
        SchedulerUtil._sync_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await SchedulerUtil._sync_task

    SchedulerUtil._reacquire_task = None
    SchedulerUtil._redis = AsyncMock()
    with patch.object(SchedulerUtil, '_run_reacquire_loop', new=AsyncMock()):
        SchedulerUtil._ensure_reacquire_task()
        assert SchedulerUtil._reacquire_task is not None
        SchedulerUtil._reacquire_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await SchedulerUtil._reacquire_task

    class PubSub:
        async def subscribe(self, *a):
            return None

        async def unsubscribe(self, *a):
            return None

        async def close(self):
            return None

        async def listen(self):
            yield {'type': 'message', 'data': 'x'}
            raise asyncio.CancelledError()

    redis = MagicMock()
    redis.pubsub.return_value = PubSub()
    SchedulerUtil._is_leader = False
    with patch.object(SchedulerUtil, 'request_scheduler_sync', new=AsyncMock()) as req:
        with pytest.raises(asyncio.CancelledError):
            await SchedulerUtil._listen_sync_channel(redis)
        req.assert_not_awaited()

    class BoomPub:
        closes = 0

        async def subscribe(self, *a):
            raise RuntimeError('boom')

        async def close(self):
            BoomPub.closes += 1
            # first close (except block) succeeds; second (finally) raises -> 616-617
            if BoomPub.closes >= 2:
                raise RuntimeError('close-fail')
            return None

        async def listen(self):
            if False:
                yield {}

    redis.pubsub.return_value = BoomPub()
    BoomPub.closes = 0

    async def sleep_then_cancel(_t):
        raise asyncio.CancelledError()

    with patch('config.get_scheduler.asyncio.sleep', side_effect=sleep_then_cancel):
        with pytest.raises(asyncio.CancelledError):
            await SchedulerUtil._listen_sync_channel(redis)
