"""Raise ops runtime coverage toward 99%."""

from __future__ import annotations

import socket
from types import SimpleNamespace
from typing import Any

import pytest

from cli.exit_codes import REDIS_ERROR, RUNTIME_ERROR, SCHEDULER_ERROR
from cli.runtime.ops import OperationsRuntimeService
from cli.runtime.ops.gateway import OperationsInfrastructureGateway
from cli.runtime.ops.support import OperationsDependencyInspector, OperationsServerInfoSupport

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _runtime_boost_helpers import FakeRedis, FakeRedisUtil, patch_gateway


def test_ops_dependency_inspector_happy_and_read_version() -> None:
    inspector = OperationsDependencyInspector()
    assert inspector.read_package_version('pytest') is not None
    assert inspector.read_package_version('definitely-missing-pkg-xyz') is None

    specs = inspector.build_dependency_specs(include_dev=True)
    assert any(spec.package_name == 'pytest' for spec in specs)

    payload = inspector.inspect(include_dev=True)
    assert payload['ok'] is True
    assert payload['includeDev'] is True
    assert 'pytest' in payload['packages']

    service = OperationsRuntimeService(dependency_inspector=inspector)
    assert service.get_dependency_versions(include_dev=True)['ok'] is True


def test_ops_resolve_server_ip_success_and_loopback_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = OperationsInfrastructureGateway()
    support = OperationsServerInfoSupport(gateway)

    monkeypatch.setattr(socket, 'gethostbyname', lambda hostname: '10.0.0.8')
    assert support.resolve_server_ip('host') == '10.0.0.8'

    class FakePsutil:
        @staticmethod
        def net_if_addrs() -> dict[str, list[SimpleNamespace]]:
            return {'lo': [SimpleNamespace(family=socket.AF_INET, address='127.0.0.1')]}

    patch_gateway(gateway, get_psutil_module=lambda: FakePsutil())
    monkeypatch.setattr(socket, 'gethostbyname', lambda hostname: (_ for _ in ()).throw(OSError('x')))
    assert support.resolve_server_ip('host') == '127.0.0.1'


def test_ops_build_server_info_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = OperationsInfrastructureGateway()
    support = OperationsServerInfoSupport(gateway)

    class FakeCpuTimes:
        user = 1.0
        system = 2.0
        idle = 97.0

    class FakeMem:
        total = 1000
        used = 400
        free = 600
        percent = 40.0
        available = 600

    class FakeProcess:
        @staticmethod
        def create_time() -> float:
            return 1000.0

        @staticmethod
        def memory_info() -> SimpleNamespace:
            return SimpleNamespace(rss=100)

        @staticmethod
        def name() -> str:
            return 'python'

        @staticmethod
        def exe() -> str:
            return '/usr/bin/python'

    class FakePsutil:
        @staticmethod
        def cpu_count(*, logical: bool = True) -> int:
            del logical
            return 4

        @staticmethod
        def cpu_times_percent() -> FakeCpuTimes:
            return FakeCpuTimes()

        @staticmethod
        def virtual_memory() -> FakeMem:
            return FakeMem()

        @staticmethod
        def Process(pid: int) -> FakeProcess:
            del pid
            return FakeProcess()

        @staticmethod
        def disk_partitions() -> list[SimpleNamespace]:
            return [
                SimpleNamespace(device='C:', fstype='NTFS', mountpoint='C:\\'),
                SimpleNamespace(device='bad', fstype='x', mountpoint='/bad'),
            ]

        @staticmethod
        def disk_usage(mountpoint: str) -> SimpleNamespace:
            if mountpoint == '/bad':
                raise OSError('skip')
            return SimpleNamespace(total=100, used=40, free=60, percent=40.0)

        @staticmethod
        def net_if_addrs() -> dict[str, list[SimpleNamespace]]:
            return {'eth0': [SimpleNamespace(family=socket.AF_INET, address='192.168.0.2')]}

    patch_gateway(
        gateway,
        get_psutil_module=lambda: FakePsutil(),
        get_bytes2human=lambda: (lambda value: f'{value}B'),
    )
    monkeypatch.setattr(socket, 'gethostname', lambda: 'demo-host')
    monkeypatch.setattr(socket, 'gethostbyname', lambda hostname: '192.168.0.2')

    payload = support.build_server_info_fallback()
    assert payload['cpu']['cpuNum'] == 4
    assert payload['sys']['computerIp'] == '192.168.0.2'
    assert len(payload['sysFiles']) == 1


@pytest.mark.asyncio
async def test_ops_ping_redis_success_and_error() -> None:
    gateway = OperationsInfrastructureGateway()
    service = OperationsRuntimeService(infrastructure_gateway=gateway)
    redis = FakeRedis()
    patch_gateway(
        gateway,
        get_redis_util=lambda: FakeRedisUtil(redis),
        get_redis_error_class=lambda: ConnectionError,
    )
    ok = await service.ping_redis()
    assert ok['ok'] is True
    assert redis.closed is True

    class BoomRedis(FakeRedis):
        async def ping(self) -> bool:
            raise ConnectionError('redis down')

    boom = BoomRedis()
    patch_gateway(gateway, get_redis_util=lambda: FakeRedisUtil(boom))
    fail = await service.ping_redis()
    assert fail['exit_code'] == REDIS_ERROR
    assert boom.closed is True


@pytest.mark.asyncio
async def test_ops_sync_jobs_failure_and_close_exceptions() -> None:
    gateway = OperationsInfrastructureGateway()
    service = OperationsRuntimeService(infrastructure_gateway=gateway)

    class BoomScheduler:
        _is_leader = False

        @staticmethod
        async def init_system_scheduler(redis: FakeRedis) -> None:
            del redis
            raise RuntimeError('sync boom')

        @staticmethod
        async def close_system_scheduler() -> None:
            raise RuntimeError('close boom')

    class BoomRedis(FakeRedis):
        async def close(self) -> None:
            raise RuntimeError('redis close')

    patch_gateway(
        gateway,
        get_redis_util=lambda: FakeRedisUtil(BoomRedis()),
        get_scheduler_util=lambda: BoomScheduler(),
    )
    payload = await service.sync_jobs()
    assert payload['ok'] is False
    assert payload['exit_code'] == SCHEDULER_ERROR


@pytest.mark.asyncio
async def test_ops_get_server_info_paths() -> None:
    gateway = OperationsInfrastructureGateway()
    service = OperationsRuntimeService(infrastructure_gateway=gateway)

    class FakeServerService:
        @staticmethod
        async def get_server_monitor_info() -> Any:
            return SimpleNamespace(model_dump=lambda *, by_alias=False: {'cpu': {'cpuNum': 2}})

    patch_gateway(gateway, get_server_service=lambda: FakeServerService())
    ok = await service.get_server_info()
    assert ok['ok'] is True
    assert ok['server']['cpu']['cpuNum'] == 2

    class GaiBoom:
        @staticmethod
        async def get_server_monitor_info() -> Any:
            raise socket.gaierror('dns fail')

    class FakeSupport:
        @staticmethod
        def build_server_info_fallback() -> dict[str, Any]:
            return {'fallback': True}

    service.server_info_support = FakeSupport()  # type: ignore[assignment]
    patch_gateway(gateway, get_server_service=lambda: GaiBoom())
    fallback = await service.get_server_info()
    assert fallback['server']['fallback'] is True

    class FallbackBoom:
        @staticmethod
        def build_server_info_fallback() -> dict[str, Any]:
            raise RuntimeError('fallback fail')

    service.server_info_support = FallbackBoom()  # type: ignore[assignment]
    fail = await service.get_server_info()
    assert fail['exit_code'] == RUNTIME_ERROR

    class GenericBoom:
        @staticmethod
        async def get_server_monitor_info() -> Any:
            raise RuntimeError('generic')

    patch_gateway(gateway, get_server_service=lambda: GenericBoom())
    generic = await service.get_server_info()
    assert generic['exit_code'] == RUNTIME_ERROR


def test_ops_gateway_lazy_imports() -> None:
    gateway = OperationsInfrastructureGateway()
    assert gateway.get_redis_util() is not None
    assert gateway.get_redis_error_class() is not None
    assert gateway.get_scheduler_util() is not None
    assert gateway.get_server_service() is not None
    assert gateway.get_psutil_module() is not None
    assert callable(gateway.get_bytes2human())
