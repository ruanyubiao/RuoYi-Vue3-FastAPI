"""Raise cache runtime coverage toward 99%."""

from __future__ import annotations

from typing import Any

import pytest

from cli.exit_codes import REDIS_ERROR, RUNTIME_ERROR
from cli.runtime.cache import CacheRuntimeService
from cli.runtime.cache.gateway import REDIS_TTL_PERSISTENT, CacheInfrastructureGateway
from cli.runtime.cache.support import CacheDomainSupport, CacheRedisSupport

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _runtime_boost_helpers import FakeRedis, FakeRedisUtil, patch_gateway


class RedisExc(Exception):
    pass


def _wire_cache(gateway: CacheInfrastructureGateway, redis: FakeRedis) -> CacheRuntimeService:
    util = FakeRedisUtil(redis)
    patch_gateway(
        gateway,
        get_redis_util=lambda: util,
        get_redis_error_class=lambda: RedisExc,
        get_redis_init_key_config=lambda: [
            SimpleKey('sys_config', '参数'),
            SimpleKey('sys_dict', '字典'),
        ],
    )
    return CacheRuntimeService(infrastructure_gateway=gateway)


class SimpleKey:
    def __init__(self, key: str, remark: str) -> None:
        self.key = key
        self.remark = remark


def test_cache_domain_and_redis_support_helpers() -> None:
    gateway = CacheInfrastructureGateway()
    support = CacheDomainSupport(gateway)
    patch_gateway(
        gateway,
        get_redis_init_key_config=lambda: [SimpleKey('sys_config', '参数')],
    )
    assert support.build_cache_name_items() == [{'cacheName': 'sys_config', 'remark': '参数'}]
    assert support.build_clear_scope(cache_name='', cache_key='x', clear_all=True) == {'mode': 'all'}
    assert support.build_clear_scope(cache_name='', cache_key='x', clear_all=False) == {
        'mode': 'cacheKey',
        'cacheKey': 'x',
    }

    redis_support = CacheRedisSupport(gateway, support)
    assert redis_support.build_redis_error_result('m', RuntimeError('e'))['exit_code'] == REDIS_ERROR
    assert redis_support.build_cache_name_keys_pattern('sys_config') == 'sys_config:*'
    assert redis_support.build_clear_target_pattern(cache_name='', cache_key='k', clear_all=True) is None
    assert redis_support.build_clear_target_pattern(cache_name='sys_config', cache_key='', clear_all=False) == (
        'sys_config:*'
    )
    assert redis_support.build_clear_target_pattern(cache_name='', cache_key='logo', clear_all=False) == '*logo'


@pytest.mark.asyncio
async def test_cache_stats_keys_value_ttl_warmup() -> None:
    gateway = CacheInfrastructureGateway()
    redis = FakeRedis(
        values={'sys_config:site': 'v1'},
        ttl=30,
        keys=lambda pattern: ['sys_config:site', 'sys_config:logo']
        if pattern and pattern.startswith('sys_config')
        else ['sys_config:site'],
    )
    service = _wire_cache(gateway, redis)

    stats = await service.get_cache_stats()
    assert stats['ok'] is True
    assert stats['dbSize'] == 2
    assert stats['commandStats'][0]['name'] in {'get', 'set'}

    keys = await service.list_cache_keys('sys_config')
    assert keys['count'] == 2

    value = await service.get_cache_value('sys_config', 'site')
    assert value['cacheValue'] == 'v1'
    missing = await service.get_cache_value('sys_config', 'nope')
    assert missing['ok'] is False

    ttl = await service.get_cache_ttl('sys_config', 'site')
    assert ttl['ok'] is True
    assert ttl['ttlSeconds'] == 30
    assert ttl['expires'] is True

    redis._overrides['ttl'] = REDIS_TTL_PERSISTENT
    persistent = await service.get_cache_ttl('sys_config', 'site')
    assert persistent['persistent'] is True
    assert persistent['expires'] is False

    warm = await service.warmup_cache()
    assert warm['ok'] is True
    assert 'dict' in redis.init_events


@pytest.mark.asyncio
async def test_cache_clear_modes_and_errors() -> None:
    gateway = CacheInfrastructureGateway()
    redis = FakeRedis(
        keys=lambda pattern: ['sys_config:a', 'sys_config:b']
        if pattern
        else ['sys_config:a', 'sys_dict:b'],
    )
    service = _wire_cache(gateway, redis)

    invalid = await service.clear_cache(cache_name='a', cache_key='b')
    assert invalid['exit_code'] == RUNTIME_ERROR

    cleared = await service.clear_cache(cache_name='sys_config')
    assert cleared['ok'] is True
    assert cleared['matchedCount'] == 2
    assert redis.deleted

    redis2 = FakeRedis(keys=lambda pattern: ['a', 'b'] if pattern is None else [])
    service2 = _wire_cache(gateway, redis2)
    all_cleared = await service2.clear_cache(clear_all=True)
    assert all_cleared['ok'] is True
    assert 'dict' in redis2.init_events

    key_cleared = await service.clear_cache(cache_key='logo', dry_run=True)
    assert key_cleared['dryRun'] is True

    class BoomRedis(FakeRedis):
        async def info(self, section: str | None = None) -> dict[str, Any]:
            del section
            raise RedisExc('info fail')

        async def keys(self, pattern: str | None = None) -> list[str]:
            del pattern
            raise RedisExc('keys fail')

        async def get(self, key: str) -> Any:
            del key
            raise RedisExc('get fail')

        async def ttl(self, key: str) -> int:
            del key
            raise RedisExc('ttl fail')

        async def delete(self, *keys: str) -> int:
            del keys
            raise RedisExc('delete fail')

    boom = BoomRedis()
    boom_service = _wire_cache(gateway, boom)
    assert (await boom_service.get_cache_stats())['exit_code'] == REDIS_ERROR
    assert (await boom_service.list_cache_keys('sys_config'))['exit_code'] == REDIS_ERROR
    assert (await boom_service.get_cache_value('sys_config', 'a'))['exit_code'] == REDIS_ERROR
    assert (await boom_service.get_cache_ttl('sys_config', 'a'))['exit_code'] == REDIS_ERROR
    assert (await boom_service.clear_cache(cache_name='sys_config'))['exit_code'] == REDIS_ERROR

    class WarmBoom(FakeRedis):
        pass

    warm_util = FakeRedisUtil(WarmBoom())

    async def boom_init(redis_client: FakeRedis) -> None:
        del redis_client
        raise RedisExc('warm fail')

    object.__setattr__(warm_util, 'init_sys_dict', boom_init)
    patch_gateway(gateway, get_redis_util=lambda: warm_util, get_redis_error_class=lambda: RedisExc)
    warm_service = CacheRuntimeService(infrastructure_gateway=gateway)
    assert (await warm_service.warmup_cache())['exit_code'] == REDIS_ERROR


def test_cache_gateway_lazy_imports() -> None:
    gateway = CacheInfrastructureGateway()
    assert gateway.get_redis_util() is not None
    assert gateway.get_redis_error_class() is not None
    assert gateway.get_redis_init_key_config() is not None
