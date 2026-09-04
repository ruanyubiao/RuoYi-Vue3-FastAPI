"""Raise module_admin coverage: role/user services+daos."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from common.vo import CrudResponseModel, PageModel
from exceptions.exception import ServiceException
from fastapi import UploadFile
from module_admin.dao.role_dao import RoleDao
from module_admin.dao.user_dao import UserDao
from module_admin.entity.vo.role_vo import (
    AddRoleModel,
    DeleteRoleModel,
    RoleDeptModel,
    RoleMenuModel,
    RoleModel,
    RolePageQueryModel,
)
from module_admin.entity.vo.user_vo import (
    AddUserModel,
    CrudUserRoleModel,
    CurrentUserModel,
    DeleteUserModel,
    EditUserModel,
    ResetUserModel,
    UserDetailModel,
    UserInfoModel,
    UserModel,
    UserPageQueryModel,
    UserPostModel,
    UserRoleModel,
    UserRolePageQueryModel,
    UserRoleQueryModel,
)
from module_admin.service.role_service import RoleService
from module_admin.service.user_service import UserService
from sqlalchemy import true


@contextmanager
def expect_service_error(substr: str):
    with pytest.raises(ServiceException) as ei:
        yield
    assert substr in (ei.value.message or '')


def _db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


def _scalars_first(value):
    result = MagicMock()
    result.scalars.return_value.first.return_value = value
    return result


def _scalars_all(values):
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def _scalar(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _page(rows):
    return PageModel(rows=rows, pageNum=1, pageSize=10, total=len(rows), hasNext=False)


# ---------------------------------------------------------------------------
# role
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_role_service_and_dao() -> None:
    db = _db()
    scope = true()

    with (
        patch.object(RoleDao, 'get_role_select_option_dao', new=AsyncMock(return_value=[object()])),
        patch('module_admin.service.role_service.CamelCaseUtil.transform_result', return_value=[{'roleId': 2}]),
    ):
        assert await RoleService.get_role_select_option_services(db)

    with (
        patch.object(
            RoleService, 'role_detail_services', new=AsyncMock(return_value=RoleModel(roleId=2, deptCheckStrictly=1))
        ),
        patch.object(
            RoleDao, 'get_role_dept_dao', new=AsyncMock(return_value=[SimpleNamespace(dept_id=1)])
        ),
    ):
        assert (await RoleService.get_role_dept_tree_services(db, 2)).checked_keys == [1]

    with patch.object(RoleDao, 'get_role_list', new=AsyncMock(return_value=[])):
        await RoleService.get_role_list_services(db, RolePageQueryModel(), scope, False)

    with pytest.raises(ServiceException):
        await RoleService.check_role_allowed_services(RoleModel(roleId=1, roleName='r', roleKey='k', roleSort=1))
    assert (
        await RoleService.check_role_allowed_services(RoleModel(roleId=2, roleName='r', roleKey='k', roleSort=1))
    ).is_success

    with patch.object(RoleDao, 'get_role_list', new=AsyncMock(return_value=[{'roleId': 2}])):
        await RoleService.check_role_data_scope_services(db, '2', scope)
    with patch.object(RoleDao, 'get_role_list', new=AsyncMock(return_value=[])):
        with expect_service_error('没有权限'):
            await RoleService.check_role_data_scope_services(db, '2', scope)
    await RoleService.check_role_data_scope_services(db, '', scope)

    with patch.object(RoleDao, 'get_role_by_info', new=AsyncMock(return_value=SimpleNamespace(role_id=3))):
        assert await RoleService.check_role_name_unique_services(db, RoleModel(roleId=2, roleName='r')) is False
        assert await RoleService.check_role_key_unique_services(db, RoleModel(roleId=2, roleKey='k')) is False
        assert await RoleService.check_role_name_unique_services(db, RoleModel(roleId=3, roleName='r')) is True
    with patch.object(RoleDao, 'get_role_by_info', new=AsyncMock(return_value=None)):
        assert await RoleService.check_role_name_unique_services(db, RoleModel(roleName='r')) is True
        assert await RoleService.check_role_key_unique_services(db, RoleModel(roleKey='k')) is True

    add = AddRoleModel(roleName='r', roleKey='k', roleSort=1, menuIds=[1, 2])
    with patch.object(RoleService, 'check_role_name_unique_services', new=AsyncMock(return_value=False)):
        with expect_service_error('名称'):
            await RoleService.add_role_services(db, add)
    with (
        patch.object(RoleService, 'check_role_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(RoleService, 'check_role_key_unique_services', new=AsyncMock(return_value=False)),
    ):
        with expect_service_error('权限'):
            await RoleService.add_role_services(db, add)
    with (
        patch.object(RoleService, 'check_role_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(RoleService, 'check_role_key_unique_services', new=AsyncMock(return_value=True)),
        patch.object(RoleDao, 'add_role_dao', new=AsyncMock(return_value=SimpleNamespace(role_id=5))),
        patch.object(RoleDao, 'add_role_menu_dao', new=AsyncMock()),
    ):
        assert (await RoleService.add_role_services(db, add)).is_success
    with (
        patch.object(RoleService, 'check_role_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(RoleService, 'check_role_key_unique_services', new=AsyncMock(return_value=True)),
        patch.object(RoleDao, 'add_role_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await RoleService.add_role_services(db, add)

    edit = AddRoleModel(roleId=2, roleName='r', roleKey='k', roleSort=1, menuIds=[1], type='menu')
    with patch.object(RoleService, 'role_detail_services', new=AsyncMock(return_value=None)):
        with expect_service_error('不存在'):
            await RoleService.edit_role_services(db, edit)
    with (
        patch.object(RoleService, 'role_detail_services', new=AsyncMock(return_value=RoleModel(roleId=2))),
        patch.object(RoleService, 'check_role_name_unique_services', new=AsyncMock(return_value=False)),
    ):
        with expect_service_error('名称'):
            await RoleService.edit_role_services(db, edit)
    with (
        patch.object(RoleService, 'role_detail_services', new=AsyncMock(return_value=RoleModel(roleId=2))),
        patch.object(RoleService, 'check_role_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(RoleService, 'check_role_key_unique_services', new=AsyncMock(return_value=False)),
    ):
        with expect_service_error('权限'):
            await RoleService.edit_role_services(db, edit)
    with (
        patch.object(RoleService, 'role_detail_services', new=AsyncMock(return_value=RoleModel(roleId=2))),
        patch.object(RoleService, 'check_role_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(RoleService, 'check_role_key_unique_services', new=AsyncMock(return_value=True)),
        patch.object(RoleDao, 'edit_role_dao', new=AsyncMock()),
        patch.object(RoleDao, 'delete_role_menu_dao', new=AsyncMock()),
        patch.object(RoleDao, 'add_role_menu_dao', new=AsyncMock()),
    ):
        assert (await RoleService.edit_role_services(db, edit)).is_success
    status_edit = AddRoleModel(roleId=2, roleName='r', roleKey='k', roleSort=1, status='1', type='status')
    with (
        patch.object(RoleService, 'role_detail_services', new=AsyncMock(return_value=RoleModel(roleId=2))),
        patch.object(RoleDao, 'edit_role_dao', new=AsyncMock()),
    ):
        assert (await RoleService.edit_role_services(db, status_edit)).is_success
    with (
        patch.object(RoleService, 'role_detail_services', new=AsyncMock(return_value=RoleModel(roleId=2))),
        patch.object(RoleService, 'check_role_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(RoleService, 'check_role_key_unique_services', new=AsyncMock(return_value=True)),
        patch.object(RoleDao, 'edit_role_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await RoleService.edit_role_services(db, edit)

    scope_role = AddRoleModel(roleId=2, dataScope='2', deptIds=[1, 2])
    with patch.object(RoleService, 'role_detail_services', new=AsyncMock(return_value=RoleModel())):
        with expect_service_error('不存在'):
            await RoleService.role_datascope_services(db, scope_role)
    with (
        patch.object(RoleService, 'role_detail_services', new=AsyncMock(return_value=RoleModel(roleId=2))),
        patch.object(RoleDao, 'edit_role_dao', new=AsyncMock()),
        patch.object(RoleDao, 'delete_role_dept_dao', new=AsyncMock()),
        patch.object(RoleDao, 'add_role_dept_dao', new=AsyncMock()),
    ):
        assert (await RoleService.role_datascope_services(db, scope_role)).is_success
    with (
        patch.object(RoleService, 'role_detail_services', new=AsyncMock(return_value=RoleModel(roleId=2))),
        patch.object(RoleDao, 'edit_role_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await RoleService.role_datascope_services(db, scope_role)

    with expect_service_error('为空'):
        await RoleService.delete_role_services(db, DeleteRoleModel(roleIds=''))
    with (
        patch.object(
            RoleService, 'role_detail_services', new=AsyncMock(return_value=RoleModel(roleId=2, roleName='r'))
        ),
        patch.object(RoleDao, 'count_user_role_dao', new=AsyncMock(return_value=1)),
    ):
        with expect_service_error('已分配'):
            await RoleService.delete_role_services(db, DeleteRoleModel(roleIds='2'))
    with (
        patch.object(
            RoleService, 'role_detail_services', new=AsyncMock(return_value=RoleModel(roleId=2, roleName='r'))
        ),
        patch.object(RoleDao, 'count_user_role_dao', new=AsyncMock(return_value=0)),
        patch.object(RoleDao, 'delete_role_menu_dao', new=AsyncMock()),
        patch.object(RoleDao, 'delete_role_dept_dao', new=AsyncMock()),
        patch.object(RoleDao, 'delete_role_dao', new=AsyncMock()),
    ):
        assert (await RoleService.delete_role_services(db, DeleteRoleModel(roleIds='2'))).is_success
    with (
        patch.object(
            RoleService, 'role_detail_services', new=AsyncMock(return_value=RoleModel(roleId=2, roleName='r'))
        ),
        patch.object(RoleDao, 'count_user_role_dao', new=AsyncMock(return_value=0)),
        patch.object(RoleDao, 'delete_role_menu_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await RoleService.delete_role_services(db, DeleteRoleModel(roleIds='2'))

    with (
        patch.object(RoleDao, 'get_role_detail_by_id', new=AsyncMock(return_value=object())),
        patch(
            'module_admin.service.role_service.CamelCaseUtil.transform_result',
            return_value={'roleId': 2, 'roleName': 'r', 'roleKey': 'k', 'roleSort': 1},
        ),
    ):
        assert (await RoleService.role_detail_services(db, 2)).role_id == 2
    with patch.object(RoleDao, 'get_role_detail_by_id', new=AsyncMock(return_value=None)):
        assert (await RoleService.role_detail_services(db, 2)).role_id is None

    with patch('module_admin.service.role_service.ExcelUtil.export_list2excel', return_value=b'r'):
        assert await RoleService.export_role_list_services([{'status': '0'}, {'status': '1'}]) == b'r'

    page = _page([{'userId': 1, 'userName': 'u'}])
    with patch.object(UserDao, 'get_user_role_allocated_list_by_role_id', new=AsyncMock(return_value=page)):
        assert (await RoleService.get_role_user_allocated_list_services(db, UserRolePageQueryModel(roleId=2), scope)).total == 1
    with patch.object(UserDao, 'get_user_role_unallocated_list_by_role_id', new=AsyncMock(return_value=page)):
        assert (await RoleService.get_role_user_unallocated_list_services(db, UserRolePageQueryModel(roleId=2), scope)).total == 1

    # dao
    db.execute = AsyncMock(return_value=_scalars_first(SimpleNamespace(role_id=2)))
    await RoleDao.get_role_by_name(db, 'r')
    await RoleDao.get_role_by_info(db, RoleModel(roleName='r'))
    await RoleDao.get_role_by_info(db, RoleModel(roleKey='k'))
    await RoleDao.get_role_by_id(db, 2)
    await RoleDao.get_role_detail_by_id(db, 2)
    db.execute = AsyncMock(return_value=_scalars_all([SimpleNamespace(role_id=2)]))
    await RoleDao.get_role_select_option_dao(db)
    with patch('module_admin.dao.role_dao.PageUtil.paginate', new=AsyncMock(return_value=[])):
        await RoleDao.get_role_list(
            db,
            RolePageQueryModel(roleId=2, roleName='r', roleKey='k', status='0', beginTime='2024-01-01', endTime='2024-01-02'),
            scope,
            True,
        )
        await RoleDao.get_role_list(db, RolePageQueryModel(), scope, False)
    db.add = MagicMock()
    db.flush = AsyncMock()
    await RoleDao.add_role_dao(db, RoleModel(roleName='r', roleKey='k', roleSort=1))
    db.execute = AsyncMock()
    await RoleDao.edit_role_dao(db, {'role_id': 2})
    await RoleDao.delete_role_dao(db, RoleModel(roleId=2))
    db.execute = AsyncMock(return_value=_scalars_all([SimpleNamespace(menu_id=1)]))
    await RoleDao.get_role_menu_dao(db, RoleModel(roleId=2, menuCheckStrictly=1))
    await RoleDao.get_role_menu_dao(db, RoleModel(roleId=2, menuCheckStrictly=0))
    db.add = MagicMock()
    await RoleDao.add_role_menu_dao(db, RoleMenuModel(roleId=2, menuId=1))
    db.execute = AsyncMock()
    await RoleDao.delete_role_menu_dao(db, RoleMenuModel(roleId=2))
    db.execute = AsyncMock(return_value=_scalars_all([SimpleNamespace(dept_id=1)]))
    await RoleDao.get_role_dept_dao(db, RoleModel(roleId=2, deptCheckStrictly=1))
    await RoleDao.get_role_dept_dao(db, RoleModel(roleId=2, deptCheckStrictly=0))
    db.add = MagicMock()
    await RoleDao.add_role_dept_dao(db, RoleDeptModel(roleId=2, deptId=1))
    db.execute = AsyncMock()
    await RoleDao.delete_role_dept_dao(db, RoleDeptModel(roleId=2))
    db.execute = AsyncMock(return_value=_scalar(2))
    assert await RoleDao.count_user_role_dao(db, 2) == 2


# ---------------------------------------------------------------------------
# user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_service_and_dao() -> None:
    db = _db()
    scope = true()

    page = _page([({'userId': 1}, {'deptId': 1})])
    with patch.object(UserDao, 'get_user_list', new=AsyncMock(return_value=page)):
        got = await UserService.get_user_list_services(db, UserPageQueryModel(), scope, True)
        assert got.total == 1
    with patch.object(UserDao, 'get_user_list', new=AsyncMock(return_value=[({'userId': 1}, {'deptId': 1})])):
        assert await UserService.get_user_list_services(db, UserPageQueryModel(), scope, False)
    with patch.object(UserDao, 'get_user_list', new=AsyncMock(return_value=[])):
        assert await UserService.get_user_list_services(db, UserPageQueryModel(), scope, False) == []

    with expect_service_error('超级管理员'):
        await UserService.check_user_allowed_services(UserModel(userId=1, userName='a', nickName='n'))
    assert (await UserService.check_user_allowed_services(UserModel(userId=2, userName='a', nickName='n'))).is_success

    with patch.object(UserDao, 'get_user_list', new=AsyncMock(return_value=[{}])):
        assert (await UserService.check_user_data_scope_services(db, 2, scope)).is_success
    with patch.object(UserDao, 'get_user_list', new=AsyncMock(return_value=[])):
        with expect_service_error('没有权限'):
            await UserService.check_user_data_scope_services(db, 2, scope)

    with patch.object(UserDao, 'get_user_by_info', new=AsyncMock(return_value=SimpleNamespace(user_id=3))):
        assert await UserService.check_user_name_unique_services(db, UserModel(userId=2, userName='u')) is False
        assert await UserService.check_phonenumber_unique_services(db, UserModel(userId=2, phonenumber='1')) is False
        assert await UserService.check_email_unique_services(db, UserModel(userId=2, email='a@b.com')) is False
        assert await UserService.check_user_name_unique_services(db, UserModel(userId=3, userName='u')) is True
    with patch.object(UserDao, 'get_user_by_info', new=AsyncMock(return_value=None)):
        assert await UserService.check_user_name_unique_services(db, UserModel(userName='u')) is True
        assert await UserService.check_phonenumber_unique_services(db, UserModel(phonenumber='1')) is True
        assert await UserService.check_email_unique_services(db, UserModel(email='a@b.com')) is True

    add = AddUserModel(userName='u', nickName='n', roleIds=[1], postIds=[2], phonenumber='1', email='a@b.com')
    with patch.object(UserService, 'check_user_name_unique_services', new=AsyncMock(return_value=False)):
        with expect_service_error('登录账号'):
            await UserService.add_user_services(db, add)
    with (
        patch.object(UserService, 'check_user_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserService, 'check_phonenumber_unique_services', new=AsyncMock(return_value=False)),
    ):
        with expect_service_error('手机'):
            await UserService.add_user_services(db, add)
    with (
        patch.object(UserService, 'check_user_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserService, 'check_phonenumber_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserService, 'check_email_unique_services', new=AsyncMock(return_value=False)),
    ):
        with expect_service_error('邮箱'):
            await UserService.add_user_services(db, add)
    with (
        patch.object(UserService, 'check_user_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserService, 'check_phonenumber_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserService, 'check_email_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserDao, 'add_user_dao', new=AsyncMock(return_value=SimpleNamespace(user_id=9))),
        patch.object(UserDao, 'add_user_role_dao', new=AsyncMock()),
        patch.object(UserDao, 'add_user_post_dao', new=AsyncMock()),
    ):
        assert (await UserService.add_user_services(db, add)).is_success
    with (
        patch.object(UserService, 'check_user_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserService, 'check_phonenumber_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserService, 'check_email_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserDao, 'add_user_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await UserService.add_user_services(db, add)

    edit = EditUserModel(
        userId=2,
        userName='u',
        nickName='n',
        roleIds=[1],
        postIds=[2],
        role=[],
        phonenumber='1',
        email='a@b.com',
        type='full',
    )
    empty_detail = UserDetailModel(data=None, posts=[], roles=[])
    with patch.object(UserService, 'user_detail_services', new=AsyncMock(return_value=empty_detail)):
        with expect_service_error('不存在'):
            await UserService.edit_user_services(db, edit)
    detail = UserDetailModel(data=UserInfoModel(userId=2, userName='u', nickName='n'), posts=[], roles=[])
    with (
        patch.object(UserService, 'user_detail_services', new=AsyncMock(return_value=detail)),
        patch.object(UserService, 'check_user_name_unique_services', new=AsyncMock(return_value=False)),
    ):
        with expect_service_error('登录账号'):
            await UserService.edit_user_services(db, edit)
    with (
        patch.object(UserService, 'user_detail_services', new=AsyncMock(return_value=detail)),
        patch.object(UserService, 'check_user_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserService, 'check_phonenumber_unique_services', new=AsyncMock(return_value=False)),
    ):
        with expect_service_error('手机'):
            await UserService.edit_user_services(db, edit)
    with (
        patch.object(UserService, 'user_detail_services', new=AsyncMock(return_value=detail)),
        patch.object(UserService, 'check_user_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserService, 'check_phonenumber_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserService, 'check_email_unique_services', new=AsyncMock(return_value=False)),
    ):
        with expect_service_error('邮箱'):
            await UserService.edit_user_services(db, edit)
    with (
        patch.object(UserService, 'user_detail_services', new=AsyncMock(return_value=detail)),
        patch.object(UserService, 'check_user_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserService, 'check_phonenumber_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserService, 'check_email_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserDao, 'edit_user_dao', new=AsyncMock()),
        patch.object(UserDao, 'delete_user_role_dao', new=AsyncMock()),
        patch.object(UserDao, 'delete_user_post_dao', new=AsyncMock()),
        patch.object(UserDao, 'add_user_role_dao', new=AsyncMock()),
        patch.object(UserDao, 'add_user_post_dao', new=AsyncMock()),
    ):
        assert (await UserService.edit_user_services(db, edit)).is_success
    status = EditUserModel(userId=2, userName='u', nickName='n', type='status', status='1')
    with (
        patch.object(UserService, 'user_detail_services', new=AsyncMock(return_value=detail)),
        patch.object(UserDao, 'edit_user_dao', new=AsyncMock()),
    ):
        assert (await UserService.edit_user_services(db, status)).is_success
    with (
        patch.object(UserService, 'user_detail_services', new=AsyncMock(return_value=detail)),
        patch.object(UserService, 'check_user_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserService, 'check_phonenumber_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserService, 'check_email_unique_services', new=AsyncMock(return_value=True)),
        patch.object(UserDao, 'edit_user_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await UserService.edit_user_services(db, edit)

    with expect_service_error('为空'):
        await UserService.delete_user_services(db, DeleteUserModel(userIds=''))
    with (
        patch.object(UserDao, 'delete_user_role_dao', new=AsyncMock()),
        patch.object(UserDao, 'delete_user_post_dao', new=AsyncMock()),
        patch.object(UserDao, 'delete_user_dao', new=AsyncMock()),
    ):
        assert (await UserService.delete_user_services(db, DeleteUserModel(userIds='2'))).is_success
    with patch.object(UserDao, 'delete_user_role_dao', new=AsyncMock(side_effect=RuntimeError('e'))):
        with pytest.raises(RuntimeError):
            await UserService.delete_user_services(db, DeleteUserModel(userIds='2'))

    query_user = {
        'user_basic_info': SimpleNamespace(user_id=2, user_name='u', nick_name='n', password='h'),
        'user_dept_info': SimpleNamespace(dept_id=1, dept_name='d'),
        'user_role_info': [SimpleNamespace(role_id=2, role_name='r', role_key='k')],
        'user_post_info': [SimpleNamespace(post_id=3, post_name='p')],
        'user_menu_info': [],
    }
    with (
        patch(
            'module_admin.service.user_service.PostService.get_post_list_services',
            new=AsyncMock(return_value=[]),
        ),
        patch(
            'module_admin.service.user_service.RoleService.get_role_select_option_services',
            new=AsyncMock(return_value=[]),
        ),
        patch.object(UserDao, 'get_user_detail_by_id', new=AsyncMock(return_value=query_user)),
        patch(
            'module_admin.service.user_service.CamelCaseUtil.transform_result',
            side_effect=lambda x: {'userId': 2, 'userName': 'u', 'nickName': 'n'}
            if hasattr(x, 'user_id')
            else ({'deptId': 1} if hasattr(x, 'dept_id') else [{'roleId': 2, 'roleName': 'r', 'roleKey': 'k'}]),
        ),
    ):
        d = await UserService.user_detail_services(db, 2)
        assert d.data.user_id == 2
        empty = await UserService.user_detail_services(db, '')
        assert empty.data is None

    with (
        patch.object(UserDao, 'get_user_detail_by_id', new=AsyncMock(return_value=query_user)),
        patch(
            'module_admin.service.user_service.CamelCaseUtil.transform_result',
            side_effect=lambda x: {'userId': 2, 'userName': 'u', 'nickName': 'n'}
            if hasattr(x, 'user_id')
            else ({'deptId': 1} if hasattr(x, 'dept_id') else [{'roleId': 2, 'roleName': 'r', 'roleKey': 'k'}]),
        ),
    ):
        profile = await UserService.user_profile_services(db, 2)
        assert 'p' in profile.post_group

    with (
        patch.object(UserDao, 'get_user_detail_by_id', new=AsyncMock(return_value=query_user)),
        patch('module_admin.service.user_service.PwdUtil.verify_password', side_effect=[False]),
    ):
        with expect_service_error('旧密码'):
            await UserService.reset_user_services(
                db, ResetUserModel(userId=2, password='new', oldPassword='old')
            )
    with (
        patch.object(UserDao, 'get_user_detail_by_id', new=AsyncMock(return_value=query_user)),
        patch('module_admin.service.user_service.PwdUtil.verify_password', side_effect=[True, True]),
    ):
        with expect_service_error('相同'):
            await UserService.reset_user_services(
                db, ResetUserModel(userId=2, password='same', oldPassword='same')
            )
    with (
        patch.object(UserDao, 'get_user_detail_by_id', new=AsyncMock(return_value=query_user)),
        patch('module_admin.service.user_service.PwdUtil.verify_password', side_effect=[True, False]),
        patch('module_admin.service.user_service.PwdUtil.get_password_hash', return_value='hashed'),
        patch.object(UserDao, 'edit_user_dao', new=AsyncMock()),
    ):
        assert (
            await UserService.reset_user_services(
                db, ResetUserModel(userId=2, password='new', oldPassword='old', smsCode='1', sessionId='s')
            )
        ).is_success
    with (
        patch('module_admin.service.user_service.PwdUtil.get_password_hash', return_value='hashed'),
        patch.object(UserDao, 'edit_user_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await UserService.reset_user_services(db, ResetUserModel(userId=2, password='new'))

    row = pd.Series({'sex': '男', 'status': '正常'})
    UserService._set_row_sex_value(row)
    UserService._set_row_status_value(row)
    assert row['sex'] == '0' and row['status'] == '0'
    row2 = pd.Series({'sex': '女', 'status': '停用'})
    UserService._set_row_sex_value(row2)
    UserService._set_row_status_value(row2)
    row3 = pd.Series({'sex': '未知', 'status': '正常'})
    UserService._set_row_sex_value(row3)

    with patch('module_admin.service.user_service.ExcelUtil.get_excel_template', return_value=b'tpl'):
        assert await UserService.get_user_import_template_services() == b'tpl'
    with patch('module_admin.service.user_service.ExcelUtil.export_list2excel', return_value=b'xls'):
        data = [
            {'userId': 1, 'status': '0', 'sex': '0', 'dept': {'deptName': 'd'}},
            {'userId': 2, 'status': '1', 'sex': '1', 'dept': {'deptName': 'd'}},
            {'userId': 3, 'status': '1', 'sex': '2', 'dept': {'deptName': 'd'}},
        ]
        assert await UserService.export_user_list_services(data) == b'xls'

    # import: existing skip / update / new
    df = pd.DataFrame(
        [
            {
                '部门编号': 1,
                '登录名称': 'exist',
                '用户名称': 'e',
                '用户邮箱': 'e@a.com',
                '手机号码': 123,
                '用户性别': '男',
                '帐号状态': '正常',
            },
            {
                '部门编号': 1,
                '登录名称': 'newu',
                '用户名称': 'n',
                '用户邮箱': 'n@a.com',
                '手机号码': 456,
                '用户性别': '女',
                '帐号状态': '停用',
            },
        ]
    )
    file = AsyncMock(spec=UploadFile)
    file.read = AsyncMock(return_value=b'xlsx')
    file.close = AsyncMock()
    req = MagicMock()
    req.app.state.redis = AsyncMock()
    cu = CurrentUserModel(
        permissions=[],
        roles=[],
        user=UserInfoModel(userId=1, userName='admin', nickName='a', admin=True),
    )
    with (
        patch('module_admin.service.user_service.pd.read_excel', return_value=df.copy()),
        patch(
            'module_admin.service.user_service.ConfigService.query_config_list_from_cache_services',
            new=AsyncMock(return_value='123456'),
        ),
        patch('module_admin.service.user_service.PwdUtil.get_password_hash', return_value='h'),
        patch.object(
            UserDao,
            'get_user_by_info',
            new=AsyncMock(side_effect=[SimpleNamespace(user_id=9), None]),
        ),
        patch.object(UserDao, 'add_user_dao', new=AsyncMock()),
    ):
        r = await UserService.batch_import_user_services(req, db, file, False, cu, scope, scope)
        assert '已存在' in r.message
    # update_support path for non-admin
    cu2 = CurrentUserModel(
        permissions=[],
        roles=[],
        user=UserInfoModel(userId=2, userName='u', nickName='n', admin=False),
    )
    df1 = pd.DataFrame(
        [
            {
                '部门编号': 1,
                '登录名称': 'exist',
                '用户名称': 'e',
                '用户邮箱': 'e@a.com',
                '手机号码': 123,
                '用户性别': '未知',
                '帐号状态': '正常',
            }
        ]
    )
    with (
        patch('module_admin.service.user_service.pd.read_excel', return_value=df1.copy()),
        patch(
            'module_admin.service.user_service.ConfigService.query_config_list_from_cache_services',
            new=AsyncMock(return_value='123456'),
        ),
        patch('module_admin.service.user_service.PwdUtil.get_password_hash', return_value='h'),
        patch.object(UserDao, 'get_user_by_info', new=AsyncMock(return_value=SimpleNamespace(user_id=9))),
        patch.object(UserService, 'check_user_allowed_services', new=AsyncMock(return_value=CrudResponseModel(is_success=True, message='ok'))),
        patch.object(UserService, 'check_user_data_scope_services', new=AsyncMock(return_value=CrudResponseModel(is_success=True, message='ok'))),
        patch(
            'module_admin.service.user_service.DeptService.check_dept_data_scope_services',
            new=AsyncMock(return_value=CrudResponseModel(is_success=True, message='ok')),
        ),
        patch.object(UserDao, 'edit_user_dao', new=AsyncMock()),
    ):
        assert (await UserService.batch_import_user_services(req, db, file, True, cu2, scope, scope)).is_success
    with (
        patch('module_admin.service.user_service.pd.read_excel', side_effect=RuntimeError('bad')),
    ):
        with pytest.raises(RuntimeError):
            await UserService.batch_import_user_services(req, db, file, False, cu, scope, scope)

    with (
        patch.object(UserDao, 'get_user_detail_by_id', new=AsyncMock(return_value=query_user)),
        patch(
            'module_admin.service.user_service.RoleService.get_role_select_option_services',
            new=AsyncMock(return_value=[{'roleId': 2, 'roleName': 'r', 'roleKey': 'k'}]),
        ),
        patch(
            'module_admin.service.user_service.CamelCaseUtil.transform_result',
            side_effect=lambda x: {'userId': 2, 'userName': 'u', 'nickName': 'n'}
            if hasattr(x, 'user_id')
            else ({'deptId': 1} if hasattr(x, 'dept_id') else [{'roleId': 2, 'roleName': 'r', 'roleKey': 'k'}]),
        ),
    ):
        alloc = await UserService.get_user_role_allocated_list_services(db, UserRoleQueryModel(userId=2))
        assert alloc.user.user_id == 2

    with (
        patch.object(UserDao, 'delete_user_role_by_user_and_role_dao', new=AsyncMock()),
        patch.object(UserDao, 'add_user_role_dao', new=AsyncMock()),
    ):
        assert (
            await UserService.add_user_role_services(db, CrudUserRoleModel(userId=2, roleIds='1,2'))
        ).is_success
        assert (await UserService.add_user_role_services(db, CrudUserRoleModel(userId=2, roleIds=''))).is_success
    with (
        patch.object(UserService, 'detail_user_role_services', new=AsyncMock(side_effect=[object(), None])),
        patch.object(UserDao, 'add_user_role_dao', new=AsyncMock()),
    ):
        assert (
            await UserService.add_user_role_services(db, CrudUserRoleModel(userIds='3,4', roleId=2))
        ).is_success
    with expect_service_error('不满足新增'):
        await UserService.add_user_role_services(db, CrudUserRoleModel())
    with patch.object(UserDao, 'delete_user_role_by_user_and_role_dao', new=AsyncMock(side_effect=RuntimeError('e'))):
        with pytest.raises(RuntimeError):
            await UserService.add_user_role_services(db, CrudUserRoleModel(userId=2, roleIds='1'))
        with pytest.raises(RuntimeError):
            await UserService.add_user_role_services(db, CrudUserRoleModel(userId=2, roleIds=''))
    with (
        patch.object(UserService, 'detail_user_role_services', new=AsyncMock(return_value=None)),
        patch.object(UserDao, 'add_user_role_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await UserService.add_user_role_services(db, CrudUserRoleModel(userIds='3', roleId=2))

    with patch.object(UserDao, 'delete_user_role_by_user_and_role_dao', new=AsyncMock()):
        assert (
            await UserService.delete_user_role_services(db, CrudUserRoleModel(userId=2, roleId=1))
        ).is_success
        assert (
            await UserService.delete_user_role_services(db, CrudUserRoleModel(userIds='2,3', roleId=1))
        ).is_success
    with expect_service_error('为空'):
        await UserService.delete_user_role_services(db, CrudUserRoleModel())
    with patch.object(UserDao, 'delete_user_role_by_user_and_role_dao', new=AsyncMock(side_effect=RuntimeError('e'))):
        with pytest.raises(RuntimeError):
            await UserService.delete_user_role_services(db, CrudUserRoleModel(userId=2, roleId=1))
        with pytest.raises(RuntimeError):
            await UserService.delete_user_role_services(db, CrudUserRoleModel(userIds='2', roleId=1))

    with patch.object(UserDao, 'get_user_role_detail', new=AsyncMock(return_value=object())):
        assert await UserService.detail_user_role_services(db, UserRoleModel(userId=1, roleId=2))

    # dao coverage
    db.execute = AsyncMock(return_value=_scalars_first(SimpleNamespace(user_id=1)))
    await UserDao.get_user_by_name(db, 'u')
    await UserDao.get_user_by_info(db, UserModel(userName='u'))
    await UserDao.get_user_by_info(db, UserModel(phonenumber='1'))
    await UserDao.get_user_by_info(db, UserModel(email='a@b.com'))
    await UserDao.get_user_by_info(db, UserModel())

    # get_user_by_id admin vs non-admin menus
    role_admin = [SimpleNamespace(role_id=1)]
    role_normal = [SimpleNamespace(role_id=2)]
    exec_seq = [
        _scalars_first(SimpleNamespace(user_id=1)),  # basic
        _scalars_first(SimpleNamespace(dept_id=1)),  # dept
        _scalars_all(role_admin),  # roles
        _scalars_all([SimpleNamespace(post_id=1)]),  # posts
        _scalars_all([SimpleNamespace(menu_id=1)]),  # menus admin
    ]
    db.execute = AsyncMock(side_effect=exec_seq)
    await UserDao.get_user_by_id(db, 1)
    exec_seq2 = [
        _scalars_first(SimpleNamespace(user_id=2)),
        _scalars_first(SimpleNamespace(dept_id=1)),
        _scalars_all(role_normal),
        _scalars_all([]),
        _scalars_all([]),
    ]
    db.execute = AsyncMock(side_effect=exec_seq2)
    await UserDao.get_user_by_id(db, 2)

    detail_seq = [
        _scalars_first(SimpleNamespace(user_id=2)),
        _scalars_first(SimpleNamespace(dept_id=1)),
        _scalars_all(role_normal),
        _scalars_all([]),
        _scalars_all([]),
    ]
    db.execute = AsyncMock(side_effect=detail_seq)
    await UserDao.get_user_detail_by_id(db, 2)

    with patch('module_admin.dao.user_dao.PageUtil.paginate', new=AsyncMock(return_value=[])):
        await UserDao.get_user_list(
            db,
            UserPageQueryModel(
                deptId=1,
                userId=2,
                userName='u',
                nickName='n',
                email='e',
                phonenumber='1',
                status='0',
                sex='0',
                beginTime='2024-01-01',
                endTime='2024-01-02',
            ),
            scope,
            True,
        )
        await UserDao.get_user_list(db, UserPageQueryModel(), scope, False)
        await UserDao.get_user_role_allocated_list_by_role_id(db, UserRolePageQueryModel(roleId=2, userName='u', phonenumber='1'), scope, True)
        await UserDao.get_user_role_unallocated_list_by_role_id(db, UserRolePageQueryModel(roleId=2), scope, False)

    db.execute = AsyncMock(return_value=_scalars_all([SimpleNamespace(role_id=2)]))
    await UserDao.get_user_role_allocated_list_by_user_id(
        db, SimpleNamespace(user_id=2, role_name='r', role_key='k')
    )
    await UserDao.get_user_role_allocated_list_by_user_id(
        db, SimpleNamespace(user_id=2, role_name=None, role_key=None)
    )

    db.add = MagicMock()
    db.flush = AsyncMock()
    await UserDao.add_user_dao(db, UserModel(userName='u', nickName='n'))
    db.execute = AsyncMock()
    await UserDao.edit_user_dao(db, {'user_id': 2})
    await UserDao.delete_user_dao(db, UserModel(userId=2))
    db.add = MagicMock()
    await UserDao.add_user_role_dao(db, UserRoleModel(userId=1, roleId=2))
    db.execute = AsyncMock()
    await UserDao.delete_user_role_dao(db, UserRoleModel(userId=1))
    await UserDao.delete_user_role_by_user_and_role_dao(db, UserRoleModel(userId=1, roleId=2))
    await UserDao.delete_user_role_by_user_and_role_dao(db, UserRoleModel())
    db.execute = AsyncMock(return_value=_scalars_first(object()))
    await UserDao.get_user_role_detail(db, UserRoleModel(userId=1, roleId=2))
    db.add = MagicMock()
    await UserDao.add_user_post_dao(db, UserPostModel(userId=1, postId=2))
    db.execute = AsyncMock()
    await UserDao.delete_user_post_dao(db, UserPostModel(userId=1))
    db.execute = AsyncMock(return_value=_scalars_first(SimpleNamespace(dept_id=1)))
    await UserDao.get_user_dept_info(db, 1)
