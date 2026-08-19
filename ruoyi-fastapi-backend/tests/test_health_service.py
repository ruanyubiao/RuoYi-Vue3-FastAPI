"""健康检查载荷与总体状态。"""

from __future__ import annotations

import asyncio

import pytest

from module_admin.service.health_service import HealthService


class _FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    async def ping(self) -> bool:
        if self._fail:
            raise ConnectionError('redis down')
        return True


def test_health_ok_when_database_and_redis_up(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok_db() -> dict:
        return {'status': 'ok', 'type': 'mysql', 'latencyMs': 1.0}

    monkeypatch.setattr(HealthService, '_check_database', staticmethod(ok_db))
    monkeypatch.setattr(HealthService, '_collectors', staticmethod(lambda: {'opened': 1, 'alive': 1}))

    payload, status_code = asyncio.run(HealthService.check(_FakeRedis()))

    assert status_code == 200
    assert payload['status'] == 'ok'
    assert payload['redis']['status'] == 'ok'
    assert payload['collectors'] == {'opened': 1, 'alive': 1}
    assert 'version' in payload
    assert 'env' in payload
    assert 'uptimeSeconds' in payload


def test_health_error_when_redis_down(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok_db() -> dict:
        return {'status': 'ok', 'type': 'mysql', 'latencyMs': 1.0}

    monkeypatch.setattr(HealthService, '_check_database', staticmethod(ok_db))
    monkeypatch.setattr(HealthService, '_collectors', staticmethod(lambda: {'opened': 0, 'alive': 0}))

    payload, status_code = asyncio.run(HealthService.check(_FakeRedis(fail=True)))

    assert status_code == 503
    assert payload['status'] == 'error'
    assert payload['redis']['status'] == 'error'
    assert 'error' in payload['redis']


def test_health_error_when_redis_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok_db() -> dict:
        return {'status': 'ok', 'type': 'mysql', 'latencyMs': 1.0}

    monkeypatch.setattr(HealthService, '_check_database', staticmethod(ok_db))
    monkeypatch.setattr(HealthService, '_collectors', staticmethod(lambda: {'opened': 0, 'alive': 0}))

    payload, status_code = asyncio.run(HealthService.check(None))

    assert status_code == 503
    assert payload['status'] == 'error'
    assert payload['redis']['status'] == 'error'


def test_health_error_when_database_down(monkeypatch: pytest.MonkeyPatch) -> None:
    async def bad_db() -> dict:
        return {'status': 'error', 'type': 'mysql', 'latencyMs': 10.0, 'error': 'TimeoutError'}

    monkeypatch.setattr(HealthService, '_check_database', staticmethod(bad_db))
    monkeypatch.setattr(HealthService, '_collectors', staticmethod(lambda: {'opened': 0, 'alive': 0}))

    payload, status_code = asyncio.run(HealthService.check(_FakeRedis()))

    assert status_code == 503
    assert payload['status'] == 'error'
    assert payload['database']['status'] == 'error'
    assert payload['redis']['status'] == 'ok'


def test_collectors_fallback_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object) -> None:
        raise RuntimeError('no manager')

    monkeypatch.setattr(
        'module_payload.collectors.process_manager.CollectorProcessManager.instance',
        boom,
    )
    assert HealthService._collectors() == {'opened': 0, 'alive': 0}


def test_collectors_counts_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeMgr:
        @staticmethod
        def list_opened() -> list:
            return [{'alive': True}, {'alive': False}, {'alive': True}]

    monkeypatch.setattr(
        'module_payload.collectors.process_manager.CollectorProcessManager.instance',
        lambda *_args: FakeMgr(),
    )
    assert HealthService._collectors() == {'opened': 3, 'alive': 2}
