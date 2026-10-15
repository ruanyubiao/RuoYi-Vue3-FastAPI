"""MCP 服务：挂载开关、工具清单、鉴权透传与只读代理。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import TYPE_CHECKING, Annotated, Any

import pytest

pytest.importorskip('mcp')

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

import module_mcp
from config.env import McpConfig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

_TOKEN = 'Bearer good-token'
_ACCEPT = {'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json'}


def _build_app() -> FastAPI:
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

    module_mcp.setup_mcp(app)
    return app


@pytest.fixture
def mcp_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(McpConfig, 'mcp_enabled', True)
    monkeypatch.setattr(McpConfig, 'mcp_allowed_hosts', '')
    monkeypatch.setattr(McpConfig, 'mcp_default_token', '')
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


def test_disabled_by_default_does_not_mount(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(McpConfig, 'mcp_enabled', False)
    app = _build_app()
    assert not any(getattr(r, 'path', '') == '/mcp' for r in app.routes)
    assert getattr(app.state, 'mcp_server', None) is None


def test_tools_are_listed_and_read_only(mcp_on: None) -> None:
    with TestClient(_build_app()) as client:
        _init(client)
        tools = _rpc(client, 'tools/list', {})['result']['tools']
    names = {t['name'] for t in tools}
    assert {'payload_version', 'telemetry_table', 'sequence_list', 'payload_api_get', 'current_user'} <= names
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
        result = _call(client, 'payload_version', {}, auth=None)
    assert result.get('isError') is True
    assert 'Authorization' in _text(result)


def test_backend_auth_failure_is_reported(mcp_on: None) -> None:
    with TestClient(_build_app()) as client:
        result = _call(client, 'payload_version', {}, auth='Bearer bad')
    assert result.get('isError') is True
    assert '用户未登录' in _text(result)


def test_default_token_fallback(mcp_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(McpConfig, 'mcp_default_token', 'good-token')
    with TestClient(_build_app()) as client:
        result = _call(client, 'payload_version', {}, auth=None)
    assert not result.get('isError'), result


@pytest.mark.parametrize('path', ['/system/user/list', '/payload/../system/user', 'http://evil/payload/x'])
def test_generic_get_rejects_paths_outside_whitelist(mcp_on: None, path: str) -> None:
    with TestClient(_build_app()) as client:
        result = _call(client, 'payload_api_get', {'path': path})
    assert result.get('isError') is True


def test_generic_get_allows_payload_path(mcp_on: None) -> None:
    with TestClient(_build_app()) as client:
        result = _call(client, 'payload_api_get', {'path': 'payload/device/version'})
    assert not result.get('isError'), result
    assert '9.9.9' in _text(result)


def test_dns_rebinding_protection_rejects_unknown_host(mcp_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(McpConfig, 'mcp_allowed_hosts', '127.0.0.1:*,localhost:*')
    with TestClient(_build_app()) as client:  # TestClient Host 为 testserver
        resp = client.post(
            '/mcp',
            json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}},
            headers={**_ACCEPT, 'Authorization': _TOKEN},
        )
    assert resp.status_code in {400, 403, 421}
