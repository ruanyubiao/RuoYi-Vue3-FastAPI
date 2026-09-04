"""Shared Fake helpers for cli.runtime coverage boost tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


class FakeSession:
    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        del exc_type, exc, tb

    async def commit(self) -> None:
        return None


class FakeSessionFactory:
    def __call__(self) -> FakeSession:
        return FakeSession()


class FakeRedis:
    def __init__(self, **overrides: Any) -> None:
        self._overrides = overrides
        self.closed = False
        self.deleted: list[tuple[str, ...]] = []
        self.set_calls: list[tuple[str, str]] = []
        self.init_events: list[str] = []

    async def ping(self) -> bool:
        if 'ping' in self._overrides:
            result = self._overrides['ping']
            if isinstance(result, Exception):
                raise result
            return result
        return True

    async def close(self) -> None:
        if 'close' in self._overrides and isinstance(self._overrides['close'], Exception):
            raise self._overrides['close']
        self.closed = True

    async def info(self, section: str | None = None) -> dict[str, Any]:
        if section == 'commandstats':
            return self._overrides.get(
                'commandstats',
                {'cmdstat_get': {'calls': 3}, 'cmdstat_set': {'calls': 1}},
            )
        return self._overrides.get('info', {'redis_version': '7.0'})

    async def dbsize(self) -> int:
        return int(self._overrides.get('dbsize', 2))

    async def keys(self, pattern: str | None = None) -> list[str]:
        if 'keys' in self._overrides:
            keys = self._overrides['keys']
            if callable(keys):
                return keys(pattern)
            return list(keys)
        if pattern is None:
            return ['sys_config:a', 'sys_dict:b']
        return [key for key in ['sys_config:a', 'sys_config:b', 'other:x'] if pattern.replace('*', '') in key or pattern.endswith('*')]

    async def get(self, key: str) -> Any:
        values = self._overrides.get('values', {})
        return values.get(key)

    async def ttl(self, key: str) -> int:
        return int(self._overrides.get('ttl', 60))

    async def delete(self, *keys: str) -> int:
        self.deleted.append(keys)
        return len(keys)

    async def set(self, key: str, value: str) -> bool:
        self.set_calls.append((key, value))
        return True

    async def mget(self, *keys: str) -> list[Any]:
        values = self._overrides.get('mget_values', {})
        return [values.get(key) for key in keys]


class FakeRedisUtil:
    def __init__(self, redis: FakeRedis | None = None, *, fail: Exception | None = None) -> None:
        self.redis = redis or FakeRedis()
        self.fail = fail
        self.init_dict_calls = 0
        self.init_config_calls = 0

    async def create_redis_pool(self, *, log_enabled: bool = False) -> FakeRedis:
        del log_enabled
        if self.fail is not None:
            raise self.fail
        return self.redis

    async def init_sys_dict(self, redis: FakeRedis) -> None:
        self.init_dict_calls += 1
        redis.init_events.append('dict')

    async def init_sys_config(self, redis: FakeRedis) -> None:
        self.init_config_calls += 1
        redis.init_events.append('config')


class FakePageModel:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows or []

    def model_dump(self, *, by_alias: bool = False) -> dict[str, Any]:
        del by_alias
        return {'rows': self._rows, 'total': len(self._rows)}


class ServiceExc(Exception):
    """Fake ServiceException for except ServiceException branches."""


def patch_gateway(gateway: Any, **methods: Any) -> None:
    for name, value in methods.items():
        object.__setattr__(gateway, name, value if callable(value) else (lambda v=value: v))


def make_dump_model(payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        model_dump=lambda *, by_alias=False, exclude_none=False: dict(payload),
        **{k: v for k, v in payload.items()},
    )
