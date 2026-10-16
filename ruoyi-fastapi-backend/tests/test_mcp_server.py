"""MCP 服务：挂载开关、工具清单、鉴权透传与只读代理。"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from types import SimpleNamespace
from typing import TYPE_CHECKING, Annotated, Any

import jwt
import pytest

pytest.importorskip('mcp')

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

import module_mcp
from config.env import JwtConfig, McpConfig, McpSettings
from module_mcp.auth import McpBearerMiddleware, bearer_is_accepted, request_path
from module_mcp.server import present_tool_result, strip_config_paths, telecontrol_index
from module_payload.protocol.protocol_catalog import bus_family_names, require_bus_family

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

_TOKEN = 'Bearer good-token'
_ACCEPT = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json'}


def _build_app(config_fault: BaseException | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        server = getattr(app.state, 'mcp_server', None)
        if server is None:
            yield
            return
        async with server.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)

    def _check(authorization: str | None) -> dict[str, Any] | None:
        if authorization != _TOKEN:
            return {'code': 401, 'msg': '用户未登录'}
        return None

    @app.get('/payload/device/version')
    async def version(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        return _check(authorization) or {'code': 200, 'msg': 'ok', 'data': {'version': '9.9.9'}}

    @app.get('/payload/telemetry/def')
    async def tm_def(
        type: str,  # noqa: A002
        family: str | None = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        return _check(authorization) or {'code': 200, 'data': {'type': type, 'family': family}}

    @app.get('/payload/sequence/list')
    async def seq_list(pageNum: int = 1, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:  # noqa: N803
        return _check(authorization) or {
            'code': 200,
            'msg': 'ok',
            'rows': [{'seqId': 1}],
            'total': 1,
            'pageNum': pageNum,
        }

    @app.get('/payload/telecontrol/config')
    async def tc_config(family: str, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        denied = _check(authorization)
        if denied:
            return denied
        require_bus_family(family)
        if config_fault is not None:
            raise config_fault
        return {
            'code': 200,
            'data': {
                'family': family,
                'page': [{'id': 1, 'name': '单帧', 'orderList': ['A1']}],
                'order': {'A1': {'id': 'A1', 'name': '使能', 'component': [{'title': '数据域'}]}},
            },
        }

    module_mcp.setup_mcp(app)
    return app


async def _accept_test_token(_app: object, authorization: str) -> bool:
    return authorization == _TOKEN


@pytest.fixture
def mcp_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(McpConfig, 'mcp_enabled', True)
    monkeypatch.setattr(McpConfig, 'mcp_allowed_hosts', '')
    monkeypatch.setattr('module_mcp.auth.bearer_is_accepted', _accept_test_token)
    yield


def _rpc(client: TestClient, method: str, params: dict[str, Any], *, auth: str | None = _TOKEN) -> dict[str, Any]:
    headers = dict(_ACCEPT)
    if auth:
        headers['Authorization'] = auth
    resp = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}, headers=headers)
    assert resp.status_code == HTTPStatus.OK, resp.text
    return resp.json()


def _init(client: TestClient, auth: str | None = _TOKEN) -> None:
    _rpc(
        client,
        'initialize',
        {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'pytest', 'version': '0'}},
        auth=auth,
    )


def _call(client: TestClient, name: str, arguments: dict[str, Any], auth: str | None = _TOKEN) -> dict[str, Any]:
    _init(client, auth)
    return _rpc(client, 'tools/call', {'name': name, 'arguments': arguments}, auth=auth)['result']


def _text(result: dict[str, Any]) -> str:
    return ''.join(c.get('text', '') for c in result.get('content') or [])


def test_enabled_is_the_default() -> None:
    assert McpSettings.model_fields['mcp_enabled'].default is True


def test_explicit_disable_does_not_mount(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(McpConfig, 'mcp_enabled', False)
    app = _build_app()
    assert not any(getattr(r, 'path', '') == '/mcp' for r in app.routes)
    assert getattr(app.state, 'mcp_server', None) is None


def test_tools_are_listed_and_read_only(mcp_on: None) -> None:
    with TestClient(_build_app()) as client:
        _init(client)
        tools = _rpc(client, 'tools/list', {})['result']['tools']
    names = {t['name'] for t in tools}
    assert {'payload_version', 'telemetry_table', 'sequence_list', 'payload_api_get', 'current_user', 'get_server_health'} <= names
    assert 'config_file_content' not in names
    for tool in tools:
        assert (tool.get('annotations') or {}).get('readOnlyHint') is True, tool['name']


def test_tool_forwards_authorization_and_unwraps_data(mcp_on: None) -> None:
    with TestClient(_build_app()) as client:
        result = _call(client, 'payload_version', {})
    assert not result.get('isError'), result
    assert '9.9.9' in _text(result)


def test_query_params_are_forwarded(mcp_on: None) -> None:
    with TestClient(_build_app()) as client:
        result = _call(client, 'telemetry_table_def', {'type': 'FF', 'family': 'biu'})
        page = _call(client, 'sequence_list', {'page_num': 2})
    assert not result.get('isError'), result
    assert '"FF"' in _text(result) and '"biu"' in _text(result)
    assert '"total": 1' in _text(page) and '"pageNum": 2' in _text(page)


def test_missing_token_is_rejected(mcp_on: None) -> None:
    with TestClient(_build_app()) as client:
        resp = client.post(
            '/mcp',
            json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
            headers=_ACCEPT,
        )
    assert resp.status_code == HTTPStatus.UNAUTHORIZED
    assert 'bearer' in resp.headers.get('www-authenticate', '').lower()


def test_invalid_token_is_unauthorized(mcp_on: None) -> None:
    with TestClient(_build_app()) as client:
        resp = client.post(
            '/mcp',
            json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}},
            headers={**_ACCEPT, 'Authorization': 'Bearer bad'},
        )
    assert resp.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.parametrize(
    'path',
    ['/system/user/list', '/payload/../system/user', 'http://evil/payload/x', '/getInfoExtra', '/healthcheck'],
)
def test_generic_get_rejects_paths_outside_whitelist(mcp_on: None, path: str) -> None:
    with TestClient(_build_app()) as client:
        result = _call(client, 'payload_api_get', {'path': path})
    assert result.get('isError') is True


def test_generic_get_allows_payload_path(mcp_on: None) -> None:
    with TestClient(_build_app()) as client:
        result = _call(client, 'payload_api_get', {'path': 'payload/device/version'})
    assert not result.get('isError'), result
    assert '9.9.9' in _text(result)


def test_list_result_is_one_object(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(McpConfig, 'mcp_max_result_chars', 10000)
    assert present_tool_result([]) == {'items': [], 'total': 0}
    assert present_tool_result([{'id': 1}])['total'] == 1


def test_truncation_drops_whole_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(McpConfig, 'mcp_max_result_chars', 180)
    result = present_tool_result([{'n': index, 'text': 'x' * 40} for index in range(10)])
    json.dumps(result)
    assert result['truncated'] is True
    assert result['returned'] < result['total']
    assert result['items']
    assert '减小 limit' in result['hint']


def test_oversized_object_is_not_a_json_fragment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(McpConfig, 'mcp_max_result_chars', 40)
    result = present_tool_result({'commands': 'x' * 200})
    json.dumps(result)
    assert result == {
        'truncated': True,
        'totalChars': len(json.dumps({'commands': 'x' * 200}, ensure_ascii=False)),
        'hint': result['hint'],
    }
    assert '半截' in result['hint']


def test_config_list_drops_server_path() -> None:
    rows = strip_config_paths([{'name': 'a.json', 'path': r'E:\secret\a.json', 'size': 3}])
    assert rows == [{'name': 'a.json', 'size': 3}]


def test_telecontrol_index_drops_command_parameters() -> None:
    slim = telecontrol_index(
        {
            'family': 'yj216',
            'datetime': 't',
            'page': [{'id': 1, 'name': '单帧', 'orderList': ['A1']}],
            'order': {'A1': {'id': 'A1', 'name': '使能', 'component': [{'title': '数据域'}]}},
        }
    )
    assert slim['orders'] == [{'id': 'A1', 'name': '使能'}]
    assert '数据域' not in json.dumps(slim, ensure_ascii=False)


def test_telecontrol_config_tool_returns_index(mcp_on: None) -> None:
    with TestClient(_build_app()) as client:
        _init(client)
        schema = next(tool for tool in _rpc(client, 'tools/list', {})['result']['tools'] if tool['name'] == 'telecontrol_config')
        family_schema = schema['inputSchema']['properties']['family']
        assert family_schema.get('enum') == list(bus_family_names())
        result = _call(client, 'telecontrol_config', {'family': 'yj216'})
        missing = _call(client, 'telecontrol_config', {'family': 'not-a-family'})
    assert not result.get('isError'), result
    text = _text(result)
    assert '使能' in text
    assert '数据域' not in text
    assert missing.get('isError') is True


def test_business_exception_text_reaches_the_agent(mcp_on: None) -> None:
    with TestClient(_build_app(ValueError('未知总线族: yj216'))) as client:
        result = _call(client, 'telecontrol_config', {'family': 'yj216'})
    assert result.get('isError') is True
    assert '未知总线族: yj216' in _text(result)


def test_internal_exception_hides_driver_text(mcp_on: None) -> None:
    with TestClient(_build_app(RuntimeError('password=secret'))) as client:
        result = _call(client, 'telecontrol_config', {'family': 'yj216'})
    assert result.get('isError') is True
    text = _text(result)
    assert '内部错误' in text
    assert 'secret' not in text


def test_server_health_keeps_failed_dependency(mcp_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _check(_redis: object) -> tuple[dict[str, str], int]:
        return {'status': 'error', 'redis': 'down'}, 503

    monkeypatch.setattr('module_admin.service.health_service.HealthService.check', _check)
    with TestClient(_build_app()) as client:
        result = _call(client, 'get_server_health', {})
    assert not result.get('isError'), result
    assert '"status": "error"' in _text(result)


def test_bearer_requires_live_redis_session() -> None:
    token = jwt.encode(
        {
            'user_id': 1,
            'session_id': 'sid',
            'exp': datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        JwtConfig.jwt_secret_key,
        algorithm=JwtConfig.jwt_algorithm,
    )

    class _Redis:
        async def get(self, key: str) -> str | None:
            if key == 'access_token:sid':
                return token
            return None

    app = SimpleNamespace(state=SimpleNamespace(redis=_Redis()))
    assert asyncio.run(bearer_is_accepted(app, f'Bearer {token}')) is True
    assert asyncio.run(bearer_is_accepted(app, 'Bearer not-a-jwt')) is False


def test_root_path_is_stripped_before_mcp_match() -> None:
    assert request_path({'path': '/dev-api/mcp', 'root_path': '/dev-api'}) == '/mcp'
    assert request_path({'path': '/mcp', 'root_path': '/dev-api'}) == '/mcp'


def test_prefixed_mcp_path_requires_bearer(mcp_on: None) -> None:
    captured: list[dict[str, Any]] = []

    async def _downstream(scope: dict[str, Any], receive: Any, send: Any) -> None:
        captured.append(scope)
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'ok'})

    middleware = McpBearerMiddleware(_downstream)

    async def _post(path: str) -> int:
        messages: list[dict[str, Any]] = []

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)

        await middleware(
            {'type': 'http', 'path': path, 'root_path': '/dev-api', 'method': 'POST', 'headers': []},
            _noop_receive,
            send,
        )
        return int(messages[0]['status'])

    assert asyncio.run(_post('/dev-api/mcp')) == HTTPStatus.UNAUTHORIZED
    assert captured == []


async def _noop_receive() -> dict[str, Any]:
    return {'type': 'http.request', 'body': b'', 'more_body': False}


def test_dns_rebinding_protection_rejects_unknown_host(mcp_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(McpConfig, 'mcp_allowed_hosts', '127.0.0.1:*,localhost:*')
    with TestClient(_build_app()) as client:  # TestClient Host 为 testserver
        resp = client.post(
            '/mcp',
            json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}},
            headers={**_ACCEPT, 'Authorization': _TOKEN},
        )
    assert resp.status_code in {400, 403, 421}
