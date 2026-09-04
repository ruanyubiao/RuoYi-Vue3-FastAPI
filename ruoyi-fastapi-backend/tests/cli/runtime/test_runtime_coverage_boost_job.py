"""Raise job runtime coverage toward 99%."""

from __future__ import annotations

from typing import Any

import pytest

from cli.exit_codes import DATABASE_ERROR
from cli.runtime.job import JobRuntimeService
from cli.runtime.job.gateway import JobInfrastructureGateway
from cli.runtime.job.support import JobDomainSupport, JobSchedulerSupport

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _runtime_boost_helpers import (
    FakePageModel,
    FakeRedis,
    FakeRedisUtil,
    FakeSessionFactory,
    make_dump_model,
    patch_gateway,
)


class FakeJobVo:
    class JobPageQueryModel:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class JobLogPageQueryModel:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class JobModel:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class EditJobModel:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs


# ---------------------------------------------------------------------------
# support
# ---------------------------------------------------------------------------


def test_job_support_metadata_filters_and_payload() -> None:
    gateway = JobInfrastructureGateway()
    support = JobDomainSupport(gateway)

    try:
        support.build_job_operation_metadata('noop')
    except ValueError as exc:
        assert '不支持的任务操作' in str(exc)
    else:
        raise AssertionError('expected ValueError')

    filters = support.build_filters(begin_date='2026-01-01', end_date='2026-01-02')
    assert filters['beginDate'] == '2026-01-01'
    assert filters['endDate'] == '2026-01-02'

    assert support.serialize_job_items([{'jobId': 1}]) == [{'jobId': 1}]

    patch_gateway(gateway, get_page_model=lambda: FakePageModel)
    page = FakePageModel([{'jobId': 1}])
    assert support.build_list_payload(page, filters={}, paged=True)['page']['total'] == 1
    assert support.build_list_payload([{'jobId': 2}], filters={}, paged=False)['count'] == 1


@pytest.mark.asyncio
async def test_job_scheduler_close_swallows_errors() -> None:
    gateway = JobInfrastructureGateway()
    support = JobSchedulerSupport(gateway)

    class BoomScheduler:
        @staticmethod
        async def close_system_scheduler() -> None:
            raise RuntimeError('close boom')

    patch_gateway(gateway, get_scheduler_util=lambda: BoomScheduler())
    await support.close_scheduler_context(None)

    class BoomRedis(FakeRedis):
        async def close(self) -> None:
            raise RuntimeError('redis close')

    await support.close_scheduler_context(BoomRedis())


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_job_list_and_detail_paths() -> None:
    gateway = JobInfrastructureGateway()
    service = JobRuntimeService(infrastructure_gateway=gateway)

    class FakeJobService:
        @staticmethod
        async def get_job_list_services(session: Any, query: Any, is_page: bool = False) -> list[Any]:
            del session, query, is_page
            return [{'jobId': 1, 'jobName': 'demo'}]

        @staticmethod
        async def job_detail_services(session: Any, job_id: int) -> Any:
            del session
            return make_dump_model({'jobId': job_id, 'jobName': 'demo'})

    patch_gateway(
        gateway,
        get_async_session_local=lambda: FakeSessionFactory(),
        get_job_vo_module=lambda: FakeJobVo,
        get_job_service=lambda: FakeJobService(),
        get_page_model=lambda: FakePageModel,
    )

    listed = await service.list_jobs(job_name='demo')
    assert listed['ok'] is True
    assert listed['count'] == 1

    detail = await service.get_job_detail(7)
    assert detail['ok'] is True
    assert detail['job']['jobId'] == 7

    class BoomList:
        @staticmethod
        async def get_job_list_services(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError('list fail')

        @staticmethod
        async def job_detail_services(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError('detail fail')

    patch_gateway(gateway, get_job_service=lambda: BoomList())
    assert (await service.list_jobs())['exit_code'] == DATABASE_ERROR
    assert (await service.get_job_detail(1))['exit_code'] == DATABASE_ERROR


@pytest.mark.asyncio
async def test_job_list_logs_success_and_error() -> None:
    gateway = JobInfrastructureGateway()
    service = JobRuntimeService(infrastructure_gateway=gateway)

    class FakeJobLogService:
        @staticmethod
        async def get_job_log_list_services(session: Any, query: Any, is_page: bool = False) -> list[Any]:
            del session, is_page
            assert query.kwargs['beginTime'] == '2026-01-01'
            return [{'jobLogId': 1}]

    patch_gateway(
        gateway,
        get_async_session_local=lambda: FakeSessionFactory(),
        get_job_vo_module=lambda: FakeJobVo,
        get_job_log_service=lambda: FakeJobLogService(),
        get_page_model=lambda: FakePageModel,
    )
    payload = await service.list_job_logs(begin_date='2026-01-01', end_date='2026-01-31')
    assert payload['ok'] is True
    assert payload['filters']['beginDate'] == '2026-01-01'

    class Boom:
        @staticmethod
        async def get_job_log_list_services(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError('log fail')

    patch_gateway(gateway, get_job_log_service=lambda: Boom())
    assert (await service.list_job_logs())['exit_code'] == DATABASE_ERROR


@pytest.mark.asyncio
async def test_job_scheduler_context_operations() -> None:
    gateway = JobInfrastructureGateway()
    service = JobRuntimeService(infrastructure_gateway=gateway)
    redis = FakeRedis()
    redis_util = FakeRedisUtil(redis)
    close_events: list[str] = []

    class SimpleSuccess:
        def __init__(self, is_success: bool, message: str) -> None:
            self.is_success = is_success
            self.message = message

    class FakeScheduler:
        @staticmethod
        async def init_system_scheduler(client: FakeRedis) -> None:
            assert client is redis

        @staticmethod
        async def close_system_scheduler() -> None:
            close_events.append('scheduler')

    class FakeJobService:
        @staticmethod
        async def execute_job_once_services(session: Any, model: Any) -> Any:
            del session
            assert model.kwargs['jobId'] == 3
            return SimpleSuccess(True, 'ran')

        @staticmethod
        async def edit_job_services(session: Any, model: Any) -> Any:
            del session
            return SimpleSuccess(True, f"status:{model.kwargs['status']}")

    patch_gateway(
        gateway,
        get_async_session_local=lambda: FakeSessionFactory(),
        get_redis_util=lambda: redis_util,
        get_scheduler_util=lambda: FakeScheduler(),
        get_job_vo_module=lambda: FakeJobVo,
        get_job_service=lambda: FakeJobService(),
    )

    once = await service.run_job_once(3)
    assert once['ok'] is True
    assert once['operation'] == 'run-once'

    paused = await service.pause_job(3)
    assert paused['ok'] is True
    assert paused['targetStatus'] == '1'

    resumed = await service.resume_job(3)
    assert resumed['ok'] is True
    assert resumed['targetStatus'] == '0'

    object.__setattr__(
        service.domain_support,
        'build_job_operation_metadata',
        lambda operation: {'operationLabel': operation, 'successMessage': 'x'},
    )
    bad = await service.run_with_scheduler_context('noop', 3)
    assert bad['ok'] is False
    assert bad['exit_code'] == 22
    assert 'scheduler' in close_events
    assert redis.closed is True


def test_job_gateway_lazy_imports() -> None:
    gateway = JobInfrastructureGateway()
    assert gateway.get_async_session_local() is not None
    assert gateway.get_page_model() is not None
    assert gateway.get_redis_util() is not None
    assert gateway.get_scheduler_util() is not None
    assert gateway.get_job_vo_module() is not None
    assert gateway.get_job_service() is not None
    assert gateway.get_job_log_service() is not None
