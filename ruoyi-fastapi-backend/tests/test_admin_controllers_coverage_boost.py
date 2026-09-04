"""Raise module_admin.controller coverage by calling route handlers directly with mocked deps."""

from __future__ import annotations

import inspect
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks, Request, UploadFile

from common.vo import CrudResponseModel
from module_admin.entity.vo.cache_vo import CacheInfoModel
from module_admin.entity.vo.config_vo import ConfigModel, ConfigPageQueryModel
from module_admin.entity.vo.dept_vo import DeptModel, DeptQueryModel
from module_admin.entity.vo.dict_vo import DictDataModel, DictDataPageQueryModel, DictTypeModel, DictTypePageQueryModel
from module_admin.entity.vo.job_vo import EditJobModel, JobLogPageQueryModel, JobModel, JobPageQueryModel
from module_admin.entity.vo.log_vo import LoginLogPageQueryModel, OperLogPageQueryModel
from module_admin.entity.vo.login_vo import UserRegister
from module_admin.entity.vo.menu_vo import MenuModel, MenuQueryModel
from module_admin.entity.vo.notice_vo import NoticeModel, NoticePageQueryModel
from module_admin.entity.vo.online_vo import OnlineQueryModel
from module_admin.entity.vo.post_vo import PostModel, PostPageQueryModel
from module_admin.entity.vo.role_vo import AddRoleModel, RoleDeptQueryModel, RoleModel, RolePageQueryModel
from module_admin.entity.vo.user_vo import (
    AddUserModel,
    CrudUserRoleModel,
    CurrentUserModel,
    EditUserModel,
    ResetPasswordModel,
    UserDetailModel,
    UserInfoModel,
    UserPageQueryModel,
    UserProfileModel,
    UserRoleResponseModel,
)
from module_admin.service.cache_service import CacheService
from module_admin.service.captcha_service import CaptchaService
from module_admin.service.common_service import CommonService
from module_admin.service.config_service import ConfigService
from module_admin.service.dept_service import DeptService
from module_admin.service.dict_service import DictDataService, DictTypeService
from module_admin.service.health_service import HealthService
from module_admin.service.job_log_service import JobLogService
from module_admin.service.job_service import JobService
from module_admin.service.log_service import LoginLogService, OperationLogService
from module_admin.service.login_service import LoginService
from module_admin.service.menu_service import MenuService
from module_admin.service.notice_service import NoticeService
from module_admin.service.online_service import OnlineService
from module_admin.service.post_service import PostService
from module_admin.service.role_service import RoleService
from module_admin.service.server_service import ServerService
from module_admin.service.transport_crypto_service import TransportCryptoService
from module_admin.service.user_service import UserService


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _unwrap(fn):
    """Bypass ApiCache / ApiRateLimit / Log wrappers so handlers are callable offline."""
    return inspect.unwrap(fn)


async def _empty_receive():
    return {'type': 'http.request', 'body': b'', 'more_body': False}


def _request(*, redis: object | None = None, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    redis = redis if redis is not None else AsyncMock()
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
        'headers': headers or [],
        'client': ('127.0.0.1', 1),
        'server': ('test', 80),
        'root_path': '',
        'app': app,
    }
    return Request(scope, _empty_receive)


def _db() -> AsyncMock:
    return AsyncMock()


def _crud(msg: str = 'ok') -> CrudResponseModel:
    return CrudResponseModel(is_success=True, message=msg)


def _admin() -> CurrentUserModel:
    return CurrentUserModel(
        permissions=[],
        roles=[],
        user=UserInfoModel(userId=1, userName='admin', nickName='a', admin=True, roleIds='1', postIds='1'),
    )


def _user(uid: int = 2) -> CurrentUserModel:
    return CurrentUserModel(
        permissions=[],
        roles=[],
        user=UserInfoModel(userId=uid, userName='u', nickName='n', admin=False, roleIds='', postIds=''),
    )


def _page():
    page = MagicMock()
    page.model_dump.return_value = {'rows': [], 'total': 0, 'pageNum': 1, 'pageSize': 10, 'hasNext': False}
    return page


# ---------------------------------------------------------------------------
# small controllers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_and_captcha_and_server() -> None:
    from module_admin.controller.health_controller import health
    health = _unwrap(health)
    from module_admin.controller.captcha_controller import get_captcha_image
    get_captcha_image = _unwrap(get_captcha_image)
    from module_admin.controller.server_controller import get_monitor_server_info
    get_monitor_server_info = _unwrap(get_monitor_server_info)

    req = _request()
    with patch.object(HealthService, 'check', new=AsyncMock(return_value=({'status': 'up'}, 200))):
        resp = await health(req)
        assert resp.status_code == 200

    with patch.object(CaptchaService, 'build_captcha_code', new=AsyncMock(return_value=MagicMock())):
        assert await get_captcha_image(req)

    with patch.object(ServerService, 'get_server_monitor_info', new=AsyncMock(return_value={'cpu': 1})):
        assert await get_monitor_server_info(req)


@pytest.mark.asyncio
async def test_cache_controller_all() -> None:
    from module_admin.controller.cache_controller import (
        clear_monitor_cache_all,
        clear_monitor_cache_key,
        clear_monitor_cache_name,
        get_monitor_cache_info,
        get_monitor_cache_key,
        get_monitor_cache_name,
        get_monitor_cache_value,
    )
    clear_monitor_cache_all = _unwrap(clear_monitor_cache_all)
    clear_monitor_cache_key = _unwrap(clear_monitor_cache_key)
    clear_monitor_cache_name = _unwrap(clear_monitor_cache_name)
    get_monitor_cache_info = _unwrap(get_monitor_cache_info)
    get_monitor_cache_key = _unwrap(get_monitor_cache_key)
    get_monitor_cache_name = _unwrap(get_monitor_cache_name)
    get_monitor_cache_value = _unwrap(get_monitor_cache_value)


    req = _request()
    with patch.object(CacheService, 'get_cache_monitor_statistical_info_services', new=AsyncMock(return_value={})):
        assert await get_monitor_cache_info(req)
    with patch.object(CacheService, 'get_cache_monitor_cache_name_services', new=AsyncMock(return_value=[])):
        assert await get_monitor_cache_name(req)
    with patch.object(CacheService, 'get_cache_monitor_cache_key_services', new=AsyncMock(return_value=[])):
        assert await get_monitor_cache_key(req, 'n')
    with patch.object(
        CacheService, 'get_cache_monitor_cache_value_services', new=AsyncMock(return_value=CacheInfoModel())
    ):
        assert await get_monitor_cache_value(req, 'n', 'k')
    with patch.object(CacheService, 'clear_cache_monitor_cache_name_services', new=AsyncMock(return_value=_crud())):
        assert await clear_monitor_cache_name(req, 'n')
    with patch.object(CacheService, 'clear_cache_monitor_cache_key_services', new=AsyncMock(return_value=_crud())):
        assert await clear_monitor_cache_key(req, 'k')
    with patch.object(CacheService, 'clear_cache_monitor_all_services', new=AsyncMock(return_value=_crud())):
        assert await clear_monitor_cache_all(req)


@pytest.mark.asyncio
async def test_common_and_online_and_transport() -> None:
    from module_admin.controller.common_controller import common_download, common_download_resource, common_upload
    from module_admin.controller.online_controller import delete_monitor_online, get_monitor_online_list
    from module_admin.controller.transport_crypto_controller import (
        get_transport_crypto_monitor_info,
        get_transport_frontend_config,
        get_transport_public_key,
    )

    common_download = _unwrap(common_download)
    common_download_resource = _unwrap(common_download_resource)
    common_upload = _unwrap(common_upload)
    delete_monitor_online = _unwrap(delete_monitor_online)
    get_monitor_online_list = _unwrap(get_monitor_online_list)
    get_transport_crypto_monitor_info = _unwrap(get_transport_crypto_monitor_info)
    get_transport_frontend_config = _unwrap(get_transport_frontend_config)
    get_transport_public_key = _unwrap(get_transport_public_key)


    req = _request()
    db = _db()
    file = UploadFile(filename='a.txt', file=BytesIO(b'x'))
    with patch.object(
        CommonService, 'upload_service', new=AsyncMock(return_value=SimpleNamespace(result=MagicMock()))
    ):
        assert await common_upload(req, file)
    with patch.object(
        CommonService,
        'download_services',
        new=AsyncMock(return_value=SimpleNamespace(message='ok', result=BytesIO(b'x'))),
    ):
        assert await common_download(req, BackgroundTasks(), 'a.txt', False)
    with patch.object(
        CommonService,
        'download_resource_services',
        new=AsyncMock(return_value=SimpleNamespace(message='ok', result=BytesIO(b'x'))),
    ):
        assert await common_download_resource(req, 'r')

    with patch.object(OnlineService, 'get_online_list_services', new=AsyncMock(return_value=[])):
        assert await get_monitor_online_list(req, OnlineQueryModel())
    with patch.object(OnlineService, 'delete_online_services', new=AsyncMock(return_value=_crud())):
        assert await delete_monitor_online(req, 't1', db)

    with patch.object(TransportCryptoService, 'get_transport_frontend_config_services', new=AsyncMock(return_value={})):
        assert await get_transport_frontend_config(req)
    with patch.object(TransportCryptoService, 'get_transport_public_key_services', new=AsyncMock(return_value={})):
        assert await get_transport_public_key(req)
    with patch.object(
        TransportCryptoService, 'get_transport_crypto_monitor_info_services', new=AsyncMock(return_value={})
    ):
        assert await get_transport_crypto_monitor_info(req)


# ---------------------------------------------------------------------------
# config / notice / post / menu / dept
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_controller_all() -> None:
    from module_admin.controller.config_controller import (
        add_system_config,
        delete_system_config,
        edit_system_config,
        export_system_config_list,
        get_system_config_list,
        query_detail_system_config,
        query_system_config,
        refresh_system_config,
    )
    add_system_config = _unwrap(add_system_config)
    delete_system_config = _unwrap(delete_system_config)
    edit_system_config = _unwrap(edit_system_config)
    export_system_config_list = _unwrap(export_system_config_list)
    get_system_config_list = _unwrap(get_system_config_list)
    query_detail_system_config = _unwrap(query_detail_system_config)
    query_system_config = _unwrap(query_system_config)
    refresh_system_config = _unwrap(refresh_system_config)


    req = _request()
    db = _db()
    cu = _admin()
    cfg = ConfigModel(configKey='k', configName='n', configValue='v')
    with patch.object(ConfigService, 'get_config_list_services', new=AsyncMock(return_value=_page())):
        assert await get_system_config_list(req, ConfigPageQueryModel(), db)
    with patch.object(ConfigService, 'add_config_services', new=AsyncMock(return_value=_crud())):
        assert await add_system_config(req, cfg, db, cu)
    with patch.object(ConfigService, 'edit_config_services', new=AsyncMock(return_value=_crud())):
        assert await edit_system_config(req, cfg, db, cu)
    with patch.object(ConfigService, 'refresh_sys_config_services', new=AsyncMock(return_value=_crud())):
        assert await refresh_system_config(req, db)
    with patch.object(ConfigService, 'delete_config_services', new=AsyncMock(return_value=_crud())):
        assert await delete_system_config(req, '1', db)
    with patch.object(ConfigService, 'config_detail_services', new=AsyncMock(return_value=cfg)):
        assert await query_detail_system_config(req, 1, db)
    with patch.object(ConfigService, 'query_config_list_from_cache_services', new=AsyncMock(return_value='v')):
        assert await query_system_config(req, 'k')
    with (
        patch.object(ConfigService, 'get_config_list_services', new=AsyncMock(return_value=[])),
        patch.object(ConfigService, 'export_config_list_services', new=AsyncMock(return_value=b'x')),
    ):
        assert await export_system_config_list(req, ConfigPageQueryModel(), db)


@pytest.mark.asyncio
async def test_notice_post_menu_dept_controllers() -> None:
    from module_admin.controller.notice_controller import (
        add_system_notice,
        delete_system_notice,
        edit_system_notice,
        get_system_notice_list,
        query_detail_system_post as query_notice,
    )
    add_system_notice = _unwrap(add_system_notice)
    delete_system_notice = _unwrap(delete_system_notice)
    edit_system_notice = _unwrap(edit_system_notice)
    get_system_notice_list = _unwrap(get_system_notice_list)
    query_notice = _unwrap(query_notice)

    from module_admin.controller.post_controller import (
        add_system_post,
        delete_system_post,
        edit_system_post,
        export_system_post_list,
        get_system_post_list,
        query_detail_system_post,
    )
    add_system_post = _unwrap(add_system_post)
    delete_system_post = _unwrap(delete_system_post)
    edit_system_post = _unwrap(edit_system_post)
    export_system_post_list = _unwrap(export_system_post_list)
    get_system_post_list = _unwrap(get_system_post_list)
    query_detail_system_post = _unwrap(query_detail_system_post)

    from module_admin.controller.menu_controller import (
        add_system_menu,
        delete_system_menu,
        edit_system_menu,
        get_system_menu_list,
        get_system_menu_tree,
        get_system_role_menu_tree,
        query_detail_system_menu,
    )
    add_system_menu = _unwrap(add_system_menu)
    delete_system_menu = _unwrap(delete_system_menu)
    edit_system_menu = _unwrap(edit_system_menu)
    get_system_menu_list = _unwrap(get_system_menu_list)
    get_system_menu_tree = _unwrap(get_system_menu_tree)
    get_system_role_menu_tree = _unwrap(get_system_role_menu_tree)
    query_detail_system_menu = _unwrap(query_detail_system_menu)

    from module_admin.controller.dept_controller import (
        add_system_dept,
        delete_system_dept,
        edit_system_dept,
        get_system_dept_list,
        get_system_dept_tree_for_edit_option,
        query_detail_system_dept,
    )
    add_system_dept = _unwrap(add_system_dept)
    delete_system_dept = _unwrap(delete_system_dept)
    edit_system_dept = _unwrap(edit_system_dept)
    get_system_dept_list = _unwrap(get_system_dept_list)
    get_system_dept_tree_for_edit_option = _unwrap(get_system_dept_tree_for_edit_option)
    query_detail_system_dept = _unwrap(query_detail_system_dept)


    req = _request()
    db = _db()
    scope = MagicMock()
    admin = _admin()
    user = _user()
    notice = NoticeModel(noticeTitle='t', noticeType='1', noticeContent='c')
    with patch.object(NoticeService, 'get_notice_list_services', new=AsyncMock(return_value=_page())):
        assert await get_system_notice_list(req, NoticePageQueryModel(), db)
    with patch.object(NoticeService, 'add_notice_services', new=AsyncMock(return_value=_crud())):
        assert await add_system_notice(req, notice, db, admin)
    with patch.object(NoticeService, 'edit_notice_services', new=AsyncMock(return_value=_crud())):
        assert await edit_system_notice(req, notice, db, admin)
    with patch.object(NoticeService, 'delete_notice_services', new=AsyncMock(return_value=_crud())):
        assert await delete_system_notice(req, '1', db)
    with patch.object(NoticeService, 'notice_detail_services', new=AsyncMock(return_value=notice)):
        assert await query_notice(req, 1, db)

    post = PostModel(postCode='c', postName='n', postSort=1)
    with patch.object(PostService, 'get_post_list_services', new=AsyncMock(return_value=_page())):
        assert await get_system_post_list(req, PostPageQueryModel(), db)
    with patch.object(PostService, 'add_post_services', new=AsyncMock(return_value=_crud())):
        assert await add_system_post(req, post, db, admin)
    with patch.object(PostService, 'edit_post_services', new=AsyncMock(return_value=_crud())):
        assert await edit_system_post(req, post, db, admin)
    with patch.object(PostService, 'delete_post_services', new=AsyncMock(return_value=_crud())):
        assert await delete_system_post(req, '1', db)
    with patch.object(PostService, 'post_detail_services', new=AsyncMock(return_value=post)):
        assert await query_detail_system_post(req, 1, db)
    with (
        patch.object(PostService, 'get_post_list_services', new=AsyncMock(return_value=[])),
        patch.object(PostService, 'export_post_list_services', new=AsyncMock(return_value=b'x')),
    ):
        assert await export_system_post_list(req, PostPageQueryModel(), db)

    menu = MenuModel(menuName='m', orderNum=1, menuType='C')
    with patch.object(MenuService, 'get_menu_tree_services', new=AsyncMock(return_value=[])):
        assert await get_system_menu_tree(req, db, admin)
    with patch.object(MenuService, 'get_role_menu_tree_services', new=AsyncMock(return_value=MagicMock())):
        assert await get_system_role_menu_tree(req, 1, db, admin)
    with patch.object(MenuService, 'get_menu_list_services', new=AsyncMock(return_value=[])):
        assert await get_system_menu_list(req, MenuQueryModel(), db, admin)
    with patch.object(MenuService, 'add_menu_services', new=AsyncMock(return_value=_crud())):
        assert await add_system_menu(req, menu, db, admin)
    with patch.object(MenuService, 'edit_menu_services', new=AsyncMock(return_value=_crud())):
        assert await edit_system_menu(req, menu, db, admin)
    with patch.object(MenuService, 'delete_menu_services', new=AsyncMock(return_value=_crud())):
        assert await delete_system_menu(req, '1', db)
    with patch.object(MenuService, 'menu_detail_services', new=AsyncMock(return_value=menu)):
        assert await query_detail_system_menu(req, 1, db)

    dept = DeptModel(deptName='d', orderNum=1)
    with patch.object(DeptService, 'get_dept_for_edit_option_services', new=AsyncMock(return_value=[])):
        assert await get_system_dept_tree_for_edit_option(req, 1, db, scope)
    with patch.object(DeptService, 'get_dept_list_services', new=AsyncMock(return_value=[])):
        assert await get_system_dept_list(req, DeptQueryModel(), db, scope)
    with patch.object(DeptService, 'add_dept_services', new=AsyncMock(return_value=_crud())):
        assert await add_system_dept(req, dept, db, admin)
    with patch.object(DeptService, 'edit_dept_services', new=AsyncMock(return_value=_crud())):
        assert await edit_system_dept(req, DeptModel(deptId=2, deptName='d', orderNum=1), db, admin, scope)
    with (
        patch.object(DeptService, 'check_dept_data_scope_services', new=AsyncMock()),
        patch.object(DeptService, 'edit_dept_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await edit_system_dept(req, DeptModel(deptId=2, deptName='d', orderNum=1), db, user, scope)
    with patch.object(DeptService, 'delete_dept_services', new=AsyncMock(return_value=_crud())):
        assert await delete_system_dept(req, '2,3', db, admin, scope)
        assert await delete_system_dept(req, '', db, admin, scope)
    with (
        patch.object(DeptService, 'check_dept_data_scope_services', new=AsyncMock()),
        patch.object(DeptService, 'delete_dept_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await delete_system_dept(req, '2', db, user, scope)
    with patch.object(DeptService, 'dept_detail_services', new=AsyncMock(return_value=dept)):
        assert await query_detail_system_dept(req, 2, db, admin, scope)
    with (
        patch.object(DeptService, 'check_dept_data_scope_services', new=AsyncMock()),
        patch.object(DeptService, 'dept_detail_services', new=AsyncMock(return_value=dept)),
    ):
        assert await query_detail_system_dept(req, 2, db, user, scope)


# ---------------------------------------------------------------------------
# dict / job / log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dict_controller_all() -> None:
    from module_admin.controller.dict_controller import (
        add_system_dict_data,
        add_system_dict_type,
        delete_system_dict_data,
        delete_system_dict_type,
        edit_system_dict_data,
        edit_system_dict_type,
        export_system_dict_data_list,
        export_system_dict_type_list,
        get_system_dict_data_list,
        get_system_dict_type_list,
        query_detail_system_dict_data,
        query_detail_system_dict_type,
        query_system_dict_type_data,
        query_system_dict_type_options,
        refresh_system_dict,
    )
    add_system_dict_data = _unwrap(add_system_dict_data)
    add_system_dict_type = _unwrap(add_system_dict_type)
    delete_system_dict_data = _unwrap(delete_system_dict_data)
    delete_system_dict_type = _unwrap(delete_system_dict_type)
    edit_system_dict_data = _unwrap(edit_system_dict_data)
    edit_system_dict_type = _unwrap(edit_system_dict_type)
    export_system_dict_data_list = _unwrap(export_system_dict_data_list)
    export_system_dict_type_list = _unwrap(export_system_dict_type_list)
    get_system_dict_data_list = _unwrap(get_system_dict_data_list)
    get_system_dict_type_list = _unwrap(get_system_dict_type_list)
    query_detail_system_dict_data = _unwrap(query_detail_system_dict_data)
    query_detail_system_dict_type = _unwrap(query_detail_system_dict_type)
    query_system_dict_type_data = _unwrap(query_system_dict_type_data)
    query_system_dict_type_options = _unwrap(query_system_dict_type_options)
    refresh_system_dict = _unwrap(refresh_system_dict)


    req = _request()
    db = _db()
    cu = _admin()
    dt = DictTypeModel(dictName='n', dictType='t')
    dd = DictDataModel(dictLabel='l', dictValue='v', dictType='t')
    with patch.object(DictTypeService, 'get_dict_type_list_services', new=AsyncMock(return_value=_page())):
        assert await get_system_dict_type_list(req, DictTypePageQueryModel(), db)
    with patch.object(DictTypeService, 'add_dict_type_services', new=AsyncMock(return_value=_crud())):
        assert await add_system_dict_type(req, dt, db, cu)
    with patch.object(DictTypeService, 'edit_dict_type_services', new=AsyncMock(return_value=_crud())):
        assert await edit_system_dict_type(req, dt, db, cu)
    with patch.object(DictTypeService, 'refresh_sys_dict_services', new=AsyncMock(return_value=_crud())):
        assert await refresh_system_dict(req, db)
    with patch.object(DictTypeService, 'delete_dict_type_services', new=AsyncMock(return_value=_crud())):
        assert await delete_system_dict_type(req, '1', db)
    with patch.object(DictTypeService, 'get_dict_type_list_services', new=AsyncMock(return_value=[])):
        assert await query_system_dict_type_options(req, db)
    with patch.object(DictTypeService, 'dict_type_detail_services', new=AsyncMock(return_value=dt)):
        assert await query_detail_system_dict_type(req, 1, db)
    with (
        patch.object(DictTypeService, 'get_dict_type_list_services', new=AsyncMock(return_value=[])),
        patch.object(DictTypeService, 'export_dict_type_list_services', new=AsyncMock(return_value=b'x')),
    ):
        assert await export_system_dict_type_list(req, DictTypePageQueryModel(), db)
    with patch.object(DictDataService, 'query_dict_data_list_from_cache_services', new=AsyncMock(return_value=[])):
        assert await query_system_dict_type_data(req, 't', db)
    with patch.object(DictDataService, 'get_dict_data_list_services', new=AsyncMock(return_value=_page())):
        assert await get_system_dict_data_list(req, DictDataPageQueryModel(), db)
    with patch.object(DictDataService, 'add_dict_data_services', new=AsyncMock(return_value=_crud())):
        assert await add_system_dict_data(req, dd, db, cu)
    with patch.object(DictDataService, 'edit_dict_data_services', new=AsyncMock(return_value=_crud())):
        assert await edit_system_dict_data(req, dd, db, cu)
    with patch.object(DictDataService, 'delete_dict_data_services', new=AsyncMock(return_value=_crud())):
        assert await delete_system_dict_data(req, '1', db)
    with patch.object(DictDataService, 'dict_data_detail_services', new=AsyncMock(return_value=dd)):
        assert await query_detail_system_dict_data(req, 1, db)
    with (
        patch.object(DictDataService, 'get_dict_data_list_services', new=AsyncMock(return_value=[])),
        patch.object(DictDataService, 'export_dict_data_list_services', new=AsyncMock(return_value=b'x')),
    ):
        assert await export_system_dict_data_list(req, DictDataPageQueryModel(), db)


@pytest.mark.asyncio
async def test_job_and_log_controllers() -> None:
    from module_admin.controller.job_controller import (
        add_system_job,
        change_system_job_status,
        clear_system_job_log,
        delete_system_job,
        delete_system_job_log,
        edit_system_job,
        execute_system_job,
        export_system_job_list,
        export_system_job_log_list,
        get_system_job_list,
        get_system_job_log_list,
        query_detail_system_job,
    )
    add_system_job = _unwrap(add_system_job)
    change_system_job_status = _unwrap(change_system_job_status)
    clear_system_job_log = _unwrap(clear_system_job_log)
    delete_system_job = _unwrap(delete_system_job)
    delete_system_job_log = _unwrap(delete_system_job_log)
    edit_system_job = _unwrap(edit_system_job)
    execute_system_job = _unwrap(execute_system_job)
    export_system_job_list = _unwrap(export_system_job_list)
    export_system_job_log_list = _unwrap(export_system_job_log_list)
    get_system_job_list = _unwrap(get_system_job_list)
    get_system_job_log_list = _unwrap(get_system_job_log_list)
    query_detail_system_job = _unwrap(query_detail_system_job)

    from module_admin.controller.log_controller import (
        clear_system_login_log,
        clear_system_operation_log,
        delete_system_login_log,
        delete_system_operation_log,
        export_system_login_log_list,
        export_system_operation_log_list,
        get_system_login_log_list,
        get_system_operation_log_list,
        unlock_system_user,
    )
    clear_system_login_log = _unwrap(clear_system_login_log)
    clear_system_operation_log = _unwrap(clear_system_operation_log)
    delete_system_login_log = _unwrap(delete_system_login_log)
    delete_system_operation_log = _unwrap(delete_system_operation_log)
    export_system_login_log_list = _unwrap(export_system_login_log_list)
    export_system_operation_log_list = _unwrap(export_system_operation_log_list)
    get_system_login_log_list = _unwrap(get_system_login_log_list)
    get_system_operation_log_list = _unwrap(get_system_operation_log_list)
    unlock_system_user = _unwrap(unlock_system_user)


    req = _request()
    db = _db()
    cu = _admin()
    job = JobModel(jobName='j', jobGroup='DEFAULT', invokeTarget='a.b', cronExpression='* * * * * ?')
    edit = EditJobModel(jobId=1, jobName='j', jobGroup='DEFAULT', invokeTarget='a.b', cronExpression='* * * * * ?')
    with patch.object(JobService, 'get_job_list_services', new=AsyncMock(return_value=_page())):
        assert await get_system_job_list(req, JobPageQueryModel(), db)
    with patch.object(JobService, 'add_job_services', new=AsyncMock(return_value=_crud())):
        assert await add_system_job(req, job, db, cu)
    with patch.object(JobService, 'edit_job_services', new=AsyncMock(return_value=_crud())):
        assert await edit_system_job(req, edit, db, cu)
        assert await change_system_job_status(req, EditJobModel(jobId=1, status='1'), db, cu)
    with patch.object(JobService, 'execute_job_once_services', new=AsyncMock(return_value=_crud())):
        assert await execute_system_job(req, job, db)
    with patch.object(JobService, 'delete_job_services', new=AsyncMock(return_value=_crud())):
        assert await delete_system_job(req, '1', db)
    with patch.object(JobService, 'job_detail_services', new=AsyncMock(return_value=job)):
        assert await query_detail_system_job(req, 1, db)
    with (
        patch.object(JobService, 'get_job_list_services', new=AsyncMock(return_value=[])),
        patch.object(JobService, 'export_job_list_services', new=AsyncMock(return_value=b'x')),
    ):
        assert await export_system_job_list(req, JobPageQueryModel(), db)
    with patch.object(JobLogService, 'get_job_log_list_services', new=AsyncMock(return_value=_page())):
        assert await get_system_job_log_list(req, JobLogPageQueryModel(), db)
    with patch.object(JobLogService, 'clear_job_log_services', new=AsyncMock(return_value=_crud())):
        assert await clear_system_job_log(req, db)
    with patch.object(JobLogService, 'delete_job_log_services', new=AsyncMock(return_value=_crud())):
        assert await delete_system_job_log(req, '1', db)
    with (
        patch.object(JobLogService, 'get_job_log_list_services', new=AsyncMock(return_value=[])),
        patch.object(JobLogService, 'export_job_log_list_services', new=AsyncMock(return_value=b'x')),
    ):
        assert await export_system_job_log_list(req, JobLogPageQueryModel(), db)

    with patch.object(OperationLogService, 'get_operation_log_list_services', new=AsyncMock(return_value=_page())):
        assert await get_system_operation_log_list(req, OperLogPageQueryModel(), db)
    with patch.object(OperationLogService, 'clear_operation_log_services', new=AsyncMock(return_value=_crud())):
        assert await clear_system_operation_log(req, db)
    with patch.object(OperationLogService, 'delete_operation_log_services', new=AsyncMock(return_value=_crud())):
        assert await delete_system_operation_log(req, '1', db)
    with (
        patch.object(OperationLogService, 'get_operation_log_list_services', new=AsyncMock(return_value=[])),
        patch.object(OperationLogService, 'export_operation_log_list_services', new=AsyncMock(return_value=b'x')),
    ):
        assert await export_system_operation_log_list(req, OperLogPageQueryModel(), db)
    with patch.object(LoginLogService, 'get_login_log_list_services', new=AsyncMock(return_value=_page())):
        assert await get_system_login_log_list(req, LoginLogPageQueryModel(), db)
    with patch.object(LoginLogService, 'clear_login_log_services', new=AsyncMock(return_value=_crud())):
        assert await clear_system_login_log(req, db)
    with patch.object(LoginLogService, 'delete_login_log_services', new=AsyncMock(return_value=_crud())):
        assert await delete_system_login_log(req, '1', db)
    with patch.object(LoginLogService, 'unlock_user_services', new=AsyncMock(return_value=_crud())):
        assert await unlock_system_user(req, 'u', db)
    with (
        patch.object(LoginLogService, 'get_login_log_list_services', new=AsyncMock(return_value=[])),
        patch.object(LoginLogService, 'export_login_log_list_services', new=AsyncMock(return_value=b'x')),
    ):
        assert await export_system_login_log_list(req, LoginLogPageQueryModel(), db)


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_controller_all() -> None:
    from module_admin.controller.login_controller import (
        get_login_user_info,
        get_login_user_routers,
        login,
        logout,
        register_user,
    )
    get_login_user_info = _unwrap(get_login_user_info)
    get_login_user_routers = _unwrap(get_login_user_routers)
    login = _unwrap(login)
    logout = _unwrap(logout)
    register_user = _unwrap(register_user)


    db = _db()
    cu = _admin()
    form = SimpleNamespace(username='u', password='p', code='c', uuid='id', login_info={})
    user_row = SimpleNamespace(user_id=2, user_name='u')
    dept_row = SimpleNamespace(dept_name='d')
    redis = AsyncMock()
    redis.get = AsyncMock(return_value='true')
    redis.set = AsyncMock()

    req = _request(redis=redis)
    with (
        patch.object(LoginService, 'authenticate_user', new=AsyncMock(return_value=(user_row, dept_row))),
        patch.object(LoginService, 'create_access_token', new=AsyncMock(return_value='tok')),
        patch.object(UserService, 'edit_user_services', new=AsyncMock(return_value=_crud())),
        patch('module_admin.controller.login_controller.AppConfig.app_same_time_login', True),
    ):
        assert await login(req, form, db)

    redis2 = AsyncMock()
    redis2.get = AsyncMock(return_value='false')
    redis2.set = AsyncMock()
    req2 = _request(redis=redis2, headers=[(b'referer', b'http://x/docs')])
    with (
        patch.object(LoginService, 'authenticate_user', new=AsyncMock(return_value=(user_row, None))),
        patch.object(LoginService, 'create_access_token', new=AsyncMock(return_value='tok')),
        patch.object(UserService, 'edit_user_services', new=AsyncMock(return_value=_crud())),
        patch('module_admin.controller.login_controller.AppConfig.app_same_time_login', False),
    ):
        out = await login(req2, form, db)
        assert out['access_token'] == 'tok'

    req3 = _request(redis=redis2, headers=[(b'referer', b'http://x/redoc')])
    with (
        patch.object(LoginService, 'authenticate_user', new=AsyncMock(return_value=(user_row, dept_row))),
        patch.object(LoginService, 'create_access_token', new=AsyncMock(return_value='tok')),
        patch.object(UserService, 'edit_user_services', new=AsyncMock(return_value=_crud())),
        patch('module_admin.controller.login_controller.AppConfig.app_same_time_login', True),
    ):
        out = await login(req3, form, db)
        assert out['token_type'] == 'Bearer'

    assert await get_login_user_info(req, cu)
    with patch.object(LoginService, 'get_current_user_routers', new=AsyncMock(return_value=[])):
        assert await get_login_user_routers(req, cu, db)
    with patch.object(LoginService, 'register_user_services', new=AsyncMock(return_value=_crud('reg'))):
        assert await register_user(req, UserRegister(username='u', password='okPass', confirmPassword='okPass'), db)

    with (
        patch('module_admin.controller.login_controller.jwt.decode', return_value={'session_id': 's', 'user_id': '2'}),
        patch.object(LoginService, 'logout_services', new=AsyncMock()),
        patch('module_admin.controller.login_controller.AppConfig.app_same_time_login', True),
    ):
        assert await logout(req, 'tok')
    with (
        patch('module_admin.controller.login_controller.jwt.decode', return_value={'session_id': 's', 'user_id': '2'}),
        patch.object(LoginService, 'logout_services', new=AsyncMock()),
        patch('module_admin.controller.login_controller.AppConfig.app_same_time_login', False),
    ):
        assert await logout(req, 'tok')


# ---------------------------------------------------------------------------
# role
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_role_controller_all() -> None:
    from module_admin.controller.role_controller import (
        add_system_role,
        add_system_role_user,
        batch_cancel_system_role_user,
        cancel_system_role_user,
        delete_system_role,
        edit_system_role,
        edit_system_role_datascope,
        export_system_role_list,
        get_system_allocated_user_list,
        get_system_role_dept_tree,
        get_system_role_list,
        get_system_unallocated_user_list,
        query_detail_system_role,
        reset_system_role_status,
    )
    add_system_role = _unwrap(add_system_role)
    add_system_role_user = _unwrap(add_system_role_user)
    batch_cancel_system_role_user = _unwrap(batch_cancel_system_role_user)
    cancel_system_role_user = _unwrap(cancel_system_role_user)
    delete_system_role = _unwrap(delete_system_role)
    edit_system_role = _unwrap(edit_system_role)
    edit_system_role_datascope = _unwrap(edit_system_role_datascope)
    export_system_role_list = _unwrap(export_system_role_list)
    get_system_allocated_user_list = _unwrap(get_system_allocated_user_list)
    get_system_role_dept_tree = _unwrap(get_system_role_dept_tree)
    get_system_role_list = _unwrap(get_system_role_list)
    get_system_unallocated_user_list = _unwrap(get_system_unallocated_user_list)
    query_detail_system_role = _unwrap(query_detail_system_role)
    reset_system_role_status = _unwrap(reset_system_role_status)


    req = _request()
    db = _db()
    scope = MagicMock()
    admin = _admin()
    user = _user()
    role = AddRoleModel(roleId=2, roleName='r', roleKey='k', roleSort=1, menuIds=[1], deptIds=[1], dataScope='2')
    detail = RoleModel(roleId=2, roleName='r', roleKey='k', roleSort=1)

    with (
        patch.object(DeptService, 'get_dept_tree_services', new=AsyncMock(return_value=[])),
        patch.object(
            RoleService, 'get_role_dept_tree_services', new=AsyncMock(return_value=RoleDeptQueryModel())
        ),
    ):
        assert await get_system_role_dept_tree(req, 2, db, scope)
    with patch.object(RoleService, 'get_role_list_services', new=AsyncMock(return_value=_page())):
        assert await get_system_role_list(req, RolePageQueryModel(), db, scope)
    with patch.object(RoleService, 'add_role_services', new=AsyncMock(return_value=_crud())):
        assert await add_system_role(req, role, db, admin)
    with (
        patch.object(RoleService, 'check_role_allowed_services', new=AsyncMock()),
        patch.object(RoleService, 'edit_role_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await edit_system_role(req, role, db, admin, scope)
    with (
        patch.object(RoleService, 'check_role_allowed_services', new=AsyncMock()),
        patch.object(RoleService, 'check_role_data_scope_services', new=AsyncMock()),
        patch.object(RoleService, 'edit_role_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await edit_system_role(req, role, db, user, scope)
    with (
        patch.object(RoleService, 'check_role_allowed_services', new=AsyncMock()),
        patch.object(RoleService, 'role_datascope_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await edit_system_role_datascope(req, role, db, admin, scope)
    with (
        patch.object(RoleService, 'check_role_allowed_services', new=AsyncMock()),
        patch.object(RoleService, 'check_role_data_scope_services', new=AsyncMock()),
        patch.object(RoleService, 'role_datascope_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await edit_system_role_datascope(req, role, db, user, scope)
    with (
        patch.object(RoleService, 'check_role_allowed_services', new=AsyncMock()),
        patch.object(RoleService, 'delete_role_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await delete_system_role(req, '2,3', db, admin, scope)
        assert await delete_system_role(req, '', db, admin, scope)
    with (
        patch.object(RoleService, 'check_role_allowed_services', new=AsyncMock()),
        patch.object(RoleService, 'check_role_data_scope_services', new=AsyncMock()),
        patch.object(RoleService, 'delete_role_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await delete_system_role(req, '2', db, user, scope)
    with patch.object(RoleService, 'role_detail_services', new=AsyncMock(return_value=detail)):
        assert await query_detail_system_role(req, 2, db, admin, scope)
    with (
        patch.object(RoleService, 'check_role_data_scope_services', new=AsyncMock()),
        patch.object(RoleService, 'role_detail_services', new=AsyncMock(return_value=detail)),
    ):
        assert await query_detail_system_role(req, 2, db, user, scope)
    with (
        patch.object(RoleService, 'get_role_list_services', new=AsyncMock(return_value=[])),
        patch.object(RoleService, 'export_role_list_services', new=AsyncMock(return_value=b'x')),
    ):
        assert await export_system_role_list(req, RolePageQueryModel(), db, scope)
    with (
        patch.object(RoleService, 'check_role_allowed_services', new=AsyncMock()),
        patch.object(RoleService, 'edit_role_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await reset_system_role_status(req, AddRoleModel(roleId=2, status='1'), db, admin, scope)
    with (
        patch.object(RoleService, 'check_role_allowed_services', new=AsyncMock()),
        patch.object(RoleService, 'check_role_data_scope_services', new=AsyncMock()),
        patch.object(RoleService, 'edit_role_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await reset_system_role_status(req, AddRoleModel(roleId=2, status='1'), db, user, scope)
    from module_admin.entity.vo.user_vo import UserRolePageQueryModel

    with patch.object(RoleService, 'get_role_user_allocated_list_services', new=AsyncMock(return_value=_page())):
        assert await get_system_allocated_user_list(req, UserRolePageQueryModel(), db, scope)
    with patch.object(RoleService, 'get_role_user_unallocated_list_services', new=AsyncMock(return_value=_page())):
        assert await get_system_unallocated_user_list(req, UserRolePageQueryModel(), db, scope)
    with patch.object(UserService, 'add_user_role_services', new=AsyncMock(return_value=_crud())):
        assert await add_system_role_user(req, CrudUserRoleModel(roleId=2, userIds='3'), db, admin, scope)
    with (
        patch.object(RoleService, 'check_role_data_scope_services', new=AsyncMock()),
        patch.object(UserService, 'add_user_role_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await add_system_role_user(req, CrudUserRoleModel(roleId=2, userIds='3'), db, user, scope)
    with patch.object(UserService, 'delete_user_role_services', new=AsyncMock(return_value=_crud())):
        assert await cancel_system_role_user(req, CrudUserRoleModel(userId=3, roleId=2), db)
        assert await batch_cancel_system_role_user(req, CrudUserRoleModel(roleId=2, userIds='3,4'), db)


# ---------------------------------------------------------------------------
# user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_controller_all(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from module_admin.controller.user_controller import (
        add_system_user,
        batch_import_system_user,
        change_system_user_profile_avatar,
        change_system_user_profile_info,
        change_system_user_status,
        delete_system_user,
        edit_system_user,
        export_system_user_list,
        export_system_user_template,
        get_system_allocated_role_list,
        get_system_dept_tree,
        get_system_user_list,
        query_detail_system_user,
        query_detail_system_user_profile,
        reset_system_user_password,
        reset_system_user_pwd,
        update_system_role_user,
    )
    add_system_user = _unwrap(add_system_user)
    batch_import_system_user = _unwrap(batch_import_system_user)
    change_system_user_profile_avatar = _unwrap(change_system_user_profile_avatar)
    change_system_user_profile_info = _unwrap(change_system_user_profile_info)
    change_system_user_status = _unwrap(change_system_user_status)
    delete_system_user = _unwrap(delete_system_user)
    edit_system_user = _unwrap(edit_system_user)
    export_system_user_list = _unwrap(export_system_user_list)
    export_system_user_template = _unwrap(export_system_user_template)
    get_system_allocated_role_list = _unwrap(get_system_allocated_role_list)
    get_system_dept_tree = _unwrap(get_system_dept_tree)
    get_system_user_list = _unwrap(get_system_user_list)
    query_detail_system_user = _unwrap(query_detail_system_user)
    query_detail_system_user_profile = _unwrap(query_detail_system_user_profile)
    reset_system_user_password = _unwrap(reset_system_user_password)
    reset_system_user_pwd = _unwrap(reset_system_user_pwd)
    update_system_role_user = _unwrap(update_system_role_user)


    monkeypatch.setattr('module_admin.controller.user_controller.UploadConfig.UPLOAD_PATH', str(tmp_path))
    monkeypatch.setattr('module_admin.controller.user_controller.UploadConfig.UPLOAD_PREFIX', '/profile')
    monkeypatch.setattr('module_admin.controller.user_controller.UploadConfig.UPLOAD_MACHINE', 'A')

    req = _request()
    db = _db()
    scope = MagicMock()
    admin = _admin()
    user = _user()
    add = AddUserModel(userName='u', nickName='n', password='pass', deptId=1, roleIds=[1], postIds=[2])
    edit = EditUserModel(userId=2, userName='u', nickName='n', deptId=1, roleIds=[1], postIds=[2])

    with patch.object(DeptService, 'get_dept_tree_services', new=AsyncMock(return_value=[])):
        assert await get_system_dept_tree(req, db, scope)
    with patch.object(UserService, 'get_user_list_services', new=AsyncMock(return_value=_page())):
        assert await get_system_user_list(req, UserPageQueryModel(), db, scope)

    with (
        patch('module_admin.controller.user_controller.PwdUtil.get_password_hash', return_value='h'),
        patch.object(UserService, 'add_user_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await add_system_user(req, add, db, admin, scope, scope)
    with (
        patch.object(DeptService, 'check_dept_data_scope_services', new=AsyncMock()),
        patch.object(RoleService, 'check_role_data_scope_services', new=AsyncMock()),
        patch('module_admin.controller.user_controller.PwdUtil.get_password_hash', return_value='h'),
        patch.object(UserService, 'add_user_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await add_system_user(req, add, db, user, scope, scope)

    with (
        patch.object(UserService, 'check_user_allowed_services', new=AsyncMock()),
        patch.object(UserService, 'edit_user_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await edit_system_user(req, edit, db, admin, scope, scope, scope)
    with (
        patch.object(UserService, 'check_user_allowed_services', new=AsyncMock()),
        patch.object(UserService, 'check_user_data_scope_services', new=AsyncMock()),
        patch.object(DeptService, 'check_dept_data_scope_services', new=AsyncMock()),
        patch.object(RoleService, 'check_role_data_scope_services', new=AsyncMock()),
        patch.object(UserService, 'edit_user_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await edit_system_user(req, edit, db, user, scope, scope, scope)

    with (
        patch.object(UserService, 'check_user_allowed_services', new=AsyncMock()),
        patch.object(UserService, 'delete_user_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await delete_system_user(req, '3,4', db, admin, scope)
        assert await delete_system_user(req, '', db, admin, scope)
    fail = await delete_system_user(req, '2', db, user, scope)
    assert fail.body  # self-delete failure
    with (
        patch.object(UserService, 'check_user_allowed_services', new=AsyncMock()),
        patch.object(UserService, 'check_user_data_scope_services', new=AsyncMock()),
        patch.object(UserService, 'delete_user_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await delete_system_user(req, '3', db, user, scope)

    with (
        patch.object(UserService, 'check_user_allowed_services', new=AsyncMock()),
        patch('module_admin.controller.user_controller.PwdUtil.get_password_hash', return_value='h'),
        patch.object(UserService, 'edit_user_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await reset_system_user_pwd(req, EditUserModel(userId=2, password='np'), db, admin, scope)
    with (
        patch.object(UserService, 'check_user_allowed_services', new=AsyncMock()),
        patch.object(UserService, 'check_user_data_scope_services', new=AsyncMock()),
        patch('module_admin.controller.user_controller.PwdUtil.get_password_hash', return_value='h'),
        patch.object(UserService, 'edit_user_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await reset_system_user_pwd(req, EditUserModel(userId=2, password='np'), db, user, scope)

    with (
        patch.object(UserService, 'check_user_allowed_services', new=AsyncMock()),
        patch.object(UserService, 'edit_user_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await change_system_user_status(req, EditUserModel(userId=2, status='1'), db, admin, scope)
    with (
        patch.object(UserService, 'check_user_allowed_services', new=AsyncMock()),
        patch.object(UserService, 'check_user_data_scope_services', new=AsyncMock()),
        patch.object(UserService, 'edit_user_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await change_system_user_status(req, EditUserModel(userId=2, status='1'), db, user, scope)

    with patch.object(
        UserService,
        'user_profile_services',
        new=AsyncMock(return_value=UserProfileModel(data=UserInfoModel(userId=1, userName='a', nickName='a'), roleGroup='', postGroup='')),
    ):
        assert await query_detail_system_user_profile(req, db, admin)

    detail = UserDetailModel(
        data=UserInfoModel(userId=2, userName='u', nickName='n'), posts=[], roles=[]
    )
    with patch.object(UserService, 'user_detail_services', new=AsyncMock(return_value=detail)):
        assert await query_detail_system_user(req, db, admin, scope, user_id='')
        assert await query_detail_system_user(req, db, admin, scope, user_id=2)
    with (
        patch.object(UserService, 'check_user_data_scope_services', new=AsyncMock()),
        patch.object(UserService, 'user_detail_services', new=AsyncMock(return_value=detail)),
    ):
        assert await query_detail_system_user(req, db, user, scope, user_id=3)

    with patch.object(UserService, 'edit_user_services', new=AsyncMock(return_value=_crud())):
        assert await change_system_user_profile_avatar(req, b'img', db, admin)
    # FileExistsError path
    with (
        patch('module_admin.controller.user_controller.os.makedirs', side_effect=FileExistsError),
        patch('module_admin.controller.user_controller.aiofiles.open') as mock_open,
        patch.object(UserService, 'edit_user_services', new=AsyncMock(return_value=_crud())),
    ):
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=AsyncMock(write=AsyncMock()))
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_open.return_value = mock_cm
        assert await change_system_user_profile_avatar(req, b'img', db, admin)
    assert await change_system_user_profile_avatar(req, b'', db, admin)

    with patch.object(UserService, 'edit_user_services', new=AsyncMock(return_value=_crud())):
        assert await change_system_user_profile_info(req, UserInfoModel(nickName='a'), db, admin)
        assert await change_system_user_profile_info(req, UserInfoModel(nickName='n'), db, user)
    with patch.object(UserService, 'reset_user_services', new=AsyncMock(return_value=_crud())):
        assert await reset_system_user_password(
            req, ResetPasswordModel(oldPassword='o', newPassword='n'), db, admin
        )

    file = UploadFile(filename='u.xlsx', file=BytesIO(b'x'))
    with patch.object(UserService, 'batch_import_user_services', new=AsyncMock(return_value=_crud())):
        assert await batch_import_system_user(req, file, False, db, admin, scope, scope)
    with patch.object(UserService, 'get_user_import_template_services', new=AsyncMock(return_value=b'x')):
        assert await export_system_user_template(req, db)
    with (
        patch.object(UserService, 'get_user_list_services', new=AsyncMock(return_value=[])),
        patch.object(UserService, 'export_user_list_services', new=AsyncMock(return_value=b'x')),
    ):
        assert await export_system_user_list(req, UserPageQueryModel(), db, scope)
    with patch.object(
        UserService,
        'get_user_role_allocated_list_services',
        new=AsyncMock(return_value=UserRoleResponseModel(user=UserInfoModel(userId=2, userName='u', nickName='n'), roles=[])),
    ):
        assert await get_system_allocated_role_list(req, 2, db)
    with patch.object(UserService, 'add_user_role_services', new=AsyncMock(return_value=_crud())):
        assert await update_system_role_user(req, 2, '1,2', db, admin, scope, scope)
    with (
        patch.object(UserService, 'check_user_data_scope_services', new=AsyncMock()),
        patch.object(RoleService, 'check_role_data_scope_services', new=AsyncMock()),
        patch.object(UserService, 'add_user_role_services', new=AsyncMock(return_value=_crud())),
    ):
        assert await update_system_role_user(req, 2, '1', db, user, scope, scope)
