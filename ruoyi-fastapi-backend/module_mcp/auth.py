"""MCP 传输层 Bearer 校验。

不启用 OAuth 资源服务器：本系统没有授权端点。缺失或无效的 Bearer 在进入工具前返回 HTTP 401。
开发环境可以回落到 ``MCP_DEFAULT_TOKEN``；其它环境配置了该值则拒绝启动。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import jwt

from common.enums import RedisInitKeyConfig
from config.env import AppConfig, JwtConfig, McpConfig
from utils.log_util import logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastapi import FastAPI
    from starlette.types import ASGIApp, Receive, Scope, Send

_WWW_AUTHENTICATE = b'Bearer'


def assert_default_token_allowed() -> None:
    """非开发环境不允许共享兜底 Token。"""
    if McpConfig.mcp_default_token and AppConfig.app_env != 'dev':
        raise RuntimeError('MCP_DEFAULT_TOKEN 仅允许在开发环境使用')
    if McpConfig.mcp_default_token:
        logger.warning('MCP_DEFAULT_TOKEN 已配置：能访问 MCP 的客户端将共用该身份，仅限开发环境')


def authorization_from_headers(headers: Mapping[str, str] | None) -> str | None:
    """读取 Authorization；开发环境在客户端未带时回落到 MCP_DEFAULT_TOKEN。"""
    if headers:
        for key, value in headers.items():
            if key.lower() == 'authorization' and value:
                return value
    return _dev_default_authorization()


def _dev_default_authorization() -> str | None:
    if AppConfig.app_env != 'dev' or not McpConfig.mcp_default_token:
        return None
    token = McpConfig.mcp_default_token.strip()
    if token.lower().startswith('bearer '):
        return token
    return f'Bearer {token}'


def _raw_token(authorization: str) -> str:
    text = authorization.strip()
    if text.lower().startswith('bearer '):
        return text[7:].strip()
    return text


def _is_dev_default_token(authorization: str) -> bool:
    fallback = _dev_default_authorization()
    return bool(fallback) and _raw_token(authorization) == _raw_token(fallback)


async def bearer_is_accepted(app: FastAPI, authorization: str) -> bool:
    """校验 JWT 签名、过期时间，以及 Redis 里仍存在的登录会话。"""
    token = _raw_token(authorization)
    if not token:
        return False
    try:
        payload = jwt.decode(token, JwtConfig.jwt_secret_key, algorithms=[JwtConfig.jwt_algorithm])
    except jwt.InvalidTokenError:
        return False
    user_id = payload.get('user_id')
    session_id = payload.get('session_id')
    if not user_id:
        return False
    redis = getattr(getattr(app, 'state', None), 'redis', None)
    if redis is None:
        return False
    if AppConfig.app_same_time_login:
        if not session_id:
            return False
        key = f'{RedisInitKeyConfig.ACCESS_TOKEN.key}:{session_id}'
    else:
        key = f'{RedisInitKeyConfig.ACCESS_TOKEN.key}:{user_id}'
    stored = await redis.get(key)
    if isinstance(stored, bytes):
        stored = stored.decode()
    return stored == token


def _header_map(scope: Scope) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for key, value in scope.get('headers') or []:
        mapped[key.decode('latin-1')] = value.decode('latin-1')
    return mapped


def _set_authorization(scope: Scope, authorization: str) -> None:
    headers = [(key, value) for key, value in scope.get('headers') or [] if key.lower() != b'authorization']
    headers.append((b'authorization', authorization.encode('latin-1')))
    scope['headers'] = headers


def _is_mcp_path(path: str) -> bool:
    base = (McpConfig.mcp_path or '/mcp').rstrip('/') or '/mcp'
    return path == base or path.startswith(f'{base}/')


class McpBearerMiddleware:
    """对 /mcp 要求有效 Bearer。OPTIONS 留给 CORS 预检。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get('type') != 'http' or not McpConfig.mcp_enabled or not _is_mcp_path(scope.get('path') or ''):
            await self.app(scope, receive, send)
            return
        if scope.get('method') == 'OPTIONS':
            await self.app(scope, receive, send)
            return
        authorization = authorization_from_headers(_header_map(scope))
        if not authorization:
            await _send_unauthorized(send)
            return
        app: Any = scope.get('app')
        if not _is_dev_default_token(authorization) and not await bearer_is_accepted(app, authorization):
            await _send_unauthorized(send)
            return
        _set_authorization(scope, authorization)
        await self.app(scope, receive, send)


async def _send_unauthorized(send: Send) -> None:
    body = b'{"code":401,"msg":"Authentication required"}'
    await send(
        {
            'type': 'http.response.start',
            'status': 401,
            'headers': [
                (b'content-type', b'application/json'),
                (b'www-authenticate', _WWW_AUTHENTICATE),
                (b'content-length', str(len(body)).encode('ascii')),
            ],
        }
    )
    await send({'type': 'http.response.body', 'body': body})
