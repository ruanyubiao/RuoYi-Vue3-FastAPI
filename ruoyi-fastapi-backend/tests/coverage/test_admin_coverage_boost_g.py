"""Raise module_admin coverage: login service/dao + RouterUtil."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from common.constant import CommonConstant, MenuConstant
from common.vo import CrudResponseModel
from exceptions.exception import AuthException, LoginException, ServiceException
from fastapi import Request
from module_admin.dao.login_dao import login_by_account
from module_admin.entity.vo.login_vo import MenuTreeModel, UserLogin, UserRegister
from module_admin.entity.vo.user_vo import ResetUserModel
from module_admin.service.login_service import (
    CustomOAuth2PasswordRequestForm,
    LoginService,
    RouterUtil,
)
from config.env import JwtConfig


@contextmanager
def expect_login_error(substr: str):
    with pytest.raises(LoginException) as ei:
        yield
    assert substr in (ei.value.message or '')


@contextmanager
def expect_auth_error(substr: str):
    with pytest.raises(AuthException) as ei:
        yield
    assert substr in (ei.value.message or '')


@contextmanager
def expect_service_error(substr: str):
    with pytest.raises(ServiceException) as ei:
        yield
    assert substr in (ei.value.message or '')


def _db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock()
    return db


def _request_with_redis(redis=None, *, referer: str | None = None, client_ip: str = '127.0.0.1') -> Request:
    redis = redis if redis is not None else AsyncMock()
    headers = []
    if referer:
        headers.append((b'referer', referer.encode()))
    app = SimpleNamespace(state=SimpleNamespace(redis=redis))
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0'},
        'http_version': '1.1',
        'method': 'GET',
        'scheme': 'http',
        'path': '/',
        'raw_path': b'/',
        'query_string': b'',
        'headers': headers,
        'client': (client_ip, 1),
        'server': ('test', 80),
        'root_path': '',
        'app': app,
    }
    return Request(scope)


def _menu(
    *,
    menu_id: int,
    parent_id: int = 0,
    menu_type: str = MenuConstant.TYPE_DIR,
    path: str = 'system',
    component: str | None = None,
    is_frame: int = MenuConstant.NO_FRAME,
    visible: str = '0',
    is_cache: int = 0,
    route_name: str = '',
    order_num: int = 1,
    query: str | None = None,
    icon: str = '#',
    menu_name: str = '菜单',
) -> MenuTreeModel:
    return MenuTreeModel(
        menuId=menu_id,
        parentId=parent_id,
        menuName=menu_name,
        menuType=menu_type,
        path=path,
        component=component,
        isFrame=is_frame,
        visible=visible,
        isCache=is_cache,
        routeName=route_name,
        orderNum=order_num,
        query=query,
        icon=icon,
    )


# ---------------------------------------------------------------------------
# CustomOAuth2 form + login_dao
# ---------------------------------------------------------------------------


def test_custom_oauth2_form_fields() -> None:
    # Bypass FastAPI Form defaults; exercise CustomOAuth2PasswordRequestForm.__init__ body.
    with patch('module_admin.service.login_service.OAuth2PasswordRequestForm.__init__', return_value=None):
        form = CustomOAuth2PasswordRequestForm.__new__(CustomOAuth2PasswordRequestForm)
        CustomOAuth2PasswordRequestForm.__init__(
            form,
            grant_type='password',
            username='u',
            password='p',
            scope='',
            client_id=None,
            client_secret=None,
            code='1',
            uuid='sid',
            login_info={'browser': 'x'},
        )
        assert form.code == '1' and form.uuid == 'sid' and form.login_info == {'browser': 'x'}


@pytest.mark.asyncio
async def test_login_by_account_dao() -> None:
    db = _db()
    row = (SimpleNamespace(user_id=1), SimpleNamespace(dept_id=1))
    result = MagicMock()
    result.first.return_value = row
    db.execute = AsyncMock(return_value=result)
    assert await login_by_account(db, 'admin') == row


# ---------------------------------------------------------------------------
# authenticate / captcha / token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_user_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db()
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    request = _request_with_redis(redis)

    # black IP
    redis.get = AsyncMock(return_value='10.0.0.1,127.0.0.1')
    with patch('module_admin.service.login_service.ClientIPUtil.get_client_ip', return_value='127.0.0.1'):
        with expect_login_error('禁止登录'):
            await LoginService.authenticate_user(request, db, UserLogin(userName='u', password='p', captchaEnabled=False))

    # account lock
    redis.get = AsyncMock(side_effect=lambda k: 'u' if 'account' in k.lower() or 'lock' in k.lower() or 'ACCOUNT' in k or 'account_lock' in k or 'lock' in str(k) else None)

    async def get_lock(key):
        if 'account' in key.lower() or 'lock' in key.lower() or key.endswith(':u'):
            # ACCOUNT_LOCK key
            from common.enums import RedisInitKeyConfig

            if key.startswith(RedisInitKeyConfig.ACCOUNT_LOCK.key):
                return 'u'
        return None

    redis.get = get_lock
    request = _request_with_redis(redis)
    with patch('module_admin.service.login_service.ClientIPUtil.get_client_ip', return_value='1.1.1.1'):
        with expect_login_error('锁定'):
            await LoginService.authenticate_user(request, db, UserLogin(userName='u', password='p', captchaEnabled=False))

    # captcha paths
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    request = _request_with_redis(redis)
    with (
        patch('module_admin.service.login_service.ClientIPUtil.get_client_ip', return_value='1.1.1.1'),
        patch('module_admin.service.login_service.login_by_account', new=AsyncMock(return_value=None)),
    ):
        with expect_login_error('验证码已失效'):
            await LoginService.authenticate_user(
                request, db, UserLogin(userName='u', password='p', captchaEnabled=True, code='1', uuid='x')
            )

    redis.get = AsyncMock(side_effect=lambda k: '99' if 'captcha' in k.lower() or 'CAPTCHA' in k or 'codes' in k.lower() else None)

    async def captcha_get(key):
        from common.enums import RedisInitKeyConfig

        if key.startswith(RedisInitKeyConfig.ACCOUNT_LOCK.key):
            return None
        if key.startswith(RedisInitKeyConfig.SYS_CONFIG.key):
            return None
        if key.startswith(RedisInitKeyConfig.CAPTCHA_CODES.key):
            return '99'
        return None

    redis.get = captcha_get
    request = _request_with_redis(redis)
    with patch('module_admin.service.login_service.ClientIPUtil.get_client_ip', return_value='1.1.1.1'):
        with expect_login_error('验证码错误'):
            await LoginService.authenticate_user(
                request, db, UserLogin(userName='u', password='p', captchaEnabled=True, code='1', uuid='x')
            )

    # swagger/redoc skip captcha in dev
    monkeypatch.setattr('module_admin.service.login_service.AppConfig.app_env', 'dev')
    redis.get = AsyncMock(return_value=None)
    request = _request_with_redis(redis, referer='http://localhost/docs')
    user_row = (SimpleNamespace(password='hash', status='0', user_name='u'), SimpleNamespace(dept_id=1))
    with (
        patch('module_admin.service.login_service.ClientIPUtil.get_client_ip', return_value='1.1.1.1'),
        patch('module_admin.service.login_service.login_by_account', new=AsyncMock(return_value=user_row)),
        patch('module_admin.service.login_service.PwdUtil.verify_password', return_value=True),
    ):
        assert await LoginService.authenticate_user(
            request, db, UserLogin(userName='u', password='p', captchaEnabled=True)
        )

    request = _request_with_redis(redis, referer='http://localhost/redoc')
    with (
        patch('module_admin.service.login_service.ClientIPUtil.get_client_ip', return_value='1.1.1.1'),
        patch('module_admin.service.login_service.login_by_account', new=AsyncMock(return_value=user_row)),
        patch('module_admin.service.login_service.PwdUtil.verify_password', return_value=True),
    ):
        await LoginService.authenticate_user(request, db, UserLogin(userName='u', password='p', captchaEnabled=True))

    # user not found
    request = _request_with_redis(redis)
    with (
        patch('module_admin.service.login_service.ClientIPUtil.get_client_ip', return_value='1.1.1.1'),
        patch('module_admin.service.login_service.login_by_account', new=AsyncMock(return_value=None)),
    ):
        with expect_login_error('不存在'):
            await LoginService.authenticate_user(request, db, UserLogin(userName='u', password='p', captchaEnabled=False))

    # wrong password + lock after too many
    async def pwd_err_get(key):
        from common.enums import RedisInitKeyConfig

        if key.startswith(RedisInitKeyConfig.ACCOUNT_LOCK.key):
            return None
        if key.startswith(RedisInitKeyConfig.PASSWORD_ERROR_COUNT.key):
            return CommonConstant.PASSWORD_ERROR_COUNT
        return None

    redis.get = pwd_err_get
    request = _request_with_redis(redis)
    with (
        patch('module_admin.service.login_service.ClientIPUtil.get_client_ip', return_value='1.1.1.1'),
        patch('module_admin.service.login_service.login_by_account', new=AsyncMock(return_value=user_row)),
        patch('module_admin.service.login_service.PwdUtil.verify_password', return_value=False),
    ):
        with expect_login_error('锁定'):
            await LoginService.authenticate_user(request, db, UserLogin(userName='u', password='bad', captchaEnabled=False))

    async def pwd_err_get2(key):
        from common.enums import RedisInitKeyConfig

        if key.startswith(RedisInitKeyConfig.ACCOUNT_LOCK.key):
            return None
        if key.startswith(RedisInitKeyConfig.PASSWORD_ERROR_COUNT.key):
            return 1
        return None

    redis.get = pwd_err_get2
    request = _request_with_redis(redis)
    with (
        patch('module_admin.service.login_service.ClientIPUtil.get_client_ip', return_value='1.1.1.1'),
        patch('module_admin.service.login_service.login_by_account', new=AsyncMock(return_value=user_row)),
        patch('module_admin.service.login_service.PwdUtil.verify_password', return_value=False),
    ):
        with expect_login_error('密码错误'):
            await LoginService.authenticate_user(request, db, UserLogin(userName='u', password='bad', captchaEnabled=False))

    # disabled user
    disabled = (SimpleNamespace(password='hash', status='1', user_name='u'), SimpleNamespace(dept_id=1))
    redis.get = AsyncMock(return_value=None)
    request = _request_with_redis(redis)
    with (
        patch('module_admin.service.login_service.ClientIPUtil.get_client_ip', return_value='1.1.1.1'),
        patch('module_admin.service.login_service.login_by_account', new=AsyncMock(return_value=disabled)),
        patch('module_admin.service.login_service.PwdUtil.verify_password', return_value=True),
    ):
        with expect_login_error('停用'):
            await LoginService.authenticate_user(request, db, UserLogin(userName='u', password='p', captchaEnabled=False))

    # success
    with (
        patch('module_admin.service.login_service.ClientIPUtil.get_client_ip', return_value='1.1.1.1'),
        patch('module_admin.service.login_service.login_by_account', new=AsyncMock(return_value=user_row)),
        patch('module_admin.service.login_service.PwdUtil.verify_password', return_value=True),
    ):
        assert await LoginService.authenticate_user(
            request, db, UserLogin(userName='u', password='p', captchaEnabled=False)
        )


@pytest.mark.asyncio
async def test_create_access_token() -> None:
    token = await LoginService.create_access_token({'user_id': 1}, expires_delta=timedelta(minutes=1))
    assert isinstance(token, str) and token
    token2 = await LoginService.create_access_token({'user_id': 1})
    assert token2


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_user_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db()
    redis = AsyncMock()
    request = _request_with_redis(redis)

    with expect_auth_error('失效'):
        await LoginService.get_current_user(request, 'not-a-jwt', db)

    payload = {'user_id': None, 'session_id': 's1'}
    bad = jwt.encode(payload, JwtConfig.jwt_secret_key, algorithm=JwtConfig.jwt_algorithm)
    with expect_auth_error('不合法'):
        await LoginService.get_current_user(request, bad, db)

    good_payload = {'user_id': '2', 'session_id': 's1'}
    token = jwt.encode(good_payload, JwtConfig.jwt_secret_key, algorithm=JwtConfig.jwt_algorithm)

    with patch(
        'module_admin.service.login_service.UserDao.get_user_by_id',
        new=AsyncMock(return_value={'user_basic_info': None}),
    ):
        with expect_auth_error('不合法'):
            await LoginService.get_current_user(request, f'Bearer {token}', db)

    def _xform(x):
        if isinstance(x, list):
            return [{'roleId': getattr(i, 'role_id', 1), 'roleKey': getattr(i, 'role_key', 'admin')} for i in x]
        if hasattr(x, 'user_id'):
            return {'userId': x.user_id, 'userName': getattr(x, 'user_name', 'u'), 'nickName': 'n'}
        if hasattr(x, 'dept_id'):
            return {'deptId': x.dept_id}
        return {}

    basic = SimpleNamespace(user_id=2, user_name='u', nick_name='n', pwd_update_date=None)
    query_user = {
        'user_basic_info': basic,
        'user_dept_info': SimpleNamespace(dept_id=1, dept_name='d'),
        'user_role_info': [SimpleNamespace(role_id=1, role_key='admin')],
        'user_post_info': [SimpleNamespace(post_id=1)],
        'user_menu_info': [SimpleNamespace(perms='a:b:c')],
    }

    async def redis_get_token(key):
        from common.enums import RedisInitKeyConfig

        if key.startswith(RedisInitKeyConfig.ACCESS_TOKEN.key):
            return token
        if 'initPasswordModify' in key:
            return '1'
        if 'passwordValidateDays' in key:
            return '0'
        return None

    redis.get = redis_get_token
    redis.set = AsyncMock()
    monkeypatch.setattr('module_admin.service.login_service.AppConfig.app_same_time_login', True)
    with (
        patch('module_admin.service.login_service.UserDao.get_user_by_id', new=AsyncMock(return_value=query_user)),
        patch('module_admin.service.login_service.CamelCaseUtil.transform_result', side_effect=_xform),
    ):
        user = await LoginService.get_current_user(request, token, db)
        assert user.permissions == ['*:*:*']

    query_user2 = {
        'user_basic_info': SimpleNamespace(
            user_id=3, user_name='u', nick_name='n', pwd_update_date=datetime.now() - timedelta(days=100)
        ),
        'user_dept_info': SimpleNamespace(dept_id=1, dept_name='d'),
        'user_role_info': [SimpleNamespace(role_id=2, role_key='common')],
        'user_post_info': [],
        'user_menu_info': [SimpleNamespace(perms='x:y:z')],
    }
    token3 = jwt.encode({'user_id': '3', 'session_id': 's2'}, JwtConfig.jwt_secret_key, algorithm=JwtConfig.jwt_algorithm)

    async def redis_get3(key):
        from common.enums import RedisInitKeyConfig

        if key.startswith(RedisInitKeyConfig.ACCESS_TOKEN.key):
            return token3
        if 'initPasswordModify' in key:
            return '0'
        if 'passwordValidateDays' in key:
            return '30'
        return None

    redis.get = redis_get3
    monkeypatch.setattr('module_admin.service.login_service.AppConfig.app_same_time_login', False)
    with (
        patch('module_admin.service.login_service.UserDao.get_user_by_id', new=AsyncMock(return_value=query_user2)),
        patch('module_admin.service.login_service.CamelCaseUtil.transform_result', side_effect=_xform),
    ):
        user = await LoginService.get_current_user(request, token3, db)
        assert 'x:y:z' in user.permissions
        assert user.is_password_expired is True

    redis.get = AsyncMock(return_value='other')
    with patch('module_admin.service.login_service.UserDao.get_user_by_id', new=AsyncMock(return_value=query_user)):
        with expect_auth_error('失效'):
            await LoginService.get_current_user(request, token, db)

    async def cfg_get(key):
        if 'initPasswordModify' in key:
            return '1'
        if 'passwordValidateDays' in key:
            return '0'
        return None

    redis.get = cfg_get
    assert await LoginService._LoginService__init_password_is_modify(request, None) is True
    assert await LoginService._LoginService__password_is_expired(request, None) is False

    async def cfg_get2(key):
        if 'passwordValidateDays' in key:
            return '10'
        return None

    redis.get = cfg_get2
    assert await LoginService._LoginService__password_is_expired(request, None) is True
    assert await LoginService._LoginService__password_is_expired(request, datetime.now()) is False


# ---------------------------------------------------------------------------
# routers / register / sms / forget / logout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_routers_register_sms_forget_logout(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db()
    menus = [
        SimpleNamespace(
            menu_id=1,
            parent_id=0,
            menu_type=MenuConstant.TYPE_DIR,
            order_num=1,
            menu_name='系统',
            path='system',
            component=None,
            query=None,
            icon='#',
            is_cache=0,
            is_frame=MenuConstant.NO_FRAME,
            visible='0',
            route_name='',
            status='0',
        ),
        SimpleNamespace(
            menu_id=2,
            parent_id=1,
            menu_type=MenuConstant.TYPE_MENU,
            order_num=1,
            menu_name='用户',
            path='user',
            component='system/user/index',
            query=None,
            icon='#',
            is_cache=0,
            is_frame=MenuConstant.NO_FRAME,
            visible='0',
            route_name='',
            status='0',
        ),
        SimpleNamespace(
            menu_id=3,
            parent_id=0,
            menu_type=MenuConstant.TYPE_MENU,
            order_num=2,
            menu_name='外链',
            path='https://example.com',
            component=None,
            query=None,
            icon='#',
            is_cache=0,
            is_frame=MenuConstant.NO_FRAME,
            visible='0',
            route_name='',
            status='0',
        ),
        SimpleNamespace(
            menu_id=4,
            parent_id=0,
            menu_type=MenuConstant.TYPE_MENU,
            order_num=3,
            menu_name='帧菜单',
            path='frame',
            component='x',
            query=None,
            icon='#',
            is_cache=1,
            is_frame=MenuConstant.NO_FRAME,
            visible='1',
            route_name='Frame',
            status='0',
        ),
    ]
    def _menu_xform(obj):
        if hasattr(obj, 'menu_id'):
            return {
                'menuId': obj.menu_id,
                'parentId': obj.parent_id,
                'menuName': obj.menu_name,
                'menuType': obj.menu_type,
                'path': obj.path,
                'component': obj.component,
                'query': obj.query,
                'icon': obj.icon,
                'isCache': obj.is_cache,
                'isFrame': obj.is_frame,
                'visible': obj.visible,
                'routeName': obj.route_name,
                'orderNum': obj.order_num,
            }
        return obj

    with (
        patch(
            'module_admin.service.login_service.UserDao.get_user_by_id',
            new=AsyncMock(return_value={'user_menu_info': menus}),
        ),
        patch('module_admin.service.login_service.CamelCaseUtil.transform_result', side_effect=_menu_xform),
    ):
        routers = await LoginService.get_current_user_routers(1, db)
        assert isinstance(routers, list) and routers

    redis = AsyncMock()
    request = _request_with_redis(redis)

    with expect_service_error('不一致'):
        await LoginService.register_user_services(
            request, db, UserRegister(username='u', password='a', confirmPassword='b')
        )

    async def reg_get(key):
        if 'registerUser' in key:
            return 'false'
        return None

    redis.get = reg_get
    with expect_service_error('关闭'):
        await LoginService.register_user_services(
            request, db, UserRegister(username='u', password='a', confirmPassword='a')
        )

    async def reg_get2(key):
        if 'registerUser' in key:
            return 'true'
        if 'captchaEnabled' in key:
            return 'true'
        return None

    redis.get = reg_get2
    with expect_service_error('验证码已失效'):
        await LoginService.register_user_services(
            request, db, UserRegister(username='u', password='a', confirmPassword='a', code='1', uuid='x')
        )

    async def reg_get3(key):
        from common.enums import RedisInitKeyConfig

        if 'registerUser' in key:
            return 'true'
        if 'captchaEnabled' in key:
            return 'true'
        if key.startswith(RedisInitKeyConfig.CAPTCHA_CODES.key):
            return '99'
        return None

    redis.get = reg_get3
    with expect_service_error('验证码错误'):
        await LoginService.register_user_services(
            request, db, UserRegister(username='u', password='a', confirmPassword='a', code='1', uuid='x')
        )

    async def reg_ok(key):
        if 'registerUser' in key:
            return 'true'
        if 'captchaEnabled' in key:
            return 'false'
        return None

    redis.get = reg_ok
    with (
        patch(
            'module_admin.service.login_service.UserService.add_user_services',
            new=AsyncMock(return_value=CrudResponseModel(is_success=True, message='ok')),
        ),
        patch('module_admin.service.login_service.PwdUtil.get_password_hash', return_value='h'),
    ):
        assert (
            await LoginService.register_user_services(
                request, db, UserRegister(username='u', password='a', confirmPassword='a')
            )
        ).is_success

    # sms
    redis.get = AsyncMock(return_value='123456')
    sms = await LoginService.get_sms_code_services(request, db, ResetUserModel(userName='u', sessionId='s'))
    assert sms.is_success is False

    redis.get = AsyncMock(return_value=None)
    with patch('module_admin.service.login_service.UserDao.get_user_by_name', new=AsyncMock(return_value=None)):
        sms = await LoginService.get_sms_code_services(request, db, ResetUserModel(userName='u', sessionId='s'))
        assert sms.message == '用户不存在'

    redis.set = AsyncMock()
    with (
        patch(
            'module_admin.service.login_service.UserDao.get_user_by_name',
            new=AsyncMock(return_value=SimpleNamespace(user_id=1)),
        ),
        patch('module_admin.service.login_service.message_service'),
    ):
        sms = await LoginService.get_sms_code_services(request, db, ResetUserModel(userName='u', sessionId='s'))
        assert sms.is_success is True

    # forget
    redis.get = AsyncMock(return_value=None)
    r = await LoginService.forget_user_services(
        request, db, ResetUserModel(userName='u', password='p', smsCode='1', sessionId='s')
    )
    assert r.is_success is False and '过期' in r.message

    redis.get = AsyncMock(return_value='999')
    redis.delete = AsyncMock()
    r = await LoginService.forget_user_services(
        request, db, ResetUserModel(userName='u', password='p', smsCode='1', sessionId='s')
    )
    assert r.is_success is False and '不正确' in r.message

    redis.get = AsyncMock(return_value='1')
    with (
        patch(
            'module_admin.service.login_service.UserDao.get_user_by_name',
            new=AsyncMock(return_value=SimpleNamespace(user_id=9)),
        ),
        patch('module_admin.service.login_service.PwdUtil.get_password_hash', return_value='h'),
        patch(
            'module_admin.service.login_service.UserService.reset_user_services',
            new=AsyncMock(return_value=CrudResponseModel(is_success=True, message='ok')),
        ),
    ):
        r = await LoginService.forget_user_services(
            request, db, ResetUserModel(userName='u', password='p', smsCode='1', sessionId='s')
        )
        assert r.is_success is True

    assert await LoginService.logout_services(request, 'tid') is True


# ---------------------------------------------------------------------------
# RouterUtil
# ---------------------------------------------------------------------------


def test_router_util_helpers() -> None:
    frame = _menu(menu_id=1, menu_type=MenuConstant.TYPE_MENU, path='index', is_frame=MenuConstant.NO_FRAME)
    assert RouterUtil.is_menu_frame(frame)
    assert RouterUtil.get_router_name(frame) == ''
    assert RouterUtil.get_router_path(frame) == '/'
    assert RouterUtil.get_route_name('', 'abc') == 'Abc'
    assert RouterUtil.get_route_name('Named', 'abc') == 'Named'

    directory = _menu(menu_id=2, menu_type=MenuConstant.TYPE_DIR, path='system', is_frame=MenuConstant.NO_FRAME)
    assert RouterUtil.get_router_path(directory) == '/system'
    assert RouterUtil.get_component(directory) == MenuConstant.LAYOUT

    with_comp = _menu(menu_id=3, menu_type=MenuConstant.TYPE_MENU, parent_id=1, path='u', component='sys/u')
    assert RouterUtil.get_component(with_comp) == 'sys/u'

    inner = _menu(
        menu_id=4,
        parent_id=1,
        menu_type=MenuConstant.TYPE_MENU,
        path='https://a.com',
        component='',
        is_frame=MenuConstant.NO_FRAME,
    )
    assert RouterUtil.is_inner_link(inner)
    assert RouterUtil.get_component(inner) == MenuConstant.INNER_LINK
    assert 'a' in RouterUtil.get_router_path(inner)

    parent_view = _menu(menu_id=5, parent_id=1, menu_type=MenuConstant.TYPE_DIR, path='x', component=None)
    assert RouterUtil.is_parent_view(parent_view)
    assert RouterUtil.get_component(parent_view) == MenuConstant.PARENT_VIEW

    assert RouterUtil.is_http('http://x') and RouterUtil.is_http('https://x')
    assert not RouterUtil.is_http('/local')
    assert RouterUtil.inner_link_replace_each('https://www.example.com:8080') == 'example/com/8080'
