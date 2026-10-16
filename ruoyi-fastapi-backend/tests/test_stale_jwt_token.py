"""JWT 密钥更换后的旧 token：退出登录返回成功、在线用户列表跳过无效 token。"""

from __future__ import annotations

import inspect
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt

from config.env import JwtConfig
from module_admin.controller.login_controller import logout
from module_admin.entity.vo.online_vo import OnlineQueryModel
from module_admin.service.login_service import LoginService
from module_admin.service.online_service import OnlineService

_logout = inspect.unwrap(logout)
HTTP_OK = 200


def _token(secret: str, **extra: object) -> str:
    payload = {
        'user_id': '1',
        'user_name': 'admin',
        'dept_name': 'd',
        'session_id': 's1',
        'login_info': {'ipaddr': '1.1.1.1', 'loginLocation': 'x', 'browser': 'b', 'os': 'os', 'loginTime': 't'},
        'exp': int(time.time()) + 3600,
    }
    payload.update(extra)
    return jwt.encode(payload, secret, algorithm=JwtConfig.jwt_algorithm)


def _request(redis: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(redis=redis)))


def _body(resp: object) -> dict:
    return json.loads(resp.body)


async def test_logout_invalid_signature_token_returns_success() -> None:
    bad = _token('a-different-jwt-secret-key-used-before-rotation')
    with patch.object(LoginService, 'logout_services', new=AsyncMock()) as svc:
        resp = await _logout(_request(), bad)
    svc.assert_not_awaited()
    assert resp.status_code == HTTP_OK
    assert _body(resp)['code'] == HTTP_OK
    assert _body(resp)['msg'] == '退出成功'


async def test_logout_garbage_or_missing_token_returns_success() -> None:
    with patch.object(LoginService, 'logout_services', new=AsyncMock()) as svc:
        for tok in ('not-a-jwt', None, ''):
            resp = await _logout(_request(), tok)
            assert _body(resp)['msg'] == '退出成功'
    svc.assert_not_awaited()


async def test_logout_valid_expired_token_still_logs_out() -> None:
    expired = _token(JwtConfig.jwt_secret_key, exp=int(time.time()) - 60)
    with (
        patch.object(LoginService, 'logout_services', new=AsyncMock()) as svc,
        patch('module_admin.controller.login_controller.AppConfig.app_same_time_login', True),
    ):
        resp = await _logout(_request(), expired)
    svc.assert_awaited_once()
    assert svc.await_args.args[1] == 's1'
    assert _body(resp)['msg'] == '退出成功'


async def test_online_list_skips_and_deletes_undecodable_tokens() -> None:
    good = _token(JwtConfig.jwt_secret_key)
    store = {
        'access_token:s1': good,
        'access_token:old': _token('a-different-jwt-secret-key-used-before-rotation', session_id='old'),
        'access_token:junk': 'not-a-jwt',
        'access_token:gone': None,
    }
    redis = SimpleNamespace(
        keys=AsyncMock(return_value=list(store)),
        get=AsyncMock(side_effect=lambda k: store[k]),
        delete=AsyncMock(),
    )
    with patch('module_admin.service.online_service.AppConfig.app_same_time_login', True):
        rows = await OnlineService.get_online_list_services(_request(redis), OnlineQueryModel())
    assert [r['tokenId'] for r in rows] == ['s1']
    assert sorted(c.args[0] for c in redis.delete.await_args_list) == [
        'access_token:gone',
        'access_token:junk',
        'access_token:old',
    ]
