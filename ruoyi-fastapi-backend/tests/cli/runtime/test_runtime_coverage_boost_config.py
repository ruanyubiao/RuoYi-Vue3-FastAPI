"""Raise config runtime coverage toward 99%."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from cli.exit_codes import ARGUMENT_ERROR, DATABASE_ERROR, REDIS_ERROR
from cli.runtime.config import ConfigRuntimeService
from cli.runtime.config.gateway import ConfigInfrastructureGateway
from cli.runtime.config.support import ConfigDomainSupport

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _runtime_boost_helpers import (
    FakePageModel,
    FakeRedis,
    FakeRedisUtil,
    FakeSession,
    FakeSessionFactory,
    patch_gateway,
)


class RedisExc(Exception):
    pass


class FakeConfigModel:
    def __init__(self, **kwargs: Any) -> None:
        self.config_id = kwargs.get('configId')
        self.config_name = kwargs.get('configName')
        self.config_key = kwargs.get('configKey')
        self.config_value = kwargs.get('configValue')
        self.config_type = kwargs.get('configType')
        self.create_by = kwargs.get('createBy')
        self.create_time = kwargs.get('createTime')
        self.update_by = kwargs.get('updateBy')
        self.update_time = kwargs.get('updateTime')
        self.remark = kwargs.get('remark')
        self.kwargs = kwargs

    def model_dump(self, *, by_alias: bool = False, exclude_none: bool = False) -> dict[str, Any]:
        del by_alias
        payload = {
            'configId': self.config_id,
            'configName': self.config_name,
            'configKey': self.config_key,
            'configValue': self.config_value,
            'configType': self.config_type,
            'createBy': self.create_by,
            'createTime': self.create_time,
            'updateBy': self.update_by,
            'updateTime': self.update_time,
            'remark': self.remark,
        }
        if exclude_none:
            return {key: value for key, value in payload.items() if value is not None}
        return payload

    def validate_fields(self) -> None:
        return None


class FakeConfigVo:
    ConfigModel = FakeConfigModel

    class ConfigPageQueryModel:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs


class FakeSanitizer:
    @staticmethod
    def sanitize_data(payload: dict[str, Any]) -> dict[str, Any]:
        return dict(payload)


def test_config_support_serialize_and_target_model() -> None:
    gateway = ConfigInfrastructureGateway()
    support = ConfigDomainSupport(gateway)
    patch_gateway(
        gateway,
        get_log_sanitizer=lambda: FakeSanitizer(),
        get_config_vo_module=lambda: FakeConfigVo,
        get_common_constant=lambda: SimpleNamespace(NO='N'),
    )

    assert support.serialize_config_model(None) is None
    empty = FakeConfigModel(configId=None, configKey='k')
    assert support.serialize_config_model(empty) is None
    assert support.serialize_cache_payload('k', None) is None

    model = support.build_target_config_model('k', 'v', 'name', 'Y', 'r', None)
    assert model.config_key == 'k'
    assert model.config_name == 'name'

    existing = FakeConfigModel(
        configId=9,
        configName='old',
        configKey='k',
        configValue='oldv',
        configType='N',
        createBy='admin',
        createTime='t0',
        remark='old-r',
    )
    updated = support.build_target_config_model('k', 'new', None, None, None, existing)
    assert updated.config_id == 9
    assert updated.config_name == 'old'
    assert updated.config_type == 'N'


@pytest.mark.asyncio
async def test_config_load_list_get_paths() -> None:
    gateway = ConfigInfrastructureGateway()
    service = ConfigRuntimeService(infrastructure_gateway=gateway)
    redis = FakeRedis()

    class FakeDao:
        @staticmethod
        async def get_config_detail_by_info(session: FakeSession, model: FakeConfigModel) -> Any:
            del session
            if model.kwargs.get('configKey') == 'missing':
                return None
            return SimpleNamespace(
                config_id=1,
                config_name='n',
                config_key=model.kwargs.get('configKey'),
                config_value='db-v',
                config_type='Y',
                create_by='a',
                create_time=None,
                update_by='',
                update_time=None,
                remark='',
            )

    class FakeConfigService:
        @staticmethod
        async def query_config_list_from_cache_services(redis_client: FakeRedis, key: str) -> str | None:
            del redis_client
            if key == 'cache-missing':
                return None
            return 'cache-v'

        @staticmethod
        async def get_config_list_services(session: Any, query: Any, is_page: bool = False) -> Any:
            del session, query
            if is_page:
                return FakePageModel([{'configKey': 'k', 'configValue': 'v'}])
            return [{'configKey': 'k', 'configValue': 'v'}]

        @staticmethod
        async def init_cache_sys_config_services(session: Any, redis_client: FakeRedis) -> None:
            del session, redis_client

    patch_gateway(
        gateway,
        get_async_session_local=lambda: FakeSessionFactory(),
        get_config_dao=lambda: FakeDao(),
        get_config_vo_module=lambda: FakeConfigVo,
        get_config_service=lambda: FakeConfigService(),
        get_redis_util=lambda: FakeRedisUtil(redis),
        get_redis_error_class=lambda: RedisExc,
        get_log_sanitizer=lambda: FakeSanitizer(),
        get_page_model=lambda: FakePageModel,
        get_common_constant=lambda: SimpleNamespace(NO='N'),
        get_redis_init_key_config=lambda: SimpleNamespace(SYS_CONFIG=SimpleNamespace(key='sys_config')),
    )

    db_loaded = await service.load_config_from_database('sys.demo')
    assert not isinstance(db_loaded, dict)
    assert db_loaded[1]['configKey'] == 'sys.demo'

    class BoomDao:
        @staticmethod
        async def get_config_detail_by_info(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError('db boom')

    patch_gateway(gateway, get_config_dao=lambda: BoomDao())
    assert (await service.load_config_from_database('k'))['exit_code'] == DATABASE_ERROR
    assert (await service.get_config('k', source='db'))['exit_code'] == DATABASE_ERROR
    patch_gateway(gateway, get_config_dao=lambda: FakeDao())

    cache_loaded = await service.load_config_from_cache('sys.demo')
    assert not isinstance(cache_loaded, dict)
    assert cache_loaded[0] == 'cache-v'

    class BoomRedisUtil(FakeRedisUtil):
        async def create_redis_pool(self, *, log_enabled: bool = False) -> FakeRedis:
            del log_enabled
            raise RedisExc('cache boom')

    patch_gateway(gateway, get_redis_util=lambda: BoomRedisUtil())
    assert (await service.load_config_from_cache('k'))['exit_code'] == REDIS_ERROR
    patch_gateway(gateway, get_redis_util=lambda: FakeRedisUtil(redis))

    listed = await service.list_configs(config_name='n')
    assert listed['count'] == 1
    paged = await service.list_configs(paged=True)
    assert 'page' in paged

    class BoomList:
        @staticmethod
        async def get_config_list_services(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError('list boom')

        @staticmethod
        async def query_config_list_from_cache_services(*_a: Any, **_k: Any) -> Any:
            return 'cache-v'

        @staticmethod
        async def init_cache_sys_config_services(*_a: Any, **_k: Any) -> None:
            return None

    patch_gateway(gateway, get_config_service=lambda: BoomList())
    assert (await service.list_configs())['exit_code'] == DATABASE_ERROR
    patch_gateway(gateway, get_config_service=lambda: FakeConfigService())

    both = await service.get_config('sys.demo', source='both')
    assert both['ok'] is True
    assert both['inSync'] is False

    db_only = await service.get_config('sys.demo', source='db')
    assert db_only['database']['configValue'] == 'db-v'

    cache_only = await service.get_config('sys.demo', source='cache')
    assert cache_only['cache']['configValue'] == 'cache-v'

    missing_db = await service.get_config('missing', source='db')
    assert missing_db['ok'] is False

    missing_cache = await service.get_config('cache-missing', source='cache')
    assert missing_cache['ok'] is False

    missing_both = await service.get_config('missing', source='both')
    # db missing + cache may still have value for 'missing' key via FakeConfigService returning cache-v
    # Force both none:
    class EmptyCacheService(FakeConfigService):
        @staticmethod
        async def query_config_list_from_cache_services(redis_client: FakeRedis, key: str) -> str | None:
            del redis_client, key
            return None

    patch_gateway(gateway, get_config_service=lambda: EmptyCacheService())
    both_missing = await service.get_config('missing', source='both')
    assert both_missing['ok'] is False

    patch_gateway(gateway, get_redis_util=lambda: BoomRedisUtil())
    cache_err = await service.get_config('sys.demo', source='both')
    assert cache_err['exit_code'] == REDIS_ERROR
    assert 'database' in cache_err


@pytest.mark.asyncio
async def test_config_set_sync_diagnose() -> None:
    gateway = ConfigInfrastructureGateway()
    service = ConfigRuntimeService(infrastructure_gateway=gateway)
    redis = FakeRedis(
        keys=lambda pattern: ['sys_config:k1', 'sys_config:orphan'] if pattern else [],
        mget_values={'sys_config:k1': 'v1', 'sys_config:orphan': 'x'},
    )

    class FakeDao:
        def __init__(self) -> None:
            self.added = False
            self.edited = False

        async def get_config_detail_by_info(self, session: FakeSession, model: FakeConfigModel) -> Any:
            del session
            if model.kwargs.get('configKey') == 'new.key':
                return None
            return SimpleNamespace(
                config_id=2,
                config_name='existing',
                config_key=model.kwargs.get('configKey'),
                config_value='old',
                config_type='Y',
                create_by='admin',
                create_time=None,
                update_by='',
                update_time=None,
                remark='',
            )

        async def add_config_dao(self, session: FakeSession, model: FakeConfigModel) -> None:
            del session
            self.added = True
            model.config_id = 99

        async def edit_config_dao(self, session: FakeSession, payload: dict[str, Any]) -> None:
            del session, payload
            self.edited = True

    class FakeConfigService:
        @staticmethod
        async def get_config_list_services(session: Any, query: Any, is_page: bool = False) -> list[Any]:
            del session, query, is_page
            return [{'configKey': 'k1', 'configValue': 'v1'}, {'configKey': 'missing', 'configValue': 'm'}]

        @staticmethod
        async def init_cache_sys_config_services(session: Any, redis_client: FakeRedis) -> None:
            del session, redis_client

    dao = FakeDao()
    patch_gateway(
        gateway,
        get_async_session_local=lambda: FakeSessionFactory(),
        get_config_dao=lambda: dao,
        get_config_vo_module=lambda: FakeConfigVo,
        get_config_service=lambda: FakeConfigService(),
        get_redis_util=lambda: FakeRedisUtil(redis),
        get_redis_error_class=lambda: RedisExc,
        get_log_sanitizer=lambda: FakeSanitizer(),
        get_common_constant=lambda: SimpleNamespace(NO='N'),
        get_redis_init_key_config=lambda: SimpleNamespace(SYS_CONFIG=SimpleNamespace(key='sys_config')),
        get_page_model=lambda: FakePageModel,
    )

    need_name = await service.set_config('new.key', 'v')
    assert need_name['exit_code'] == ARGUMENT_ERROR

    dry = await service.set_config('new.key', 'v', config_name='n', dry_run=True)
    assert dry['dryRun'] is True
    assert dry['action'] == 'create'

    created = await service.set_config('new.key', 'v', config_name='n')
    assert created['ok'] is True
    assert created['action'] == 'create'
    assert dao.added is True

    updated = await service.set_config('old.key', 'v2')
    assert updated['action'] == 'update'
    assert dao.edited is True

    class BoomDao:
        @staticmethod
        async def get_config_detail_by_info(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError('write boom')

    patch_gateway(gateway, get_config_dao=lambda: BoomDao())
    assert (await service.set_config('k', 'v', config_name='n'))['exit_code'] == DATABASE_ERROR
    patch_gateway(gateway, get_config_dao=lambda: FakeDao())

    class BoomSetRedis(FakeRedis):
        async def set(self, key: str, value: str) -> bool:
            del key, value
            raise RedisExc('set fail')

    patch_gateway(gateway, get_redis_util=lambda: FakeRedisUtil(BoomSetRedis()))
    redis_fail = await service.set_config('old.key', 'v')
    assert redis_fail['exit_code'] == REDIS_ERROR
    assert redis_fail['databaseCommitted'] is True
    patch_gateway(gateway, get_redis_util=lambda: FakeRedisUtil(redis))

    synced = await service.sync_config_cache()
    assert synced['ok'] is True
    assert synced['count'] == 2

    class BoomSyncRedis(FakeRedisUtil):
        async def create_redis_pool(self, *, log_enabled: bool = False) -> FakeRedis:
            del log_enabled
            raise RedisExc('sync redis')

    patch_gateway(gateway, get_redis_util=lambda: BoomSyncRedis())
    assert (await service.sync_config_cache())['exit_code'] == REDIS_ERROR

    class BoomSyncDb:
        @staticmethod
        async def get_config_list_services(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError('sync db')

        @staticmethod
        async def init_cache_sys_config_services(*_a: Any, **_k: Any) -> None:
            return None

    patch_gateway(
        gateway,
        get_config_service=lambda: BoomSyncDb(),
        get_redis_util=lambda: FakeRedisUtil(redis),
    )
    assert (await service.sync_config_cache())['exit_code'] == DATABASE_ERROR
    patch_gateway(gateway, get_config_service=lambda: FakeConfigService())

    diagnosed = await service.diagnose_config(sample_limit=5)
    assert diagnosed['ok'] is False
    assert diagnosed['missingInCacheCount'] >= 1
    assert diagnosed['orphanInCacheCount'] >= 1

    class BoomDiagRedis(FakeRedisUtil):
        async def create_redis_pool(self, *, log_enabled: bool = False) -> FakeRedis:
            del log_enabled
            raise RedisExc('diag redis')

    patch_gateway(gateway, get_redis_util=lambda: BoomDiagRedis())
    assert (await service.diagnose_config())['exit_code'] == REDIS_ERROR

    class BoomDiagDb:
        @staticmethod
        async def get_config_list_services(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError('diag db')

    patch_gateway(
        gateway,
        get_config_service=lambda: BoomDiagDb(),
        get_redis_util=lambda: FakeRedisUtil(redis),
    )
    assert (await service.diagnose_config())['exit_code'] == DATABASE_ERROR


def test_config_gateway_lazy_imports() -> None:
    gateway = ConfigInfrastructureGateway()
    assert gateway.get_async_session_local() is not None
    assert gateway.get_page_model() is not None
    assert gateway.get_common_constant() is not None
    assert gateway.get_redis_init_key_config() is not None
    assert gateway.get_redis_util() is not None
    assert gateway.get_redis_error_class() is not None
    assert gateway.get_log_sanitizer() is not None
    assert gateway.get_config_dao() is not None
    assert gateway.get_config_vo_module() is not None
    assert gateway.get_config_service() is not None
