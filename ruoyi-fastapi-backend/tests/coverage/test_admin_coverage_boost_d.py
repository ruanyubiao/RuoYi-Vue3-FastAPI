"""Raise module_admin coverage: notice/post/cache/online/common/server/transport + vos/daos."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks, Request, UploadFile

from exceptions.exception import ModelValidatorException, ServiceException
from module_admin.dao.notice_dao import NoticeDao
from module_admin.dao.post_dao import PostDao
from module_admin.entity.vo.dept_vo import DeptModel
from module_admin.entity.vo.notice_vo import DeleteNoticeModel, NoticeModel, NoticePageQueryModel
from module_admin.entity.vo.post_vo import DeletePostModel, PostModel, PostPageQueryModel
from module_admin.entity.vo.role_vo import RoleModel
from module_admin.entity.vo.user_vo import ResetPasswordModel, UserModel
from module_admin.entity.vo.online_vo import DeleteOnlineModel, OnlineQueryModel
from module_admin.service.cache_service import CacheService
from module_admin.service.common_service import CommonService
from module_admin.service.notice_service import NoticeService
from module_admin.service.online_service import OnlineService
from module_admin.service.post_service import PostService
from module_admin.service.server_service import ServerService
from module_admin.service.transport_crypto_service import TransportCryptoService


@contextmanager
def expect_service_error(substr: str):
    with pytest.raises(ServiceException) as ei:
        yield
    assert substr in (ei.value.message or '')


def _request_with_redis(redis: object | None = None) -> Request:
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
        'headers': [],
        'client': ('127.0.0.1', 1),
        'server': ('test', 80),
        'root_path': '',
        'app': app,
    }
    return Request(scope)


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


def _scalar(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


# ---------------------------------------------------------------------------
# VO validators
# ---------------------------------------------------------------------------


def test_extra_vo_validators() -> None:
    NoticeModel(noticeTitle='t').validate_fields()
    PostModel(postName='n', postCode='c', postSort=1).validate_fields()
    DeptModel(deptName='d', orderNum=1, phone='123', email='a@b.com').validate_fields()
    RoleModel(roleName='r', roleKey='k', roleSort=1, menuCheckStrictly=1, deptCheckStrictly=0).validate_fields()
    assert RoleModel.check_filed_mapping(True) == 1
    assert RoleModel.check_filed_mapping(False) == 0
    RoleModel(roleId=1, roleName='r', roleKey='k', roleSort=1)  # admin True
    UserModel(userName='u', nickName='n', email='a@b.com', phonenumber='123')
    UserModel(userId=1, userName='u', nickName='n')  # admin True
    with pytest.raises(ModelValidatorException):
        UserModel(userName='u', password='bad<pass')
    UserModel(userName='u', nickName='n', email='a@b.com', phonenumber='1').validate_fields()
    ResetPasswordModel(newPassword='ok')
    with pytest.raises(ModelValidatorException):
        ResetPasswordModel(newPassword='bad|pass')


# ---------------------------------------------------------------------------
# notice
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notice_service_and_dao() -> None:
    db = _db()
    with patch.object(NoticeDao, 'get_notice_list', new=AsyncMock(return_value=[])):
        await NoticeService.get_notice_list_services(db, NoticePageQueryModel(), False)

    existing = SimpleNamespace(notice_id=2)
    with patch.object(NoticeDao, 'get_notice_detail_by_info', new=AsyncMock(return_value=existing)):
        assert await NoticeService.check_notice_unique_services(db, NoticeModel(noticeId=1, noticeTitle='t')) is False
        assert await NoticeService.check_notice_unique_services(db, NoticeModel(noticeId=2, noticeTitle='t')) is True
    with patch.object(NoticeDao, 'get_notice_detail_by_info', new=AsyncMock(return_value=None)):
        assert await NoticeService.check_notice_unique_services(db, NoticeModel(noticeTitle='t')) is True

    page = NoticeModel(noticeTitle='t')
    with patch.object(NoticeService, 'check_notice_unique_services', new=AsyncMock(return_value=False)):
        with expect_service_error('已存在'):
            await NoticeService.add_notice_services(db, page)
    with (
        patch.object(NoticeService, 'check_notice_unique_services', new=AsyncMock(return_value=True)),
        patch.object(NoticeDao, 'add_notice_dao', new=AsyncMock()),
    ):
        assert (await NoticeService.add_notice_services(db, page)).is_success
    with (
        patch.object(NoticeService, 'check_notice_unique_services', new=AsyncMock(return_value=True)),
        patch.object(NoticeDao, 'add_notice_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await NoticeService.add_notice_services(db, page)

    edit = NoticeModel(noticeId=1, noticeTitle='t')
    with patch.object(NoticeService, 'notice_detail_services', new=AsyncMock(return_value=NoticeModel())):
        with expect_service_error('不存在'):
            await NoticeService.edit_notice_services(db, edit)
    with (
        patch.object(
            NoticeService, 'notice_detail_services', new=AsyncMock(return_value=NoticeModel(noticeId=1))
        ),
        patch.object(NoticeService, 'check_notice_unique_services', new=AsyncMock(return_value=False)),
    ):
        with expect_service_error('已存在'):
            await NoticeService.edit_notice_services(db, edit)
    with (
        patch.object(
            NoticeService, 'notice_detail_services', new=AsyncMock(return_value=NoticeModel(noticeId=1))
        ),
        patch.object(NoticeService, 'check_notice_unique_services', new=AsyncMock(return_value=True)),
        patch.object(NoticeDao, 'edit_notice_dao', new=AsyncMock()),
    ):
        assert (await NoticeService.edit_notice_services(db, edit)).is_success
    with (
        patch.object(
            NoticeService, 'notice_detail_services', new=AsyncMock(return_value=NoticeModel(noticeId=1))
        ),
        patch.object(NoticeService, 'check_notice_unique_services', new=AsyncMock(return_value=True)),
        patch.object(NoticeDao, 'edit_notice_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await NoticeService.edit_notice_services(db, edit)

    with expect_service_error('为空'):
        await NoticeService.delete_notice_services(db, DeleteNoticeModel(noticeIds=''))
    with patch.object(NoticeDao, 'delete_notice_dao', new=AsyncMock()):
        assert (await NoticeService.delete_notice_services(db, DeleteNoticeModel(noticeIds='1'))).is_success
    with patch.object(NoticeDao, 'delete_notice_dao', new=AsyncMock(side_effect=RuntimeError('e'))):
        with pytest.raises(RuntimeError):
            await NoticeService.delete_notice_services(db, DeleteNoticeModel(noticeIds='1'))

    with (
        patch.object(NoticeDao, 'get_notice_detail_by_id', new=AsyncMock(return_value=object())),
        patch(
            'module_admin.service.notice_service.CamelCaseUtil.transform_result',
            return_value={'noticeId': 1, 'noticeTitle': 't'},
        ),
    ):
        assert (await NoticeService.notice_detail_services(db, 1)).notice_id == 1
    with patch.object(NoticeDao, 'get_notice_detail_by_id', new=AsyncMock(return_value=None)):
        assert (await NoticeService.notice_detail_services(db, 1)).notice_id is None

    db.execute = AsyncMock(return_value=_scalars_first(SimpleNamespace(notice_id=1)))
    await NoticeDao.get_notice_detail_by_id(db, 1)
    await NoticeDao.get_notice_detail_by_info(db, NoticeModel(noticeTitle='t'))
    with patch('module_admin.dao.notice_dao.PageUtil.paginate', new=AsyncMock(return_value=[])):
        await NoticeDao.get_notice_list(
            db,
            NoticePageQueryModel(
                noticeTitle='t', noticeType='1', createBy='a', beginTime='2024-01-01', endTime='2024-01-02'
            ),
            True,
        )
        await NoticeDao.get_notice_list(db, NoticePageQueryModel(), False)
    db.add = MagicMock()
    db.flush = AsyncMock()
    await NoticeDao.add_notice_dao(db, NoticeModel(noticeTitle='t'))
    db.execute = AsyncMock()
    await NoticeDao.edit_notice_dao(db, {'notice_id': 1})
    await NoticeDao.delete_notice_dao(db, NoticeModel(noticeId=1))


# ---------------------------------------------------------------------------
# post
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_service_and_dao() -> None:
    db = _db()
    with patch.object(PostDao, 'get_post_list', new=AsyncMock(return_value=[])):
        await PostService.get_post_list_services(db, PostPageQueryModel(), False)

    existing = SimpleNamespace(post_id=2)
    with patch.object(PostDao, 'get_post_detail_by_info', new=AsyncMock(return_value=existing)):
        assert await PostService.check_post_name_unique_services(db, PostModel(postId=1, postName='n')) is False
        assert await PostService.check_post_code_unique_services(db, PostModel(postId=1, postCode='c')) is False
        assert await PostService.check_post_code_unique_services(db, PostModel(postId=2, postCode='c')) is True
    with patch.object(PostDao, 'get_post_detail_by_info', new=AsyncMock(return_value=None)):
        assert await PostService.check_post_name_unique_services(db, PostModel(postName='n')) is True
        assert await PostService.check_post_code_unique_services(db, PostModel(postCode='c')) is True

    page = PostModel(postName='n', postCode='c')
    with patch.object(PostService, 'check_post_name_unique_services', new=AsyncMock(return_value=False)):
        with expect_service_error('名称'):
            await PostService.add_post_services(db, page)
    with (
        patch.object(PostService, 'check_post_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(PostService, 'check_post_code_unique_services', new=AsyncMock(return_value=False)),
    ):
        with expect_service_error('编码'):
            await PostService.add_post_services(db, page)
    with (
        patch.object(PostService, 'check_post_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(PostService, 'check_post_code_unique_services', new=AsyncMock(return_value=True)),
        patch.object(PostDao, 'add_post_dao', new=AsyncMock()),
    ):
        assert (await PostService.add_post_services(db, page)).is_success
    with (
        patch.object(PostService, 'check_post_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(PostService, 'check_post_code_unique_services', new=AsyncMock(return_value=True)),
        patch.object(PostDao, 'add_post_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await PostService.add_post_services(db, page)

    edit = PostModel(postId=1, postName='n', postCode='c')
    with patch.object(PostService, 'post_detail_services', new=AsyncMock(return_value=PostModel())):
        with expect_service_error('不存在'):
            await PostService.edit_post_services(db, edit)
    with (
        patch.object(PostService, 'post_detail_services', new=AsyncMock(return_value=PostModel(postId=1))),
        patch.object(PostService, 'check_post_name_unique_services', new=AsyncMock(return_value=False)),
    ):
        with expect_service_error('名称'):
            await PostService.edit_post_services(db, edit)
    with (
        patch.object(PostService, 'post_detail_services', new=AsyncMock(return_value=PostModel(postId=1))),
        patch.object(PostService, 'check_post_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(PostService, 'check_post_code_unique_services', new=AsyncMock(return_value=False)),
    ):
        with expect_service_error('编码'):
            await PostService.edit_post_services(db, edit)
    with (
        patch.object(PostService, 'post_detail_services', new=AsyncMock(return_value=PostModel(postId=1))),
        patch.object(PostService, 'check_post_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(PostService, 'check_post_code_unique_services', new=AsyncMock(return_value=True)),
        patch.object(PostDao, 'edit_post_dao', new=AsyncMock()),
    ):
        assert (await PostService.edit_post_services(db, edit)).is_success
    with (
        patch.object(PostService, 'post_detail_services', new=AsyncMock(return_value=PostModel(postId=1))),
        patch.object(PostService, 'check_post_name_unique_services', new=AsyncMock(return_value=True)),
        patch.object(PostService, 'check_post_code_unique_services', new=AsyncMock(return_value=True)),
        patch.object(PostDao, 'edit_post_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await PostService.edit_post_services(db, edit)

    with expect_service_error('为空'):
        await PostService.delete_post_services(db, DeletePostModel(postIds=''))
    with (
        patch.object(
            PostService, 'post_detail_services', new=AsyncMock(return_value=PostModel(postId=1, postName='n'))
        ),
        patch.object(PostDao, 'count_user_post_dao', new=AsyncMock(return_value=1)),
    ):
        with expect_service_error('已分配'):
            await PostService.delete_post_services(db, DeletePostModel(postIds='1'))
    with (
        patch.object(
            PostService, 'post_detail_services', new=AsyncMock(return_value=PostModel(postId=1, postName='n'))
        ),
        patch.object(PostDao, 'count_user_post_dao', new=AsyncMock(return_value=0)),
        patch.object(PostDao, 'delete_post_dao', new=AsyncMock()),
    ):
        assert (await PostService.delete_post_services(db, DeletePostModel(postIds='1'))).is_success
    with (
        patch.object(
            PostService, 'post_detail_services', new=AsyncMock(return_value=PostModel(postId=1, postName='n'))
        ),
        patch.object(PostDao, 'count_user_post_dao', new=AsyncMock(return_value=0)),
        patch.object(PostDao, 'delete_post_dao', new=AsyncMock(side_effect=RuntimeError('e'))),
    ):
        with pytest.raises(RuntimeError):
            await PostService.delete_post_services(db, DeletePostModel(postIds='1'))

    with (
        patch.object(PostDao, 'get_post_detail_by_id', new=AsyncMock(return_value=object())),
        patch(
            'module_admin.service.post_service.CamelCaseUtil.transform_result',
            return_value={'postId': 1, 'postName': 'n', 'postCode': 'c'},
        ),
    ):
        assert (await PostService.post_detail_services(db, 1)).post_id == 1
    with patch.object(PostDao, 'get_post_detail_by_id', new=AsyncMock(return_value=None)):
        assert (await PostService.post_detail_services(db, 1)).post_id is None

    with patch('module_admin.service.post_service.ExcelUtil.export_list2excel', return_value=b'p'):
        assert await PostService.export_post_list_services([{'status': '0'}, {'status': '1'}]) == b'p'

    db.execute = AsyncMock(return_value=_scalars_first(SimpleNamespace(post_id=1)))
    await PostDao.get_post_by_id(db, 1)
    await PostDao.get_post_detail_by_id(db, 1)
    await PostDao.get_post_detail_by_info(db, PostModel(postName='n'))
    await PostDao.get_post_detail_by_info(db, PostModel(postCode='c'))
    with patch('module_admin.dao.post_dao.PageUtil.paginate', new=AsyncMock(return_value=[])):
        await PostDao.get_post_list(db, PostPageQueryModel(postCode='c', postName='n', status='0'), True)
        await PostDao.get_post_list(db, PostPageQueryModel(), False)
    db.add = MagicMock()
    db.flush = AsyncMock()
    await PostDao.add_post_dao(db, PostModel(postName='n', postCode='c'))
    db.execute = AsyncMock()
    await PostDao.edit_post_dao(db, {'post_id': 1})
    await PostDao.delete_post_dao(db, PostModel(postId=1))
    db.execute = AsyncMock(return_value=_scalar(2))
    assert await PostDao.count_user_post_dao(db, 1) == 2


# ---------------------------------------------------------------------------
# cache / online / transport / common / server
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_online_transport_common_server() -> None:
    redis = AsyncMock()
    redis.info = AsyncMock(side_effect=[{'redis_version': '7'}, {'cmdstat_get': {'calls': 1}}])
    redis.dbsize = AsyncMock(return_value=3)
    redis.keys = AsyncMock(return_value=['sys_config:a', 'other:b'])
    redis.get = AsyncMock(return_value='v')
    redis.delete = AsyncMock()
    req = _request_with_redis(redis)

    mon = await CacheService.get_cache_monitor_statistical_info_services(req)
    assert mon.db_size == 3
    names = await CacheService.get_cache_monitor_cache_name_services()
    assert names
    keys = await CacheService.get_cache_monitor_cache_key_services(req, 'sys_config')
    assert 'a' in keys
    val = await CacheService.get_cache_monitor_cache_value_services(req, 'sys_config', 'a')
    assert val.cache_value == 'v'
    assert (await CacheService.clear_cache_monitor_cache_name_services(req, 'sys_config')).is_success
    redis.keys = AsyncMock(return_value=[])
    assert (await CacheService.clear_cache_monitor_cache_name_services(req, 'empty')).is_success
    redis.keys = AsyncMock(return_value=['x:k'])
    assert (await CacheService.clear_cache_monitor_cache_key_services(req, 'k')).is_success
    redis.keys = AsyncMock(return_value=[])
    assert (await CacheService.clear_cache_monitor_cache_key_services(req, 'k')).is_success
    redis.keys = AsyncMock(return_value=['a', 'b'])
    with (
        patch('module_admin.service.cache_service.RedisUtil.init_sys_dict', new=AsyncMock()),
        patch('module_admin.service.cache_service.RedisUtil.init_sys_config', new=AsyncMock()),
    ):
        assert (await CacheService.clear_cache_monitor_all_services(req)).is_success
    redis.keys = AsyncMock(return_value=[])
    with (
        patch('module_admin.service.cache_service.RedisUtil.init_sys_dict', new=AsyncMock()),
        patch('module_admin.service.cache_service.RedisUtil.init_sys_config', new=AsyncMock()),
    ):
        assert (await CacheService.clear_cache_monitor_all_services(req)).is_success

    # online
    token = (
        'eyJhbGciOiJub25lIn0.'
        'eyJ1c2VyX2lkIjoxLCJzZXNzaW9uX2lkIjoiczEiLCJ1c2VyX25hbWUiOiJhZG1pbiIsImRlcHRfbmFtZSI6ImQiLCJsb2dpbl9pbmZvIjp7ImlwYWRkciI6IjEuMS4xLjEiLCJsb2dpbkxvY2F0aW9uIjoieCIsImJyb3dzZXIiOiJiIiwib3MiOiJvcyIsImxvZ2luVGltZSI6InQifX0.'
    )
    # use patched jwt.decode instead of real token
    payload = {
        'user_id': 1,
        'session_id': 's1',
        'user_name': 'admin',
        'dept_name': 'd',
        'login_info': {
            'ipaddr': '1.1.1.1',
            'loginLocation': 'x',
            'browser': 'b',
            'os': 'os',
            'loginTime': 't',
        },
    }
    redis.keys = AsyncMock(return_value=['access_token:s1'])
    redis.get = AsyncMock(return_value='tok')
    with (
        patch('module_admin.service.online_service.jwt.decode', return_value=payload),
        patch('module_admin.service.online_service.AppConfig.app_same_time_login', True),
        patch(
            'module_admin.service.online_service.CamelCaseUtil.transform_result',
            side_effect=lambda x: x,
        ),
    ):
        rows = await OnlineService.get_online_list_services(req, OnlineQueryModel())
        assert rows
        rows = await OnlineService.get_online_list_services(req, OnlineQueryModel(userName='admin'))
        assert rows
        rows = await OnlineService.get_online_list_services(req, OnlineQueryModel(ipaddr='1.1.1.1'))
        assert rows
        rows = await OnlineService.get_online_list_services(
            req, OnlineQueryModel(userName='admin', ipaddr='1.1.1.1')
        )
        assert rows
        assert (
            await OnlineService.get_online_list_services(req, OnlineQueryModel(userName='nope'))
        ) == []

    redis.keys = AsyncMock(return_value=None)
    with patch(
        'module_admin.service.online_service.CamelCaseUtil.transform_result',
        side_effect=lambda x: x,
    ):
        assert await OnlineService.get_online_list_services(req, OnlineQueryModel()) == []

    with patch('module_admin.service.online_service.AppConfig.app_same_time_login', False):
        redis.keys = AsyncMock(return_value=['access_token:1'])
        redis.get = AsyncMock(return_value='tok')
        with (
            patch('module_admin.service.online_service.jwt.decode', return_value=payload),
            patch(
                'module_admin.service.online_service.CamelCaseUtil.transform_result',
                side_effect=lambda x: x,
            ),
        ):
            await OnlineService.get_online_list_services(req, OnlineQueryModel())

    redis.delete = AsyncMock()
    assert (await OnlineService.delete_online_services(req, DeleteOnlineModel(tokenIds='s1,s2'))).is_success
    with expect_service_error('为空'):
        await OnlineService.delete_online_services(req, DeleteOnlineModel(tokenIds=''))

    with (
        patch(
            'module_admin.service.transport_crypto_service.TransportCryptoUtil.build_frontend_config_payload',
            return_value={},
        ),
        patch(
            'module_admin.service.transport_crypto_service.TransportCryptoUtil.build_public_key_payload',
            return_value={},
        ),
        patch(
            'module_admin.service.transport_crypto_service.TransportCryptoMonitorUtil.get_snapshot',
            new=AsyncMock(return_value={}),
        ),
        patch(
            'module_admin.service.transport_crypto_service.TransportCryptoFrontendConfigModel.model_validate',
            return_value=MagicMock(),
        ),
        patch(
            'module_admin.service.transport_crypto_service.TransportCryptoPublicKeyModel.model_validate',
            return_value=MagicMock(),
        ),
        patch(
            'module_admin.service.transport_crypto_service.TransportCryptoMonitorModel.model_validate',
            return_value=MagicMock(),
        ),
    ):
        await TransportCryptoService.get_transport_frontend_config_services()
        await TransportCryptoService.get_transport_public_key_services()
        await TransportCryptoService.get_transport_crypto_monitor_info_services(req)

    # common upload/download
    bad_file = MagicMock(spec=UploadFile)
    with patch('module_admin.service.common_service.UploadUtil.check_file_extension', return_value=False):
        with expect_service_error('不合法'):
            await CommonService.upload_service(req, bad_file)

    good = MagicMock(spec=UploadFile)
    good.filename = 'a.txt'
    good.read = AsyncMock(side_effect=[b'data', b''])
    with (
        patch('module_admin.service.common_service.UploadUtil.check_file_extension', return_value=True),
        patch('module_admin.service.common_service.UploadUtil.generate_random_number', return_value='1234'),
        patch('module_admin.service.common_service.aiofiles.open') as mock_open,
        patch('module_admin.service.common_service.os.makedirs', side_effect=FileExistsError()),
        patch('module_admin.service.common_service.UploadConfig.UPLOAD_PATH', 'up'),
        patch('module_admin.service.common_service.UploadConfig.UPLOAD_PREFIX', '/profile'),
        patch('module_admin.service.common_service.UploadConfig.UPLOAD_MACHINE', 'A'),
    ):
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=AsyncMock(write=AsyncMock()))
        cm.__aexit__ = AsyncMock(return_value=None)
        mock_open.return_value = cm
        result = await CommonService.upload_service(req, good)
        assert result.is_success

    bg = BackgroundTasks()
    with expect_service_error('不合法'):
        await CommonService.download_services(bg, '../x', False)
    with (
        patch('module_admin.service.common_service.UploadUtil.check_file_exists', return_value=False),
        patch('module_admin.service.common_service.UploadConfig.DOWNLOAD_PATH', 'dl'),
    ):
        with expect_service_error('不存在'):
            await CommonService.download_services(bg, 'a.txt', False)
    with (
        patch('module_admin.service.common_service.UploadUtil.check_file_exists', return_value=True),
        patch('module_admin.service.common_service.UploadUtil.generate_file', return_value=b'f'),
        patch('module_admin.service.common_service.UploadConfig.DOWNLOAD_PATH', 'dl'),
    ):
        assert (await CommonService.download_services(bg, 'a.txt', True)).is_success

    with (
        patch('module_admin.service.common_service.UploadUtil.check_file_timestamp', return_value=False),
        patch('module_admin.service.common_service.UploadConfig.UPLOAD_PREFIX', '/profile'),
        patch('module_admin.service.common_service.UploadConfig.UPLOAD_PATH', 'up'),
    ):
        with expect_service_error('不合法'):
            await CommonService.download_resource_services('/profile/a.txt')
    with (
        patch('module_admin.service.common_service.UploadUtil.check_file_timestamp', return_value=True),
        patch('module_admin.service.common_service.UploadUtil.check_file_machine', return_value=True),
        patch('module_admin.service.common_service.UploadUtil.check_file_random_code', return_value=True),
        patch('module_admin.service.common_service.UploadUtil.check_file_exists', return_value=False),
        patch('module_admin.service.common_service.UploadConfig.UPLOAD_PREFIX', '/profile'),
        patch('module_admin.service.common_service.UploadConfig.UPLOAD_PATH', 'up'),
    ):
        with expect_service_error('不存在'):
            await CommonService.download_resource_services('/profile/ok.txt')
    with (
        patch('module_admin.service.common_service.UploadUtil.check_file_timestamp', return_value=True),
        patch('module_admin.service.common_service.UploadUtil.check_file_machine', return_value=True),
        patch('module_admin.service.common_service.UploadUtil.check_file_random_code', return_value=True),
        patch('module_admin.service.common_service.UploadUtil.check_file_exists', return_value=True),
        patch('module_admin.service.common_service.UploadUtil.generate_file', return_value=b'f'),
        patch('module_admin.service.common_service.UploadConfig.UPLOAD_PREFIX', '/profile'),
        patch('module_admin.service.common_service.UploadConfig.UPLOAD_PATH', 'up'),
    ):
        assert (await CommonService.download_resource_services('/profile/ok.txt')).is_success

    # server monitor — mock psutil/platform/socket heavily
    cpu_times = SimpleNamespace(user=1.0, system=2.0, idle=97.0)
    mem = SimpleNamespace(total=1000, used=400, free=600, percent=40.0, available=600)
    proc = MagicMock()
    proc.name.return_value = 'python'
    proc.exe.return_value = '/py'
    proc.create_time.return_value = 1000.0
    proc.memory_info.return_value = SimpleNamespace(rss=100)
    part = SimpleNamespace(device='C:\\', fstype='NTFS', mountpoint='C:\\')
    with (
        patch('module_admin.service.server_service.psutil.cpu_count', return_value=4),
        patch('module_admin.service.server_service.psutil.cpu_times_percent', return_value=cpu_times),
        patch('module_admin.service.server_service.psutil.virtual_memory', return_value=mem),
        patch('module_admin.service.server_service.psutil.Process', return_value=proc),
        patch('module_admin.service.server_service.psutil.disk_partitions', return_value=[part, part]),
        patch(
            'module_admin.service.server_service.psutil.disk_usage',
            side_effect=[
                SimpleNamespace(total=10, used=4, free=6, percent=40.0),
                SimpleNamespace(total=10, used=4, free=6, percent=40.0),
                Exception('skip'),
            ],
        ),
        patch('module_admin.service.server_service.socket.gethostname', return_value='host'),
        patch('module_admin.service.server_service.socket.gethostbyname', return_value='127.0.0.1'),
        patch('module_admin.service.server_service.platform.platform', return_value='win'),
        patch('module_admin.service.server_service.platform.node', return_value='node'),
        patch('module_admin.service.server_service.platform.machine', return_value='x64'),
        patch('module_admin.service.server_service.platform.python_version', return_value='3.13'),
        patch('module_admin.service.server_service.time.time', return_value=2000.0),
        patch('module_admin.service.server_service.anyio.Path.cwd', new=AsyncMock(return_value='/cwd')),
    ):
        info = await ServerService.get_server_monitor_info()
        assert info.cpu.cpu_num == 4
