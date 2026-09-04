"""Raise module_admin coverage: dept/menu services+daos + health/captcha leftovers."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from exceptions.exception import ServiceException, ServiceWarning
from module_admin.dao.dept_dao import DeptDao
from module_admin.dao.menu_dao import MenuDao
from module_admin.entity.vo.dept_vo import DeleteDeptModel, DeptModel
from module_admin.entity.vo.menu_vo import DeleteMenuModel, MenuModel, MenuQueryModel
from module_admin.entity.vo.user_vo import CurrentUserModel, UserInfoModel
from module_admin.service.captcha_service import CaptchaService, _captcha_font_path
from module_admin.service.dept_service import DeptService
from module_admin.service.health_service import HealthService
from module_admin.service.menu_service import MenuService
from sqlalchemy import true


@contextmanager
def expect_service_error(substr: str):
    with pytest.raises(ServiceException) as ei:
        yield
    assert substr in (ei.value.message or '')


@contextmanager
def expect_service_warning(substr: str):
    with pytest.raises(ServiceWarning) as ei:
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


def _current_user(*, admin: bool = True, role_id: int = 1) -> CurrentUserModel:
    role = SimpleNamespace(role_id=role_id, role_key='admin', role_name='管理员')
    user = UserInfoModel(
        userId=1 if admin else 2,
        userName='admin',
        nickName='管理员',
        admin=admin,
        role=[role],
    )
    return CurrentUserModel(permissions=['*:*:*'], roles=['admin'], user=user)


# ---------------------------------------------------------------------------
# health leftovers (check / redis / collectors / version)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_check_and_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok_db():
        return {'status': 'ok', 'type': 'mysql', 'latencyMs': 1.0}

    class FakeMgr:
        @staticmethod
        def list_opened():
            return [{'alive': True}, {'alive': False}]

    monkeypatch.setattr(HealthService, '_check_database', staticmethod(ok_db))
    monkeypatch.setattr(
        'module_payload.collectors.process_manager.CollectorProcessManager.instance',
        lambda: FakeMgr(),
    )

    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    payload, code = await HealthService.check(redis)
    assert code == 200 and payload['status'] == 'ok'
    assert payload['collectors'] == {'opened': 2, 'alive': 1}

    redis.ping = AsyncMock(side_effect=ConnectionError('down'))
    payload, code = await HealthService.check(redis)
    assert code == 503 and payload['redis']['status'] == 'error'

    payload, code = await HealthService.check(None)
    assert code == 503 and '未初始化' in payload['redis']['error']

    import sys
    from types import ModuleType

    ver = ModuleType('version')
    ver.appVersion = '9.9.9'
    monkeypatch.setitem(sys.modules, 'version', ver)
    assert HealthService._app_version() == '9.9.9'

    monkeypatch.setattr(
        'module_payload.collectors.process_manager.CollectorProcessManager.instance',
        lambda: (_ for _ in ()).throw(RuntimeError('x')),
    )
    assert HealthService._collectors() == {'opened': 0, 'alive': 0}


# ---------------------------------------------------------------------------
# captcha leftovers
# ---------------------------------------------------------------------------


def test_captcha_font_none_and_build_fail(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('module_admin.service.captcha_service.get_package_root', lambda: tmp_path)
    monkeypatch.setattr('module_admin.service.captcha_service.os.name', 'posix', raising=False)
    assert _captcha_font_path() is None


@pytest.mark.asyncio
async def test_build_captcha_degrades_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value='true')

    async def boom():
        raise RuntimeError('draw fail')

    monkeypatch.setattr(CaptchaService, 'create_captcha_image_service', boom)
    result = await CaptchaService.build_captcha_code(redis)
    assert result.captcha_enabled is False


# ---------------------------------------------------------------------------
# dept service + dao
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dept_service_and_dao() -> None:
    db = _db()
    scope = true()
    root = SimpleNamespace(dept_id=1, dept_name='root', parent_id=0, ancestors='0', status='0')
    child = SimpleNamespace(dept_id=2, dept_name='child', parent_id=1, ancestors='0,1', status='0')

    with patch.object(DeptDao, 'get_dept_list_for_tree', new=AsyncMock(return_value=[root, child])):
        tree = await DeptService.get_dept_tree_services(db, DeptModel(), scope)
        assert len(tree) == 1 and tree[0]['id'] == 1

    with (
        patch.object(DeptDao, 'get_dept_info_for_edit_option', new=AsyncMock(return_value=[root])),
        patch('module_admin.service.dept_service.CamelCaseUtil.transform_result', return_value=[{'deptId': 1}]),
    ):
        assert await DeptService.get_dept_for_edit_option_services(db, DeptModel(deptId=2), scope)

    with (
        patch.object(DeptDao, 'get_dept_list', new=AsyncMock(return_value=[root])),
        patch('module_admin.service.dept_service.CamelCaseUtil.transform_result', return_value=[{'deptId': 1}]),
    ):
        assert await DeptService.get_dept_list_services(db, DeptModel(), scope)

    with patch.object(DeptDao, 'get_dept_list', new=AsyncMock(return_value=[root])):
        assert (await DeptService.check_dept_data_scope_services(db, 1, scope)).is_success
    with patch.object(DeptDao, 'get_dept_list', new=AsyncMock(return_value=[])):
        with expect_service_error('没有权限'):
            await DeptService.check_dept_data_scope_services(db, 1, scope)

    with patch.object(DeptDao, 'get_dept_detail_by_info', new=AsyncMock(return_value=SimpleNamespace(dept_id=2))):
        assert await DeptService.check_dept_name_unique_services(db, DeptModel(deptId=1, deptName='x')) is False
        assert await DeptService.check_dept_name_unique_services(db, DeptModel(deptId=2, deptName='x')) is True
    with patch.object(DeptDao, 'get_dept_detail_by_info', new=AsyncMock(return_value=None)):
        assert await DeptService.check_dept_name_unique_services(db, DeptModel(deptName='x')) is True

    page = DeptModel(deptName='n', parentId=1)
    with patch.object(DeptService, 'check_dept_name_unique_services', new=AsyncMock(return_value=False)):
        with expect_service_error('已存在'):
            await DeptService.add_dept_services(db, page)
    disabled_parent = SimpleNamespace(dept_name='p', status='1', ancestors='0')
    with (
        patch.object(DeptService, 'check_dept_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(DeptDao, 'get_dept_by_id', new=AsyncMock(return_value=disabled_parent)),
    ):
        with expect_service_error('停用'):
            await DeptService.add_dept_services(db, page)
    parent = SimpleNamespace(dept_name='p', status='0', ancestors='0')
    with (
        patch.object(DeptService, 'check_dept_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(DeptDao, 'get_dept_by_id', new=AsyncMock(return_value=parent)),
        patch.object(DeptDao, 'add_dept_dao', new=AsyncMock()),
    ):
        assert (await DeptService.add_dept_services(db, page)).is_success
    with (
        patch.object(DeptService, 'check_dept_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(DeptDao, 'get_dept_by_id', new=AsyncMock(return_value=parent)),
        patch.object(DeptDao, 'add_dept_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await DeptService.add_dept_services(db, page)

    edit = DeptModel(deptId=2, parentId=1, deptName='n', status='0', ancestors='0,1')
    with patch.object(DeptService, 'check_dept_name_unique_services', new=AsyncMock(return_value=False)):
        with expect_service_error('已存在'):
            await DeptService.edit_dept_services(db, edit)
    with (
        patch.object(DeptService, 'check_dept_name_unique_services', new=AsyncMock(return_value=True)),
        expect_service_error('上级部门不能是自己'),
    ):
        await DeptService.edit_dept_services(
            db, DeptModel(deptId=2, parentId=2, deptName='n', status='0')
        )
    with (
        patch.object(DeptService, 'check_dept_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(DeptDao, 'count_normal_children_dept_dao', new=AsyncMock(return_value=1)),
    ):
        with expect_service_error('未停用'):
            await DeptService.edit_dept_services(
                db, DeptModel(deptId=2, parentId=1, deptName='n', status='1')
            )
    new_p = SimpleNamespace(ancestors='0', dept_id=1)
    old_d = SimpleNamespace(ancestors='0,9')
    with (
        patch.object(DeptService, 'check_dept_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(DeptDao, 'count_normal_children_dept_dao', new=AsyncMock(return_value=0)),
        patch.object(DeptDao, 'get_dept_by_id', new=AsyncMock(side_effect=[new_p, old_d])),
        patch.object(DeptService, 'update_dept_children', new=AsyncMock()),
        patch.object(DeptDao, 'edit_dept_dao', new=AsyncMock()),
        patch.object(DeptService, 'update_parent_dept_status_normal', new=AsyncMock()),
    ):
        assert (await DeptService.edit_dept_services(db, edit)).is_success
    with (
        patch.object(DeptService, 'check_dept_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(DeptDao, 'get_dept_by_id', new=AsyncMock(side_effect=[new_p, old_d])),
        patch.object(DeptService, 'update_dept_children', new=AsyncMock()),
        patch.object(DeptDao, 'edit_dept_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await DeptService.edit_dept_services(db, edit)

    with expect_service_error('为空'):
        await DeptService.delete_dept_services(db, DeleteDeptModel(deptIds=''))
    with patch.object(DeptDao, 'count_children_dept_dao', new=AsyncMock(return_value=1)):
        with expect_service_warning('下级部门'):
            await DeptService.delete_dept_services(db, DeleteDeptModel(deptIds='2'))
    with (
        patch.object(DeptDao, 'count_children_dept_dao', new=AsyncMock(return_value=0)),
        patch.object(DeptDao, 'count_dept_user_dao', new=AsyncMock(return_value=1)),
    ):
        with expect_service_warning('存在用户'):
            await DeptService.delete_dept_services(db, DeleteDeptModel(deptIds='2'))
    with (
        patch.object(DeptDao, 'count_children_dept_dao', new=AsyncMock(return_value=0)),
        patch.object(DeptDao, 'count_dept_user_dao', new=AsyncMock(return_value=0)),
        patch.object(DeptDao, 'delete_dept_dao', new=AsyncMock()),
    ):
        assert (await DeptService.delete_dept_services(db, DeleteDeptModel(deptIds='2'))).is_success
    with (
        patch.object(DeptDao, 'count_children_dept_dao', new=AsyncMock(return_value=0)),
        patch.object(DeptDao, 'count_dept_user_dao', new=AsyncMock(return_value=0)),
        patch.object(DeptDao, 'delete_dept_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await DeptService.delete_dept_services(db, DeleteDeptModel(deptIds='2'))

    with (
        patch.object(DeptDao, 'get_dept_detail_by_id', new=AsyncMock(return_value=object())),
        patch(
            'module_admin.service.dept_service.CamelCaseUtil.transform_result',
            return_value={'deptId': 1, 'deptName': 'r'},
        ),
    ):
        assert (await DeptService.dept_detail_services(db, 1)).dept_id == 1
    with patch.object(DeptDao, 'get_dept_detail_by_id', new=AsyncMock(return_value=None)):
        assert (await DeptService.dept_detail_services(db, 1)).dept_id is None

    assert await DeptService.replace_first('0,1,2', '0,1', '0,9') == '0,9,2'
    assert await DeptService.replace_first('x0,1', '0,1', '0,9') == 'x0,1'

    with patch.object(DeptDao, 'update_dept_status_normal_dao', new=AsyncMock()) as m:
        await DeptService.update_parent_dept_status_normal(db, DeptModel(ancestors='1,2'))
        m.assert_awaited()

    kids = [SimpleNamespace(dept_id=3, ancestors='0,1,2')]
    with (
        patch.object(DeptDao, 'get_children_dept_dao', new=AsyncMock(return_value=kids)),
        patch.object(DeptDao, 'update_dept_children_dao', new=AsyncMock()) as m2,
    ):
        await DeptService.update_dept_children(db, 2, '0,9', '0,1')
        m2.assert_awaited()
    with patch.object(DeptDao, 'get_children_dept_dao', new=AsyncMock(return_value=[])):
        await DeptService.update_dept_children(db, 2, '0,9', '0,1')

    # dao paths — build a fresh session mock per call style
    async def _run_dept_dao() -> None:
        d = _db()
        d.execute = AsyncMock(return_value=_scalars_first(root))
        await DeptDao.get_dept_by_id(d, 1)
        await DeptDao.get_dept_detail_by_id(d, 1)
        await DeptDao.get_dept_detail_by_info(d, DeptModel(deptName='n', parentId=1))
        await DeptDao.get_dept_detail_by_info(d, DeptModel())
        d.execute = AsyncMock(return_value=_scalars_all([root]))
        await DeptDao.get_dept_info_for_edit_option(d, DeptModel(deptId=2), scope)
        await DeptDao.get_children_dept_dao(d, 1)
        await DeptDao.get_dept_list_for_tree(d, DeptModel(deptName='r'), scope)
        await DeptDao.get_dept_list_for_tree(d, DeptModel(), scope)
        await DeptDao.get_dept_list(d, DeptModel(deptId=1, status='0', deptName='r'), scope)
        await DeptDao.get_dept_list(d, DeptModel(), scope)
        d.add = MagicMock()
        d.flush = AsyncMock()
        await DeptDao.add_dept_dao(d, DeptModel(deptName='n', parentId=0, orderNum=1))
        d.execute = AsyncMock(return_value=MagicMock())
        await DeptDao.edit_dept_dao(d, {'dept_id': 1})
        await DeptDao.update_dept_children_dao(d, [{'dept_id': 2, 'ancestors': '0,1'}])
        await DeptDao.update_dept_status_normal_dao(d, [1, 2])
        await DeptDao.delete_dept_dao(d, DeptModel(deptId=2))
        d.execute = AsyncMock(return_value=_scalar(3))
        assert await DeptDao.count_normal_children_dept_dao(d, 1) == 3
        assert await DeptDao.count_children_dept_dao(d, 1) == 3
        assert await DeptDao.count_dept_user_dao(d, 1) == 3

    await _run_dept_dao()


# ---------------------------------------------------------------------------
# menu service + dao
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_menu_service_and_dao() -> None:
    db = _db()
    cu = _current_user()
    m1 = SimpleNamespace(menu_id=1, menu_name='系统', parent_id=0)
    m2 = SimpleNamespace(menu_id=2, menu_name='用户', parent_id=1)

    with patch.object(MenuDao, 'get_menu_list_for_tree', new=AsyncMock(return_value=[m1, m2])):
        tree = await MenuService.get_menu_tree_services(db, cu)
        assert tree[0]['id'] == 1

    role = SimpleNamespace(role_id=2, menu_check_strictly=True)
    with (
        patch.object(MenuDao, 'get_menu_list_for_tree', new=AsyncMock(return_value=[m1])),
        patch('module_admin.service.menu_service.RoleDao.get_role_detail_by_id', new=AsyncMock(return_value=role)),
        patch(
            'module_admin.service.menu_service.RoleDao.get_role_menu_dao',
            new=AsyncMock(return_value=[SimpleNamespace(menu_id=1)]),
        ),
    ):
        r = await MenuService.get_role_menu_tree_services(db, 2, cu)
        assert r.checked_keys == [1]

    with (
        patch.object(MenuDao, 'get_menu_list', new=AsyncMock(return_value=[m1])),
        patch('module_admin.service.menu_service.CamelCaseUtil.transform_result', return_value=[{'menuId': 1}]),
    ):
        assert await MenuService.get_menu_list_services(db, MenuQueryModel(), cu)

    with patch.object(MenuDao, 'get_menu_detail_by_info', new=AsyncMock(return_value=SimpleNamespace(menu_id=2))):
        assert await MenuService.check_menu_name_unique_services(db, MenuModel(menuId=1, menuName='x')) is False
        assert await MenuService.check_menu_name_unique_services(db, MenuModel(menuId=2, menuName='x')) is True
    with patch.object(MenuDao, 'get_menu_detail_by_info', new=AsyncMock(return_value=None)):
        assert await MenuService.check_menu_name_unique_services(db, MenuModel(menuName='x')) is True

    page = MenuModel(menuName='n', path='path', isFrame=1)
    with patch.object(MenuService, 'check_menu_name_unique_services', new=AsyncMock(return_value=False)):
        with expect_service_error('已存在'):
            await MenuService.add_menu_services(db, page)
    with (
        patch.object(MenuService, 'check_menu_name_unique_services', new=AsyncMock(return_value=True)),
    ):
        with expect_service_error('http'):
            await MenuService.add_menu_services(db, MenuModel(menuName='n', path='bad', isFrame=0))
    with (
        patch.object(MenuService, 'check_menu_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(MenuDao, 'add_menu_dao', new=AsyncMock()),
    ):
        assert (
            await MenuService.add_menu_services(db, MenuModel(menuName='n', path='https://a.com', isFrame=0))
        ).is_success
    with (
        patch.object(MenuService, 'check_menu_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(MenuDao, 'add_menu_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await MenuService.add_menu_services(db, MenuModel(menuName='n', path='p', isFrame=1))

    edit = MenuModel(menuId=2, parentId=1, menuName='n', path='p', isFrame=1)
    with patch.object(MenuService, 'menu_detail_services', new=AsyncMock(return_value=MenuModel())):
        with expect_service_error('不存在'):
            await MenuService.edit_menu_services(db, edit)
    with (
        patch.object(MenuService, 'menu_detail_services', new=AsyncMock(return_value=MenuModel(menuId=2))),
        patch.object(MenuService, 'check_menu_name_unique_services', new=AsyncMock(return_value=False)),
    ):
        with expect_service_error('已存在'):
            await MenuService.edit_menu_services(db, edit)
    with (
        patch.object(MenuService, 'menu_detail_services', new=AsyncMock(return_value=MenuModel(menuId=2))),
        patch.object(MenuService, 'check_menu_name_unique_services', new=AsyncMock(return_value=True)),
    ):
        with expect_service_error('http'):
            await MenuService.edit_menu_services(db, MenuModel(menuId=2, parentId=1, menuName='n', path='x', isFrame=0))
    with (
        patch.object(MenuService, 'menu_detail_services', new=AsyncMock(return_value=MenuModel(menuId=2))),
        patch.object(MenuService, 'check_menu_name_unique_services', new=AsyncMock(return_value=True)),
    ):
        with expect_service_error('上级菜单'):
            await MenuService.edit_menu_services(db, MenuModel(menuId=2, parentId=2, menuName='n', path='p', isFrame=1))
    with (
        patch.object(MenuService, 'menu_detail_services', new=AsyncMock(return_value=MenuModel(menuId=2))),
        patch.object(MenuService, 'check_menu_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(MenuDao, 'edit_menu_dao', new=AsyncMock()),
    ):
        assert (await MenuService.edit_menu_services(db, edit)).is_success
    with (
        patch.object(MenuService, 'menu_detail_services', new=AsyncMock(return_value=MenuModel(menuId=2))),
        patch.object(MenuService, 'check_menu_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(MenuDao, 'edit_menu_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await MenuService.edit_menu_services(db, edit)

    with expect_service_error('为空'):
        await MenuService.delete_menu_services(db, DeleteMenuModel(menuIds=''))
    with patch.object(MenuDao, 'has_child_by_menu_id_dao', new=AsyncMock(return_value=1)):
        with expect_service_warning('子菜单'):
            await MenuService.delete_menu_services(db, DeleteMenuModel(menuIds='1'))
    with (
        patch.object(MenuDao, 'has_child_by_menu_id_dao', new=AsyncMock(return_value=0)),
        patch.object(MenuDao, 'check_menu_exist_role_dao', new=AsyncMock(return_value=1)),
    ):
        with expect_service_warning('已分配'):
            await MenuService.delete_menu_services(db, DeleteMenuModel(menuIds='1'))
    with (
        patch.object(MenuDao, 'has_child_by_menu_id_dao', new=AsyncMock(return_value=0)),
        patch.object(MenuDao, 'check_menu_exist_role_dao', new=AsyncMock(return_value=0)),
        patch.object(MenuDao, 'delete_menu_dao', new=AsyncMock()),
    ):
        assert (await MenuService.delete_menu_services(db, DeleteMenuModel(menuIds='1'))).is_success
    with (
        patch.object(MenuDao, 'has_child_by_menu_id_dao', new=AsyncMock(return_value=0)),
        patch.object(MenuDao, 'check_menu_exist_role_dao', new=AsyncMock(return_value=0)),
        patch.object(MenuDao, 'delete_menu_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await MenuService.delete_menu_services(db, DeleteMenuModel(menuIds='1'))

    with (
        patch.object(MenuDao, 'get_menu_detail_by_id', new=AsyncMock(return_value=object())),
        patch(
            'module_admin.service.menu_service.CamelCaseUtil.transform_result',
            return_value={'menuId': 1, 'menuName': 'm'},
        ),
    ):
        assert (await MenuService.menu_detail_services(db, 1)).menu_id == 1
    with patch.object(MenuDao, 'get_menu_detail_by_id', new=AsyncMock(return_value=None)):
        assert (await MenuService.menu_detail_services(db, 1)).menu_id is None

    # dao
    db.execute = AsyncMock(return_value=_scalars_first(m1))
    await MenuDao.get_menu_detail_by_id(db, 1)
    await MenuDao.get_menu_detail_by_info(db, MenuModel(menuName='m', parentId=0, menuType='M'))
    await MenuDao.get_menu_detail_by_info(db, MenuModel())
    db.execute = AsyncMock(return_value=_scalars_all([m1]))
    await MenuDao.get_menu_list_for_tree(db, 1, [SimpleNamespace(role_id=1)])
    await MenuDao.get_menu_list_for_tree(db, 2, [SimpleNamespace(role_id=2)])
    await MenuDao.get_menu_list(db, MenuQueryModel(status='0', menuName='m'), 1, [SimpleNamespace(role_id=1)])
    await MenuDao.get_menu_list(db, MenuQueryModel(), 2, [SimpleNamespace(role_id=2)])
    db.add = MagicMock()
    db.flush = AsyncMock()
    await MenuDao.add_menu_dao(db, MenuModel(menuName='m'))
    db.execute = AsyncMock()
    await MenuDao.edit_menu_dao(db, {'menu_id': 1})
    await MenuDao.delete_menu_dao(db, MenuModel(menuId=1))
    db.execute = AsyncMock(return_value=_scalar(1))
    assert await MenuDao.has_child_by_menu_id_dao(db, 1) == 1
    assert await MenuDao.check_menu_exist_role_dao(db, 1) == 1
