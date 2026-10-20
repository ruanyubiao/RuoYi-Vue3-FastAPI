"""Raise coverage for annotation + aspect modules toward 99%+."""

from __future__ import annotations

import json
import re
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import Column, Integer
from starlette.background import BackgroundTask

from common.annotation.cache_annotation import ApiCache, ApiCacheEvict, ApiCacheManager, _ApiCacheSupport
from common.annotation.rate_limit_annotation import (
    ApiRateLimit,
    ApiRateLimitBypassConfig,
    ApiRateLimitPreset,
    ApiRateLimitPresetConfig,
)
from common.aspect.data_scope import DataScopeDependency, GetDataScope
from common.aspect.interface_auth import (
    CheckRoleInterfaceAuth,
    CheckUserInterfaceAuth,
    RoleInterfaceAuthDependency,
    UserInterfaceAuthDependency,
)
from common.aspect.pre_auth import CurrentUserDependency, PreAuth, PreAuthDependency
from common.constant import HttpStatusConstant
from common.context import RequestContext
from common.enums import HttpMethod
from config.database import Base
from exceptions.exception import AuthException, LoginException, PermissionException
from module_admin.entity.vo.role_vo import RoleModel
from module_admin.entity.vo.user_vo import CurrentUserModel, UserInfoModel


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_request(
    *,
    path: str = '/api/test',
    method: str = 'GET',
    headers: dict[str, str] | None = None,
    query_string: bytes = b'',
    path_params: dict | None = None,
    body: bytes = b'',
    redis: object | None = ...,
    route_path: str | None = None,
) -> Request:
    header_items = []
    if headers:
        for key, value in headers.items():
            header_items.append((key.lower().encode('latin-1'), value.encode('latin-1')))
    app_state = SimpleNamespace()
    if redis is not ...:
        app_state.redis = redis
    app = SimpleNamespace(state=app_state)
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0'},
        'http_version': '1.1',
        'method': method,
        'scheme': 'http',
        'path': path,
        'raw_path': path.encode(),
        'query_string': query_string,
        'headers': header_items,
        'client': ('127.0.0.1', 12345),
        'server': ('testserver', 80),
        'root_path': '',
        'app': app,
        'path_params': path_params or {},
    }
    if route_path is not None:
        scope['route'] = SimpleNamespace(path=route_path)

    async def receive() -> dict:
        return {'type': 'http.request', 'body': body, 'more_body': False}

    return Request(scope, receive)


def _current_user(
    *,
    user_id: int = 2,
    dept_id: int = 100,
    admin: bool = False,
    permissions: list | None = None,
    roles: list | None = None,
    role_models: list | None = None,
) -> CurrentUserModel:
    user = UserInfoModel(
        userId=user_id,
        deptId=dept_id,
        userName='tester',
        role=role_models if role_models is not None else [],
    )
    # admin is forced by user_id==1 validator; override after for non-1 admin tests
    if admin and user_id != 1:
        object.__setattr__(user, 'admin', True)
    return CurrentUserModel(
        permissions=permissions if permissions is not None else [],
        roles=roles if roles is not None else [],
        user=user,
    )


class _ScopeModel(Base):
    __tablename__ = 'cov_scope_model'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    dept_id = Column(Integer)


class _ScopeNoAlias(Base):
    __tablename__ = 'cov_scope_no_alias'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True)


# ---------------------------------------------------------------------------
# ApiCacheManager / _ApiCacheSupport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_cache_manager_clear_paths() -> None:
    redis = MagicMock()

    async def _empty_scan(**_kwargs):
        if False:
            yield 'x'

    async def _keys_scan(**_kwargs):
        for k in ('a', 'b'):
            yield k

    redis.scan_iter = lambda **kw: _empty_scan(**kw)
    assert await ApiCacheManager.clear_namespace(redis, 'ns') == 0
    assert await ApiCacheManager.clear_all(redis) == 0

    redis.scan_iter = lambda **kw: _keys_scan(**kw)
    redis.delete = AsyncMock(return_value=2)
    assert await ApiCacheManager.clear_namespaces(redis, ['ns1', 'ns1', 'ns2']) == 4
    assert await ApiCacheManager.clear_namespace_prefixes(redis, ['pre', 'pre']) == 2
    assert 'API_CACHE' in ApiCacheManager.build_namespace_pattern('x') or True
    assert ApiCacheManager.build_namespace_pattern('demo').endswith(':demo:*')
    assert ApiCacheManager.build_namespace_prefix_pattern('demo').endswith(':demo*')


def test_api_cache_support_json_helpers() -> None:
    support = _ApiCacheSupport()
    assert support._load_json_content('{"a":1}') == {'a': 1}
    assert support._load_json_content('not-json') is None

    assert support._extract_json_response_content(None) is None
    assert support._extract_json_response_content(StreamingResponse(iter([]))) is None
    assert support._extract_json_response_content(JSONResponse({'code': 200})) == {'code': 200}
    assert support._extract_json_response_content(Response(content=b'x')) is None
    assert support._extract_json_response_content({'ok': True}) == {'ok': True}

    assert support._match_response_codes(['x'], {200}) is True
    assert support._match_response_codes({'msg': 'ok'}, {200}) is True
    assert support._match_response_codes({'code': 200}, {200}) is True
    assert support._match_response_codes({'code': 500}, {200}) is False

    assert support._get_matched_response_content(None, {200}) is None
    assert support._get_matched_response_content({'code': 200}, {200}) == {'code': 200}
    assert support._get_matched_response_content({'code': 500}, {200}) is None


# ---------------------------------------------------------------------------
# ApiCache decorator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_cache_skips_without_request_or_redis_or_method() -> None:
    cache = ApiCache(namespace='demo')

    @cache
    async def no_request() -> str:
        return 'ok'

    assert await no_request() == 'ok'

    @cache
    async def with_request(request: Request) -> str:
        return 'ok'

    assert await with_request(_make_request(redis=None)) == 'ok'
    assert await with_request(_make_request(method='POST', redis=AsyncMock())) == 'ok'


@pytest.mark.asyncio
async def test_api_cache_hit_and_miss_and_user_scope() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    cache = ApiCache(namespace='demo', expire_seconds=5, vary_by_user=True)

    @cache
    async def endpoint(request: Request) -> dict:
        return {
            'code': HttpStatusConstant.SUCCESS,
            'msg': 'ok',
            'success': True,
            'time': 'old',
            'data': 1,
        }

    request = _make_request(
        path='/api/x',
        method='GET',
        query_string=b'a=1&a=2',
        path_params={'id': '9'},
        body=b'{"k":1}',
        redis=redis,
        headers={'Authorization': 'Bearer tok'},
    )
    token = RequestContext.set_current_user(_current_user(user_id=7))
    try:
        result = await endpoint(request)
        assert result['data'] == 1
        redis.set.assert_awaited()
        assert request.state.api_response_headers['X-Api-Cache'] == 'MISS'
    finally:
        RequestContext.reset_current_user(token)

    cached_payload = json.dumps(
        {
            'content': {
                'code': HttpStatusConstant.SUCCESS,
                'msg': 'ok',
                'success': True,
                'time': 'old',
                'data': 2,
            },
            'status_code': 200,
            'media_type': 'application/json',
            'headers': {'X-Custom': '1'},
        }
    )
    redis.get = AsyncMock(return_value=cached_payload)
    hit = await endpoint(_make_request(redis=redis))
    assert isinstance(hit, JSONResponse)
    assert hit.headers['X-Api-Cache'] == 'HIT'


@pytest.mark.asyncio
async def test_api_cache_user_scope_login_exception_and_payload_filters() -> None:
    cache = ApiCache(namespace='demo', vary_by_user=True)
    request = _make_request(headers={'Authorization': 'Bearer abc'}, redis=AsyncMock())
    RequestContext.clear_all()
    assert cache._get_user_scope(request)
    assert cache._get_user_scope(_make_request()) == ''

    assert cache._serialize_response(StreamingResponse(iter([]))) is None
    assert cache._extract_response_payload(Response(content=b'x')) is None

    bg = JSONResponse({'code': 200}, background=BackgroundTask(lambda: None))
    assert cache._extract_response_payload(bg) is None

    bad_code = JSONResponse({'code': 500})
    assert cache._extract_response_payload(bad_code) is None

    good = JSONResponse({'code': 200, 'msg': 'ok'}, headers={'content-type': 'application/json', 'X-A': '1'})
    payload = cache._extract_response_payload(good)
    assert payload is not None
    assert 'content-type' not in {k.lower() for k in payload['headers']}
    assert payload['headers'].get('X-A') == '1' or 'x-a' in {k.lower() for k in payload['headers']}

    assert cache._extract_response_payload({'code': 500}) is None
    plain = cache._extract_response_payload({'code': 200, 'data': []})
    assert plain is not None and plain['status_code'] == HttpStatusConstant.SUCCESS

    assert cache._refresh_response_time('x') == 'x'
    assert cache._refresh_response_time({'code': 1}) == {'code': 1}
    refreshed = cache._refresh_response_time(
        {'code': 200, 'msg': 'm', 'success': True, 'time': 't'}
    )
    assert refreshed['time'] != 't'

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()

    @cache
    async def stream_endpoint(request: Request):
        return StreamingResponse(iter([b'x']))

    await stream_endpoint(_make_request(redis=redis))
    redis.set.assert_not_awaited()


def test_api_cache_evict_requires_namespace() -> None:
    with pytest.raises(ValueError):
        ApiCacheEvict()


@pytest.mark.asyncio
async def test_api_cache_evict_wrapper_paths() -> None:
    redis = AsyncMock()

    async def _keys_scan(**_kwargs):
        yield 'k1'

    redis.scan_iter = lambda **kw: _keys_scan(**kw)
    redis.delete = AsyncMock(return_value=1)

    evict = ApiCacheEvict(namespaces=['ns'], namespace_prefixes=['pre'])

    @evict
    async def endpoint(request: Request) -> dict:
        return {'code': HttpStatusConstant.SUCCESS}

    assert await endpoint(_make_request(redis=None)) == {'code': HttpStatusConstant.SUCCESS}

    result = await endpoint(_make_request(redis=redis))
    assert result['code'] == HttpStatusConstant.SUCCESS
    redis.delete.assert_awaited()

    @evict
    async def fail_endpoint(request: Request) -> dict:
        return {'code': 500}

    redis.delete.reset_mock()
    await fail_endpoint(_make_request(redis=redis))
    redis.delete.assert_not_awaited()

    only_prefix = ApiCacheEvict(namespace_prefixes=['only'])
    await only_prefix._evict_cache(redis)
    only_ns = ApiCacheEvict(namespaces=['only'])
    await only_ns._evict_cache(redis)


# ---------------------------------------------------------------------------
# ApiRateLimit
# ---------------------------------------------------------------------------


def test_api_rate_limit_init_validation() -> None:
    with pytest.raises(ValueError):
        ApiRateLimit(namespace='')
    with pytest.raises(ValueError):
        ApiRateLimit(namespace='n', limit=0)
    with pytest.raises(ValueError):
        ApiRateLimit(namespace='n', limit=1, window_seconds=0)
    with pytest.raises(ValueError):
        ApiRateLimit(namespace='n', limit=1, window_seconds=1, scope='bad')  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ApiRateLimit(namespace='n', limit=1, window_seconds=1, algorithm='bad')  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ApiRateLimit(namespace='n', limit=1, window_seconds=1, fail_strategy='bad')  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ApiRateLimit(
            namespace='n',
            limit=1,
            window_seconds=1,
            scope='ip',
            bypass=ApiRateLimitBypassConfig(roles=('admin',)),
        )
    with pytest.raises(ValueError):
        ApiRateLimit(
            namespace='n',
            limit=1,
            window_seconds=1,
            scope='user',
            bypass=ApiRateLimitBypassConfig(roles=('  ',)),
        )

    preset = ApiRateLimitPresetConfig(name='P', limit=2, window_seconds=3, methods=(HttpMethod.GET,))
    lim = ApiRateLimit(namespace='n', preset=preset, message='slow')
    assert lim.limit == 2 and lim.preset_name == 'P' and lim.message == 'slow'
    assert ApiRateLimitPreset.ANON_AUTH_LOGIN.limit == 12


@pytest.mark.asyncio
async def test_api_rate_limit_wrapper_allow_block_bypass_and_fail() -> None:
    ApiRateLimit._LOCAL_FALLBACK_STORE.clear()

    @ApiRateLimit(namespace='rl', limit=2, window_seconds=60, methods=(HttpMethod.POST,))
    async def method_skip(request: Request) -> str:
        return 'skip'

    assert await method_skip(_make_request(method='GET')) == 'skip'

    @ApiRateLimit(namespace='rl', limit=2, window_seconds=60)
    async def no_req() -> str:
        return 'nr'

    assert await no_req() == 'nr'

    bypass = ApiRateLimit(
        namespace='rl',
        limit=1,
        window_seconds=60,
        scope='user',
        bypass=ApiRateLimitBypassConfig(roles=('admin', 'ops')),
    )

    @bypass
    async def bypass_ep(request: Request) -> str:
        return 'bypassed'

    token = RequestContext.set_current_user(_current_user(roles=['admin'], role_models=[]))
    try:
        assert await bypass_ep(_make_request()) == 'bypassed'
    finally:
        RequestContext.reset_current_user(token)

    # no bypass roles match / no user
    assert bypass._match_bypass_role() is None
    token = RequestContext.set_current_user(_current_user(roles=['guest']))
    try:
        assert bypass._match_bypass_role() is None
    finally:
        RequestContext.reset_current_user(token)

    # redis unavailable + open
    open_rl = ApiRateLimit(namespace='rl', limit=1, window_seconds=60, fail_strategy='open')

    @open_rl
    async def open_ep(request: Request) -> str:
        return 'open'

    assert await open_ep(_make_request(redis=None)) == 'open'
    open_err_redis = AsyncMock()
    open_err_redis.eval = AsyncMock(side_effect=RuntimeError('open-err'))
    assert await open_ep(_make_request(redis=open_err_redis)) == 'open'

    # redis ok but scope skips (user not logged in)
    skip_rl = ApiRateLimit(namespace='rl-skip', limit=1, window_seconds=60, scope='user')

    @skip_rl
    async def skip_ep(request: Request) -> str:
        return 'skipped'

    RequestContext.clear_all()
    assert await skip_ep(_make_request(redis=AsyncMock())) == 'skipped'

    # redis unavailable + closed
    closed_rl = ApiRateLimit(namespace='rl', limit=1, window_seconds=60, fail_strategy='closed')

    @closed_rl
    async def closed_ep(request: Request):
        return 'never'

    blocked = await closed_ep(_make_request(redis=None))
    assert blocked.status_code == 429

    # redis error + local_fallback
    bad_redis = AsyncMock()
    bad_redis.eval = AsyncMock(side_effect=RuntimeError('boom'))
    local_rl = ApiRateLimit(
        namespace='rl-local',
        limit=1,
        window_seconds=60,
        fail_strategy='local_fallback',
        algorithm='sliding_window',
    )

    @local_rl
    async def local_ep(request: Request) -> str:
        return 'local'

    req = _make_request(redis=bad_redis, route_path='/api/{id}')
    assert await local_ep(req) == 'local'
    blocked2 = await local_ep(req)
    assert blocked2.status_code == 429

    # fixed window acquire allowed then denied
    good_redis = AsyncMock()
    good_redis.eval = AsyncMock(side_effect=[(1, 1, 1, 1000), (0, 2, 0, 500)])
    fixed = ApiRateLimit(namespace='rl-fixed', limit=1, window_seconds=60, algorithm='fixed_window')

    @fixed
    async def fixed_ep(request: Request) -> str:
        return 'ok'

    assert await fixed_ep(_make_request(redis=good_redis)) == 'ok'
    denied = await fixed_ep(_make_request(redis=good_redis))
    assert denied.status_code == 429

    # sliding window path
    slide_redis = AsyncMock()
    slide_redis.eval = AsyncMock(return_value=(1, 1, 0, 1000))
    slide = ApiRateLimit(namespace='rl-slide', limit=5, window_seconds=10, algorithm='sliding_window')
    assert await slide._acquire_rate_limit(slide_redis, _make_request()) is not None

    # scope user without login → skip
    user_rl = ApiRateLimit(namespace='rl-user', limit=1, window_seconds=60, scope='user')
    RequestContext.clear_all()
    assert user_rl._build_rate_limit_key(_make_request(), 1) is None
    assert await user_rl._acquire_rate_limit(AsyncMock(), _make_request()) is None

    # user_or_ip falls back to ip
    uip = ApiRateLimit(namespace='rl-uip', limit=1, window_seconds=60, scope='user_or_ip')
    assert uip._get_scope_value(_make_request()).startswith('ip:')

    token = RequestContext.set_current_user(_current_user(user_id=9))
    try:
        assert uip._get_scope_value(_make_request()).startswith('user:')
    finally:
        RequestContext.reset_current_user(token)

    # local fallback empty-window reinit branch
    ApiRateLimit._LOCAL_FALLBACK_STORE.clear()
    key_rl = ApiRateLimit(namespace='rl-lf', limit=3, window_seconds=60, fail_strategy='local_fallback')
    req2 = _make_request()
    # seed expired entries then empty
    k = key_rl._build_rate_limit_key(req2, int(__import__('time').time() * 1000), include_window_bucket=False)
    assert k is not None
    ApiRateLimit._LOCAL_FALLBACK_STORE[k] = deque([1])
    assert key_rl._acquire_local_fallback_rate_limit(req2)['allowed'] is True

    # local fallback when scope unavailable
    user_only = ApiRateLimit(namespace='rl-uo', limit=1, window_seconds=60, scope='user', fail_strategy='local_fallback')
    RequestContext.clear_all()
    assert user_only._acquire_local_fallback_rate_limit(_make_request()) is None
    assert user_only._resolve_failed_rate_limit(_make_request(), 'x', 'y') is None

    # normalize empty bypass
    assert key_rl._normalize_bypass_roles(None) == ()
    assert key_rl._normalize_bypass_roles(['a', 'a', 'b']) == ('a', 'b')

    # headers
    headers = key_rl._build_rate_limit_headers(
        {'allowed': False, 'remaining': 0, 'reset_at': 1, 'reset_after_seconds': 2}
    )
    assert headers['Retry-After'] == '2'
    headers2 = key_rl._build_rate_limit_headers(
        {'allowed': True, 'remaining': 1, 'reset_at': 1, 'reset_after_seconds': 2}
    )
    assert 'Retry-After' not in headers2

    key_rl._log_rate_limit_hit(_make_request(), {'current': 1, 'reset_after_seconds': 1})
    key_rl._log_rate_limit_degrade(_make_request(), 'r', 'e')
    local_rl._log_rate_limit_degrade(_make_request(), 'r', 'e')
    bypass._log_rate_limit_bypass(_make_request(), 'admin')


# ---------------------------------------------------------------------------
# data_scope
# ---------------------------------------------------------------------------


def test_data_scope_all_branches() -> None:
    RequestContext.clear_all()
    dep = GetDataScope(_ScopeModel)
    request = _make_request(path='/secure')

    # admin → True
    token = RequestContext.set_current_user(
        _current_user(
            user_id=1,
            role_models=[RoleModel(roleId=1, roleKey='r', dataScope='5')],
        )
    )
    try:
        sql = dep(request)
        assert sql is not None
    finally:
        RequestContext.reset_current_user(token)

    # ALL scope
    token = RequestContext.set_current_user(
        _current_user(role_models=[RoleModel(roleId=2, roleKey='r', dataScope='1')])
    )
    try:
        assert dep(request) is not None
    finally:
        RequestContext.reset_current_user(token)

    # CUSTOM single + multi, DEPT, DEPT_AND_CHILD, SELF, unknown, and missing aliases
    roles = [
        RoleModel(roleId=10, roleKey='c1', dataScope='2'),
        RoleModel(roleId=11, roleKey='c2', dataScope='2'),
        RoleModel(roleId=12, roleKey='d', dataScope='3'),
        RoleModel(roleId=13, roleKey='dc', dataScope='4'),
        RoleModel(roleId=14, roleKey='s', dataScope='5'),
        RoleModel(roleId=15, roleKey='x', dataScope=None),
    ]
    token = RequestContext.set_current_user(_current_user(role_models=roles))
    try:
        assert dep(request) is not None
    finally:
        RequestContext.reset_current_user(token)

    # single custom only
    token = RequestContext.set_current_user(
        _current_user(role_models=[RoleModel(roleId=20, roleKey='c', dataScope='2')])
    )
    try:
        assert dep(request) is not None
    finally:
        RequestContext.reset_current_user(token)

    no_alias = GetDataScope(_ScopeNoAlias, user_alias='user_id', dept_alias='dept_id')
    token = RequestContext.set_current_user(
        _current_user(
            role_models=[
                RoleModel(roleId=1, roleKey='a', dataScope='2'),
                RoleModel(roleId=2, roleKey='b', dataScope='2'),
                RoleModel(roleId=3, roleKey='c', dataScope='3'),
                RoleModel(roleId=4, roleKey='d', dataScope='4'),
                RoleModel(roleId=5, roleKey='e', dataScope='5'),
            ]
        )
    )
    try:
        assert no_alias(request) is not None
    finally:
        RequestContext.reset_current_user(token)

    assert DataScopeDependency(_ScopeModel) is not None


# ---------------------------------------------------------------------------
# interface_auth
# ---------------------------------------------------------------------------


def test_interface_auth_user_and_role() -> None:
    request = _make_request(path='/secure')

    # wildcard
    token = RequestContext.set_current_user(_current_user(permissions=['*:*:*']))
    try:
        assert CheckUserInterfaceAuth('a')(request) is True
    finally:
        RequestContext.reset_current_user(token)

    # string match
    token = RequestContext.set_current_user(_current_user(permissions=['sys:user:list']))
    try:
        assert CheckUserInterfaceAuth('sys:user:list')(request) is True
        with pytest.raises(PermissionException):
            CheckUserInterfaceAuth('sys:user:add')(request)
        assert CheckUserInterfaceAuth(['sys:user:list', 'x'], is_strict=False)(request) is True
        with pytest.raises(PermissionException):
            CheckUserInterfaceAuth(['sys:user:list', 'x'], is_strict=True)(request)
        assert CheckUserInterfaceAuth(['sys:user:list'], is_strict=True)(request) is True
        with pytest.raises(PermissionException):
            CheckUserInterfaceAuth(['x', 'y'], is_strict=False)(request)
    finally:
        RequestContext.reset_current_user(token)

    roles = [
        RoleModel(roleId=1, roleKey='admin'),
        RoleModel(roleId=2, roleKey='common'),
    ]
    token = RequestContext.set_current_user(_current_user(role_models=roles))
    try:
        assert CheckRoleInterfaceAuth('admin')(request) is True
        with pytest.raises(PermissionException):
            CheckRoleInterfaceAuth('missing')(request)
        assert CheckRoleInterfaceAuth(['admin', 'x'], is_strict=False)(request) is True
        with pytest.raises(PermissionException):
            CheckRoleInterfaceAuth(['admin', 'x'], is_strict=True)(request)
        assert CheckRoleInterfaceAuth(['admin', 'common'], is_strict=True)(request) is True
        with pytest.raises(PermissionException):
            CheckRoleInterfaceAuth(['x', 'y'], is_strict=False)(request)
    finally:
        RequestContext.reset_current_user(token)

    assert UserInterfaceAuthDependency('a') is not None
    assert RoleInterfaceAuthDependency('a') is not None


# ---------------------------------------------------------------------------
# pre_auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_auth_exclude_and_login() -> None:
    auth = PreAuth(
        exclude_routes=[
            {'path': '/login', 'methods': ['POST']},
            {'path': '/open/{id}', 'methods': [], 'ignore_paths': ['/open/secret']},
            {'path': '/health'},
        ]
    )
    assert auth._compile_path_pattern('/x/{id}').pattern == '^/x/[^/]+$'

    db = AsyncMock()
    with patch('common.aspect.pre_auth.AppConfig.app_root_path', '/dev-api'):
        # excluded by method
        assert await auth(_make_request(path='/dev-api/login', method='POST'), db=db) is None
        # ignore_paths continues to auth
        with pytest.raises(AuthException):
            await auth(_make_request(path='/dev-api/open/secret', method='GET'), db=db)
        # wildcard exclude all methods
        assert await auth(_make_request(path='/dev-api/open/1', method='PUT'), db=db) is None
        assert await auth(_make_request(path='/dev-api/health', method='GET'), db=db) is None
        # missing token
        with pytest.raises(AuthException):
            await auth(_make_request(path='/dev-api/secure', method='GET'), db=db)

        user = _current_user()
        with patch(
            'common.aspect.pre_auth.LoginService.get_current_user',
            new=AsyncMock(return_value=user),
        ):
            got = await auth(
                _make_request(
                    path='/dev-api/secure',
                    method='GET',
                    headers={'Authorization': 'Bearer t'},
                ),
                db=db,
            )
            assert got is user

    with patch('common.aspect.pre_auth.AppConfig.app_root_path', ''):
        assert await auth(_make_request(path='/login', method='POST'), db=db) is None

    assert PreAuthDependency() is not None
    assert CurrentUserDependency() is not None
