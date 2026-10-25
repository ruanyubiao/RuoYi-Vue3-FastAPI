"""module_payload/controller 的 HTTP 层测试。

覆盖三件事：
1. 路由清单：8 个控制器全部挂载，前缀与 doc/04-后端接口设计.md 一致；
2. 鉴权：每个地检接口在未带 token 时返回 401（PreAuth），在缺少接口权限时返回 403；
3. 典型接口的正常调用：读取 assets/config 下真实配置，或 monkeypatch 服务层后校验
   参数透传与统一响应结构 ``{"code": 200, "msg": ..., "data": ...}``。

不依赖 MySQL / Redis：``get_db`` 被替换为空会话，Redis 用 MagicMock/AsyncMock。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.testclient import TestClient

from common.aspect.interface_auth import CheckUserInterfaceAuth
from common.aspect.pre_auth import PreAuth
from common.context import RequestContext
from config.get_db import get_db
from exceptions.handle import handle_exception
from module_admin.entity.vo.user_vo import CurrentUserModel
from module_payload.controller.payload_board_controller import payload_board_controller
from module_payload.controller.payload_camera_controller import payload_camera_controller
from module_payload.controller.payload_config_file_controller import payload_config_file_controller
from module_payload.controller.payload_device_controller import (
    payload_device_controller,
    payload_timeconv_controller,
)
from module_payload.controller.payload_lvds_controller import payload_lvds_controller
from module_payload.controller.payload_sequence_controller import payload_sequence_controller
from module_payload.controller.payload_telecontrol_controller import payload_telecontrol_controller
from module_payload.controller.payload_telemetry_controller import payload_telemetry_controller
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.service.payload_device_service import PayloadDeviceService
from module_payload.service.payload_lvds_service import PayloadLvdsService

if TYPE_CHECKING:
    from collections.abc import Iterator

ROUTERS = [
    ('/payload/board', payload_board_controller),
    ('/payload/camera', payload_camera_controller),
    ('/payload/config-files', payload_config_file_controller),
    ('/payload/device', payload_device_controller),
    ('/payload/device', payload_timeconv_controller),
    ('/payload/lvds', payload_lvds_controller),
    ('/payload/sequence', payload_sequence_controller),
    ('/payload/telecontrol', payload_telecontrol_controller),
    ('/payload/telemetry', payload_telemetry_controller),
]

SUCCESS = 200
UNAUTHORIZED = 401
FORBIDDEN = 403
VALIDATION_ERROR = 422
HTTP_OK = 200
MIN_PAYLOAD_ROUTES = 90
MIN_PERM_CHECKED = 50


async def _no_db() -> Any:
    yield MagicMock(name='db')


def _build_app() -> FastAPI:
    app = FastAPI()
    handle_exception(app)
    for _prefix, router in ROUTERS:
        app.include_router(router)
    app.dependency_overrides[get_db] = _no_db
    app.state.redis = MagicMock(name='redis')
    return app


def _iter_dep_calls(dependant: Any) -> Iterator[Any]:
    for dep in dependant.dependencies:
        if dep.call is not None:
            yield dep.call
        yield from _iter_dep_calls(dep)


def _payload_routes(app: FastAPI) -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith('/payload/')]


def _route_perms(route: APIRoute) -> list[Any]:
    return [c.perm for c in _iter_dep_calls(route.dependant) if isinstance(c, CheckUserInterfaceAuth)]


def _login_as(app: FastAPI, permissions: list[str]) -> None:
    """把每个 PreAuth 实例替换为“已登录、具备给定权限”的假依赖。"""
    user = CurrentUserModel(permissions=permissions, roles=['common'], user=None)

    async def _fake_pre_auth() -> CurrentUserModel:
        RequestContext.set_current_exclude_patterns([])
        RequestContext.set_current_user(user)
        return user

    for route in _payload_routes(app):
        for call in _iter_dep_calls(route.dependant):
            if isinstance(call, PreAuth):
                app.dependency_overrides[call] = _fake_pre_auth


def _sample_path(path: str) -> str:
    return (
        path.replace('{family}', 'xl')
        .replace('{board}', 'rkdj')
        .replace('{order_id}', '1')
        .replace('{seq_id}', '1')
        .replace('{sequence_id}', '1')
        .replace('{id}', '1')
        .replace('{run_id}', '1')
    )


@pytest.fixture
def app() -> FastAPI:
    return _build_app()


@pytest.fixture
def admin_client(app: FastAPI) -> TestClient:
    _login_as(app, ['*:*:*'])
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. 路由清单
# ---------------------------------------------------------------------------


def test_all_payload_controllers_mounted_with_expected_prefix(app: FastAPI) -> None:
    for prefix, router in ROUTERS:
        assert router.prefix == prefix
        paths = [r.path for r in router.routes]
        assert paths, f'{prefix} 没有任何路由'
        assert all(p.startswith(prefix) for p in paths)
    routes = _payload_routes(app)
    assert len(routes) >= MIN_PAYLOAD_ROUTES
    # doc/04 中曾被标错的两个接口：/config 返回聚合页，/def 返回单表定义；不存在 /pages
    paths = {(m, r.path) for r in routes for m in r.methods}
    assert ('GET', '/payload/telemetry/config') in paths
    assert ('GET', '/payload/telemetry/def') in paths
    assert ('GET', '/payload/telemetry/pages') not in paths


def test_route_method_path_pairs_are_unique(app: FastAPI) -> None:
    pairs = [(m, r.path) for r in _payload_routes(app) for m in r.methods]
    dup = {p for p in pairs if pairs.count(p) > 1}
    assert not dup, f'重复注册的接口: {dup}'


# ---------------------------------------------------------------------------
# 2. 鉴权
# ---------------------------------------------------------------------------


def _route_cases() -> list[tuple[str, str]]:
    app = _build_app()
    return sorted({(sorted(r.methods)[0], r.path) for r in _payload_routes(app)})


@pytest.mark.parametrize(('method', 'path'), _route_cases())
def test_every_payload_route_requires_login(app: FastAPI, method: str, path: str) -> None:
    client = TestClient(app)
    resp = client.request(method, _sample_path(path))
    assert resp.status_code == HTTP_OK  # 若依统一返回 HTTP 200，业务码在 body
    body = resp.json()
    assert body['code'] == UNAUTHORIZED, body
    assert '登录' in body['msg']


def test_protected_routes_reject_user_without_permission(app: FastAPI) -> None:
    _login_as(app, ['system:user:list'])
    client = TestClient(app)
    checked = 0
    for route in _payload_routes(app):
        perms = _route_perms(route)
        if not perms:
            continue
        method = sorted(route.methods)[0]
        body = client.request(method, _sample_path(route.path)).json()
        # 权限依赖先于参数校验执行，缺权限一律 403
        assert body.get('code') == FORBIDDEN, (method, route.path, body)
        checked += 1
    assert checked >= MIN_PERM_CHECKED


def test_permission_codes_use_payload_namespace(app: FastAPI) -> None:
    perms: set[str] = set()
    for route in _payload_routes(app):
        for perm in _route_perms(route):
            perms.update([perm] if isinstance(perm, str) else perm)
    assert perms
    assert all(p.startswith('payload:') for p in perms), perms


# ---------------------------------------------------------------------------
# 3. 典型接口：真实配置（assets/config）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('family', ['biu', 'xl'])
def test_telecontrol_config_reads_real_json(admin_client: TestClient, family: str) -> None:
    body = admin_client.get('/payload/telecontrol/config', params={'family': family}).json()
    assert body['code'] == SUCCESS, body
    assert body['data']['family'] == family


def test_telecontrol_config_requires_family_param(admin_client: TestClient) -> None:
    resp = admin_client.get('/payload/telecontrol/config')
    assert resp.status_code == VALIDATION_ERROR


def test_telemetry_config_returns_aggregated_pages(admin_client: TestClient) -> None:
    body = admin_client.get('/payload/telemetry/config').json()
    assert body['code'] == SUCCESS, body
    assert body['data']


def test_device_parsers_and_assemblers_lists(admin_client: TestClient) -> None:
    parsers = admin_client.get('/payload/device/parsers').json()
    assemblers = admin_client.get('/payload/device/assemblers').json()
    assert parsers['code'] == SUCCESS and isinstance(parsers['data'], list) and parsers['data']
    assert assemblers['code'] == SUCCESS and isinstance(assemblers['data'], list) and assemblers['data']


def test_timeconv_epochs_api(admin_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from module_payload.service.payload_timeconv_service import PayloadTimeconvService

    fake = [
        {'id': 'none', 'label': 'NONE: 1970-01-01', 'epochUtcSec': 0, 'dateUtc': '1970-01-01'},
        {'id': 'biu', 'label': 'BIU: 2020-01-01', 'epochUtcSec': 1577836800, 'dateUtc': '2020-01-01'},
    ]
    monkeypatch.setattr(PayloadTimeconvService, 'list_epochs', lambda: fake)
    body = admin_client.get('/payload/device/timeconv/epochs').json()
    assert body['code'] == SUCCESS, body
    assert body['data'] == fake


# ---------------------------------------------------------------------------
# 4. 典型接口：服务层打桩，校验参数透传
# ---------------------------------------------------------------------------


def test_device_status_passes_device_id_and_redis(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = AsyncMock(return_value={'deviceId': 'can:0:0:1', 'state': 'open'})
    monkeypatch.setattr(PayloadDeviceService, 'get_device_status', fake)
    _login_as(app, ['*:*:*'])
    body = TestClient(app).get('/payload/device/status', params={'deviceId': 'can:0:0:1'}).json()
    assert body['code'] == SUCCESS
    assert body['data'] == {'deviceId': 'can:0:0:1', 'state': 'open'}
    fake.assert_awaited_once_with(app.state.redis, 'can:0:0:1')


def test_device_status_missing_device_id_is_422(admin_client: TestClient) -> None:
    assert admin_client.get('/payload/device/status').status_code == VALIDATION_ERROR


def test_lvds_signals_and_data(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(PayloadLvdsService, 'list_signals', MagicMock(return_value=[{'id': 's1'}]))
    data = AsyncMock(return_value={'points': [1, 2, 3]})
    monkeypatch.setattr(PayloadLvdsService, 'get_data', data)
    _login_as(app, ['payload:lvds:view'])
    client = TestClient(app)

    sig = client.get('/payload/lvds/signals').json()
    assert sig['code'] == SUCCESS
    assert sig['data'] == [{'id': 's1'}]
    PayloadLvdsService.list_signals.assert_called_once_with('7E9B')

    out = client.get('/payload/lvds/data', params={'signal': 's1', 'limit': 10}).json()
    assert out['code'] == SUCCESS
    assert out['data'] == {'points': [1, 2, 3]}
    data.assert_awaited_once_with(app.state.redis, 's1', 'lvds:demo', 10)


def test_lvds_data_rejects_non_int_limit(app: FastAPI) -> None:
    _login_as(app, ['payload:lvds:view'])
    resp = TestClient(app).get('/payload/lvds/data', params={'signal': 's1', 'limit': 'abc'})
    assert resp.status_code == VALIDATION_ERROR


def test_telemetry_def_passes_type_and_family(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = MagicMock(return_value={'row': []})
    monkeypatch.setattr(PayloadConfigService, 'get_telemetry_table_def', fake)
    _login_as(app, ['*:*:*'])
    body = TestClient(app).get('/payload/telemetry/def', params={'type': 'FF', 'family': 'biu'}).json()
    assert body['code'] == SUCCESS
    assert body['data'] == {'row': []}
    fake.assert_called_once_with('FF', reload=False, family='biu')
