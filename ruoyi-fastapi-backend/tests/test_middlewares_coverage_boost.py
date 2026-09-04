"""Raise coverage of middlewares modules toward 99%+ (defer transport_crypto)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from starlette.responses import PlainTextResponse, Response
from starlette.testclient import TestClient

from middlewares.api_response_header_middleware import (
    ApiResponseHeaderMiddleware,
    add_api_response_header_middleware,
)
from middlewares.context_middleware import (
    ContextCleanupMiddleware,
    add_context_cleanup_middleware,
)
from middlewares.cors_middleware import add_cors_middleware
from middlewares.demo_mode_middleware import DemoModeMiddleware, add_demo_mode_middleware
from middlewares.gzip_middleware import add_gzip_middleware
from middlewares.handle import handle_middleware
from middlewares.trace_middleware import TraceASGIMiddleware, TraceCtx, add_trace_middleware
from middlewares.trace_middleware.ctx import (
    CTX_REQUEST_ID,
    CTX_REQUEST_METHOD,
    CTX_REQUEST_PATH,
    CTX_SPAN_ID,
    CTX_TRACE_ID,
)
from middlewares.trace_middleware.span import Span, get_current_span


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_request(
    *,
    path: str = '/system/user',
    method: str = 'GET',
    base_url: str = 'http://testserver/',
) -> Request:
    from urllib.parse import urlsplit

    parts = urlsplit(base_url)
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0'},
        'http_version': '1.1',
        'method': method,
        'scheme': parts.scheme or 'http',
        'path': path,
        'raw_path': path.encode(),
        'query_string': b'',
        'headers': [],
        'client': ('127.0.0.1', 12345),
        'server': (parts.hostname or 'testserver', parts.port or 80),
        'root_path': '',
    }
    request = Request(scope)
    # Starlette derives base_url from scheme/server; override via scope if needed
    return request


def _app_with_middleware(middleware_cls: type) -> FastAPI:
    app = FastAPI()
    app.add_middleware(middleware_cls)

    @app.get('/ok')
    async def ok() -> dict[str, str]:
        return {'status': 'ok'}

    @app.post('/system/user')
    async def create_user() -> dict[str, str]:
        return {'status': 'created'}

    @app.get('/system/user')
    async def list_user() -> dict[str, str]:
        return {'status': 'list'}

    @app.post('/common/upload')
    async def common_upload() -> dict[str, str]:
        return {'status': 'upload'}

    @app.post('/other')
    async def other() -> dict[str, str]:
        return {'status': 'other'}

    return app


# ---------------------------------------------------------------------------
# api_response_header_middleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_response_header_updates_when_present() -> None:
    request = _make_request(path='/api/test')
    request.state.api_response_headers = {'X-Custom': 'yes', 'X-Trace': 'abc'}
    response = Response(content=b'ok', status_code=200)

    async def call_next(req: Request) -> Response:
        return response

    mw = ApiResponseHeaderMiddleware(app=MagicMock())
    result = await mw.dispatch(request, call_next)
    assert result.headers['X-Custom'] == 'yes'
    assert result.headers['X-Trace'] == 'abc'


@pytest.mark.asyncio
async def test_api_response_header_skips_when_absent() -> None:
    request = _make_request(path='/api/test')
    response = Response(content=b'ok', status_code=200)

    async def call_next(req: Request) -> Response:
        return response

    mw = ApiResponseHeaderMiddleware(app=MagicMock())
    result = await mw.dispatch(request, call_next)
    assert 'X-Custom' not in result.headers


def test_add_api_response_header_middleware() -> None:
    app = FastAPI()
    add_api_response_header_middleware(app)
    assert any(getattr(m, 'cls', None) is ApiResponseHeaderMiddleware for m in app.user_middleware)


def test_api_response_header_via_testclient() -> None:
    app = FastAPI()

    @app.get('/hdr')
    async def hdr(request: Request) -> dict[str, str]:
        request.state.api_response_headers = {'X-Api': 'header-value'}
        return {'ok': '1'}

    add_api_response_header_middleware(app)
    client = TestClient(app)
    r = client.get('/hdr')
    assert r.status_code == 200
    assert r.headers.get('X-Api') == 'header-value'


# ---------------------------------------------------------------------------
# context_middleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_cleanup_clears_after_request() -> None:
    from common.context import RequestContext

    RequestContext.set_current_user({'user_id': 1})
    request = _make_request()
    response = Response(content=b'ok')

    async def call_next(req: Request) -> Response:
        return response

    with patch('middlewares.context_middleware.RequestContext.clear_all') as clear_all:
        mw = ContextCleanupMiddleware(app=MagicMock())
        result = await mw.dispatch(request, call_next)
        clear_all.assert_called_once()
        assert result is response


def test_add_context_cleanup_middleware() -> None:
    app = FastAPI()

    @app.get('/')
    async def root() -> dict[str, str]:
        return {'ok': '1'}

    add_context_cleanup_middleware(app)
    client = TestClient(app)
    assert client.get('/').status_code == 200


# ---------------------------------------------------------------------------
# cors_middleware / gzip_middleware
# ---------------------------------------------------------------------------


def test_add_cors_middleware() -> None:
    app = FastAPI()

    @app.get('/')
    async def root() -> dict[str, str]:
        return {'ok': '1'}

    add_cors_middleware(app)
    client = TestClient(app)
    r = client.options(
        '/',
        headers={
            'Origin': 'http://example.com',
            'Access-Control-Request-Method': 'GET',
        },
    )
    assert r.status_code in (200, 204)
    assert 'access-control-allow-origin' in {k.lower() for k in r.headers.keys()}


def test_add_gzip_middleware() -> None:
    app = FastAPI()

    @app.get('/big')
    async def big() -> PlainTextResponse:
        return PlainTextResponse('x' * 2000)

    add_gzip_middleware(app)
    client = TestClient(app)
    r = client.get('/big', headers={'Accept-Encoding': 'gzip'})
    assert r.status_code == 200
    assert r.headers.get('content-encoding') == 'gzip'


# ---------------------------------------------------------------------------
# demo_mode_middleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_demo_mode_blocks_mutating_system_path() -> None:
    request = _make_request(path='/system/user', method='POST')
    call_next = AsyncMock()

    with (
        patch('middlewares.demo_mode_middleware.ClientIPUtil.get_client_ip', return_value='1.2.3.4'),
        patch('middlewares.demo_mode_middleware.logger') as logger,
        patch('middlewares.demo_mode_middleware.ResponseUtil.failure') as failure,
    ):
        failure.return_value = Response(content=b'blocked', status_code=200)
        mw = DemoModeMiddleware(app=MagicMock())
        result = await mw.dispatch(request, call_next)
        failure.assert_called_once_with(msg='演示模式，不允许操作！')
        logger.warning.assert_called_once()
        call_next.assert_not_called()
        assert result is failure.return_value


@pytest.mark.asyncio
async def test_demo_mode_allows_get_on_system_path() -> None:
    request = _make_request(path='/system/user', method='GET')
    response = Response(content=b'ok')
    call_next = AsyncMock(return_value=response)

    mw = DemoModeMiddleware(app=MagicMock())
    result = await mw.dispatch(request, call_next)
    call_next.assert_awaited_once()
    assert result is response


@pytest.mark.asyncio
async def test_demo_mode_blocks_common_register_and_create_table() -> None:
    mw = DemoModeMiddleware(app=MagicMock())
    call_next = AsyncMock()

    for path in ('/common/upload', '/register', '/tool/gen/createTable'):
        request = _make_request(path=path, method='GET')
        with (
            patch('middlewares.demo_mode_middleware.ClientIPUtil.get_client_ip', return_value='9.9.9.9'),
            patch('middlewares.demo_mode_middleware.logger'),
            patch(
                'middlewares.demo_mode_middleware.ResponseUtil.failure',
                return_value=Response(content=b'no', status_code=200),
            ) as failure,
        ):
            result = await mw.dispatch(request, call_next)
            failure.assert_called_once()
            assert result.body == b'no'

    call_next.assert_not_called()


@pytest.mark.asyncio
async def test_demo_mode_allows_unrelated_path() -> None:
    request = _make_request(path='/payload/telemetry', method='POST')
    response = Response(content=b'ok')
    call_next = AsyncMock(return_value=response)

    mw = DemoModeMiddleware(app=MagicMock())
    result = await mw.dispatch(request, call_next)
    call_next.assert_awaited_once()
    assert result is response


def test_demo_mode_via_testclient() -> None:
    app = _app_with_middleware(DemoModeMiddleware)
    client = TestClient(app)

    # GET allowed
    assert client.get('/system/user').status_code == 200

    # POST blocked
    with patch('middlewares.demo_mode_middleware.ClientIPUtil.get_client_ip', return_value='127.0.0.1'):
        r = client.post('/system/user')
    assert r.status_code == 200
    body = r.json()
    assert '演示模式' in body.get('msg', '') or '演示模式' in r.text

    # common blocked even for methods that would otherwise pass list check
    with patch('middlewares.demo_mode_middleware.ClientIPUtil.get_client_ip', return_value='127.0.0.1'):
        r2 = client.post('/common/upload')
    assert '演示模式' in r2.text

    # unrelated allowed
    assert client.post('/other').status_code == 200


def test_add_demo_mode_middleware() -> None:
    app = FastAPI()
    add_demo_mode_middleware(app)


# ---------------------------------------------------------------------------
# handle_middleware
# ---------------------------------------------------------------------------


def test_handle_middleware_without_demo() -> None:
    app = FastAPI()
    with (
        patch('middlewares.handle.AppConfig') as cfg,
        patch('middlewares.handle.add_context_cleanup_middleware') as c1,
        patch('middlewares.handle.add_cors_middleware') as c2,
        patch('middlewares.handle.add_gzip_middleware') as c3,
        patch('middlewares.handle.add_api_response_header_middleware') as c4,
        patch('middlewares.handle.add_trace_middleware') as c5,
        patch('middlewares.handle.add_demo_mode_middleware') as c6,
        patch('middlewares.handle.add_transport_crypto_middleware') as c7,
    ):
        cfg.app_demo_mode = False
        handle_middleware(app)
        c1.assert_called_once_with(app)
        c2.assert_called_once_with(app)
        c3.assert_called_once_with(app)
        c4.assert_called_once_with(app)
        c5.assert_called_once_with(app)
        c6.assert_not_called()
        c7.assert_called_once_with(app)


def test_handle_middleware_with_demo() -> None:
    app = FastAPI()
    with (
        patch('middlewares.handle.AppConfig') as cfg,
        patch('middlewares.handle.add_context_cleanup_middleware'),
        patch('middlewares.handle.add_cors_middleware'),
        patch('middlewares.handle.add_gzip_middleware'),
        patch('middlewares.handle.add_api_response_header_middleware'),
        patch('middlewares.handle.add_trace_middleware'),
        patch('middlewares.handle.add_demo_mode_middleware') as c6,
        patch('middlewares.handle.add_transport_crypto_middleware'),
    ):
        cfg.app_demo_mode = True
        handle_middleware(app)
        c6.assert_called_once_with(app)


# ---------------------------------------------------------------------------
# trace_middleware / ctx
# ---------------------------------------------------------------------------


def test_trace_ctx_setters_getters_and_clear() -> None:
    TraceCtx.clear()
    assert TraceCtx.get_trace_id() == ''
    assert TraceCtx.get_request_id() == ''
    assert TraceCtx.get_span_id() == ''
    assert TraceCtx.get_request_path() == ''
    assert TraceCtx.get_request_method() == ''

    tid = TraceCtx.set_trace_id()
    rid = TraceCtx.set_request_id()
    sid = TraceCtx.set_span_id()
    TraceCtx.set_request_path('/api/x')
    TraceCtx.set_request_method('POST')

    assert TraceCtx.get_trace_id() == tid == CTX_TRACE_ID.get()
    assert TraceCtx.get_request_id() == rid == CTX_REQUEST_ID.get()
    assert TraceCtx.get_span_id() == sid == CTX_SPAN_ID.get()
    assert TraceCtx.get_request_path() == '/api/x' == CTX_REQUEST_PATH.get()
    assert TraceCtx.get_request_method() == 'POST' == CTX_REQUEST_METHOD.get()
    assert len(tid) == 32

    TraceCtx.clear()
    assert TraceCtx.get_trace_id() == ''
    assert TraceCtx.get_request_id() == ''
    assert TraceCtx.get_span_id() == ''
    assert TraceCtx.get_request_path() == ''
    assert TraceCtx.get_request_method() == ''


# ---------------------------------------------------------------------------
# trace_middleware / span
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_span_request_before_sets_context() -> None:
    TraceCtx.clear()
    span = Span({'type': 'http', 'path': '/hello', 'method': 'GET'})
    await span.request_before()
    assert TraceCtx.get_trace_id()
    assert TraceCtx.get_request_id()
    assert TraceCtx.get_span_id()
    assert TraceCtx.get_request_path() == '/hello'
    assert TraceCtx.get_request_method() == 'GET'
    TraceCtx.clear()


@pytest.mark.asyncio
async def test_span_request_before_defaults_empty_path_method() -> None:
    TraceCtx.clear()
    span = Span({'type': 'http'})
    await span.request_before()
    assert TraceCtx.get_request_path() == ''
    assert TraceCtx.get_request_method() == ''
    TraceCtx.clear()


@pytest.mark.asyncio
async def test_span_request_after_passthrough() -> None:
    span = Span({'type': 'http'})
    msg = {'type': 'http.request', 'body': b'{}', 'more_body': False}
    assert await span.request_after(msg) is msg


@pytest.mark.asyncio
async def test_span_response_appends_ids_on_start() -> None:
    TraceCtx.clear()
    TraceCtx.set_trace_id()
    TraceCtx.set_request_id()
    TraceCtx.set_span_id()
    span = Span({'type': 'http'})
    message = {'type': 'http.response.start', 'status': 200, 'headers': []}
    out = await span.response(message)
    header_names = {h[0] for h in out['headers']}
    assert b'request-id' in header_names
    assert b'trace-id' in header_names
    assert b'span-id' in header_names
    TraceCtx.clear()


@pytest.mark.asyncio
async def test_span_response_body_unchanged() -> None:
    span = Span({'type': 'http'})
    message = {'type': 'http.response.body', 'body': b'hi'}
    out = await span.response(message)
    assert out is message
    assert 'headers' not in out


@pytest.mark.asyncio
async def test_get_current_span_context_manager() -> None:
    async with get_current_span({'type': 'http', 'path': '/'}) as span:
        assert isinstance(span, Span)
        assert span.scope['path'] == '/'


# ---------------------------------------------------------------------------
# trace_middleware / middle + add
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trace_asgi_middleware_non_http_passthrough() -> None:
    inner = AsyncMock()
    mw = TraceASGIMiddleware(inner)
    scope = {'type': 'websocket'}
    receive = AsyncMock()
    send = AsyncMock()
    await mw(scope, receive, send)
    inner.assert_awaited_once_with(scope, receive, send)


@pytest.mark.asyncio
async def test_trace_asgi_middleware_http_flow() -> None:
    TraceCtx.clear()
    messages_sent: list[dict] = []

    async def inner_app(scope, receive, send):  # type: ignore[no-untyped-def]
        # pull request body through wrapped receive
        msg = await receive()
        assert msg['type'] == 'http.request'
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'ok'})

    async def receive() -> dict:
        return {'type': 'http.request', 'body': b'{}', 'more_body': False}

    async def send(message: dict) -> None:
        messages_sent.append(message)

    mw = TraceASGIMiddleware(inner_app)
    scope = {'type': 'http', 'path': '/t', 'method': 'POST'}
    await mw(scope, receive, send)

    assert messages_sent[0]['type'] == 'http.response.start'
    header_names = {h[0] for h in messages_sent[0]['headers']}
    assert b'trace-id' in header_names
    assert b'request-id' in header_names
    assert b'span-id' in header_names
    # finally clears context
    assert TraceCtx.get_trace_id() == ''


@pytest.mark.asyncio
async def test_trace_asgi_middleware_clears_on_exception() -> None:
    TraceCtx.clear()

    async def boom(scope, receive, send):  # type: ignore[no-untyped-def]
        await receive()
        raise RuntimeError('boom')

    async def receive() -> dict:
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    mw = TraceASGIMiddleware(boom)
    with pytest.raises(RuntimeError, match='boom'):
        await mw({'type': 'http', 'path': '/', 'method': 'GET'}, receive, AsyncMock())
    assert TraceCtx.get_trace_id() == ''


def test_add_trace_middleware_and_http_client() -> None:
    app = FastAPI()

    @app.get('/traced')
    async def traced() -> dict[str, str]:
        return {'ok': '1'}

    add_trace_middleware(app)
    client = TestClient(app)
    r = client.get('/traced')
    assert r.status_code == 200
    assert 'trace-id' in r.headers
    assert 'request-id' in r.headers
    assert 'span-id' in r.headers


@pytest.mark.asyncio
async def test_my_receive_wrapper() -> None:
    span = MagicMock()
    span.request_before = AsyncMock()
    span.request_after = AsyncMock(side_effect=lambda m: m)

    async def receive() -> dict:
        return {'type': 'http.request', 'body': b'x', 'more_body': False}

    wrapped = await TraceASGIMiddleware.my_receive(receive, span)
    span.request_before.assert_awaited_once()
    msg = await wrapped()
    assert msg['body'] == b'x'
    span.request_after.assert_awaited_once()
