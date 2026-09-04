"""Raise module_admin coverage leftovers: login routers + user import edges."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from common.constant import MenuConstant
from common.vo import CrudResponseModel
from fastapi import UploadFile
from module_admin.dao.user_dao import UserDao
from module_admin.entity.vo.login_vo import MenuTreeModel, UserLogin
from module_admin.entity.vo.user_vo import CurrentUserModel, UserInfoModel
from module_admin.service.login_service import LoginService, RouterUtil
from module_admin.service.user_service import UserService
from sqlalchemy import true


def _request(redis):
    from fastapi import Request

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
        'headers': [],
        'client': ('1.1.1.1', 1),
        'server': ('test', 80),
        'root_path': '',
        'app': app,
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_login_captcha_ok_and_router_branches() -> None:
    db = AsyncMock()
    redis = AsyncMock()

    async def get(key):
        from common.enums import RedisInitKeyConfig

        if key.startswith(RedisInitKeyConfig.ACCOUNT_LOCK.key):
            return None
        if key.startswith(RedisInitKeyConfig.CAPTCHA_CODES.key):
            return '42'
        return None

    redis.get = get
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    request = _request(redis)
    user_row = (SimpleNamespace(password='hash', status='0', user_name='u'), SimpleNamespace(dept_id=1))
    with (
        patch('module_admin.service.login_service.ClientIPUtil.get_client_ip', return_value='1.1.1.1'),
        patch('module_admin.service.login_service.login_by_account', new=AsyncMock(return_value=user_row)),
        patch('module_admin.service.login_service.PwdUtil.verify_password', return_value=True),
    ):
        assert await LoginService.authenticate_user(
            request, db, UserLogin(userName='u', password='p', captchaEnabled=True, code='42', uuid='sid')
        )

    # Direct router generation covering menu-frame + top-level inner-link
    frame = MenuTreeModel(
        menuId=10,
        parentId=0,
        menuName='首页',
        menuType=MenuConstant.TYPE_MENU,
        path='index',
        component='index',
        isFrame=MenuConstant.NO_FRAME,
        visible='0',
        isCache=0,
        routeName='',
        orderNum=1,
        icon='#',
    )
    inner = MenuTreeModel(
        menuId=11,
        parentId=0,
        menuName='外链',
        menuType=MenuConstant.TYPE_DIR,
        path='https://www.example.com',
        component=None,
        isFrame=MenuConstant.NO_FRAME,
        visible='0',
        isCache=0,
        routeName='',
        orderNum=2,
        icon='#',
    )
    routers = LoginService._LoginService__generate_user_router_menu([frame, inner])
    assert len(routers) == 2
    assert RouterUtil.is_menu_frame(frame)
    assert RouterUtil.is_inner_link(inner)


@pytest.mark.asyncio
async def test_user_import_non_admin_add_and_rollback() -> None:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    scope = true()
    file = AsyncMock(spec=UploadFile)
    file.read = AsyncMock(return_value=b'x')
    file.close = AsyncMock()
    req = MagicMock()
    req.app.state.redis = AsyncMock()
    cu = CurrentUserModel(
        permissions=[],
        roles=[],
        user=UserInfoModel(userId=2, userName='u', nickName='n', admin=False),
    )
    df = pd.DataFrame(
        [
            {
                '部门编号': 1,
                '登录名称': 'newbie',
                '用户名称': 'n',
                '用户邮箱': 'n@a.com',
                '手机号码': 1,
                '用户性别': '男',
                '帐号状态': '正常',
            }
        ]
    )
    with (
        patch('module_admin.service.user_service.pd.read_excel', return_value=df.copy()),
        patch(
            'module_admin.service.user_service.ConfigService.query_config_list_from_cache_services',
            new=AsyncMock(return_value='123456'),
        ),
        patch('module_admin.service.user_service.PwdUtil.get_password_hash', return_value='h'),
        patch.object(UserDao, 'get_user_by_info', new=AsyncMock(return_value=None)),
        patch(
            'module_admin.service.user_service.DeptService.check_dept_data_scope_services',
            new=AsyncMock(return_value=CrudResponseModel(is_success=True, message='ok')),
        ),
        patch.object(UserDao, 'add_user_dao', new=AsyncMock()),
    ):
        assert (await UserService.batch_import_user_services(req, db, file, False, cu, scope, scope)).is_success

    with (
        patch('module_admin.service.user_service.pd.read_excel', return_value=df.copy()),
        patch(
            'module_admin.service.user_service.ConfigService.query_config_list_from_cache_services',
            new=AsyncMock(return_value='123456'),
        ),
        patch('module_admin.service.user_service.PwdUtil.get_password_hash', return_value='h'),
        patch.object(UserDao, 'get_user_by_info', new=AsyncMock(return_value=None)),
        patch(
            'module_admin.service.user_service.DeptService.check_dept_data_scope_services',
            new=AsyncMock(return_value=CrudResponseModel(is_success=True, message='ok')),
        ),
        patch.object(UserDao, 'add_user_dao', new=AsyncMock(side_effect=RuntimeError('boom'))),
    ):
        with pytest.raises(RuntimeError):
            await UserService.batch_import_user_services(req, db, file, False, cu, scope, scope)
        db.rollback.assert_awaited()
