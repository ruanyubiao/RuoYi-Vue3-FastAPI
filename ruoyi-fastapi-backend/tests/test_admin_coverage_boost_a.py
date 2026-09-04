"""Raise module_admin coverage: config/captcha/health + related dao/vo."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from exceptions.exception import ModelValidatorException, ServiceException
from module_admin.dao.config_dao import ConfigDao
from module_admin.entity.vo.config_vo import ConfigModel, ConfigPageQueryModel, DeleteConfigModel
from module_admin.entity.vo.login_vo import UserRegister
from module_admin.entity.vo.menu_vo import MenuModel
from module_admin.service.captcha_service import CaptchaService, _captcha_font_path
from module_admin.service.config_service import ConfigService
from module_admin.service.health_service import HealthService


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


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


def _scalars_all(values):
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


# ---------------------------------------------------------------------------
# config VO
# ---------------------------------------------------------------------------


def test_config_vo_validate_fields_ok() -> None:
    model = ConfigModel(configKey='sys.key', configName='name', configValue='val')
    model.validate_fields()


def test_config_vo_validate_fields_blank_key() -> None:
    with pytest.raises(Exception):
        ConfigModel(configKey='', configName='n', configValue='v').validate_fields()


# ---------------------------------------------------------------------------
# login / menu VO validators
# ---------------------------------------------------------------------------


def test_user_register_rejects_illegal_password() -> None:
    with pytest.raises(ModelValidatorException):
        UserRegister(username='u', password='bad<pass', confirmPassword='bad<pass')


def test_user_register_accepts_ok_password() -> None:
    UserRegister(username='u', password='okPass', confirmPassword='okPass')


def test_menu_vo_validate_fields() -> None:
    MenuModel(menuName='菜单', orderNum=1, menuType='C', path='/a', component='x', perms='p:a').validate_fields()


# ---------------------------------------------------------------------------
# config service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_list_and_cache_query() -> None:
    db = _db()
    with patch.object(ConfigDao, 'get_config_list', new=AsyncMock(return_value=[{'configKey': 'a'}])):
        assert await ConfigService.get_config_list_services(db, ConfigPageQueryModel(), False) == [{'configKey': 'a'}]

    redis = AsyncMock()
    redis.get = AsyncMock(return_value='v')
    assert await ConfigService.query_config_list_from_cache_services(redis, 'k') == 'v'


@pytest.mark.asyncio
async def test_init_cache_sys_config_deletes_keys() -> None:
    db = _db()
    redis = AsyncMock()
    redis.keys = AsyncMock(return_value=['sys_config:a', 'sys_config:b'])
    redis.delete = AsyncMock()
    redis.set = AsyncMock()
    with patch.object(
        ConfigDao,
        'get_config_list',
        new=AsyncMock(return_value=[{'configKey': 'a', 'configValue': '1'}]),
    ):
        await ConfigService.init_cache_sys_config_services(db, redis)
    redis.delete.assert_awaited()
    redis.set.assert_awaited()


@pytest.mark.asyncio
async def test_init_cache_sys_config_no_keys() -> None:
    db = _db()
    redis = AsyncMock()
    redis.keys = AsyncMock(return_value=[])
    redis.set = AsyncMock()
    with patch.object(ConfigDao, 'get_config_list', new=AsyncMock(return_value=[])):
        await ConfigService.init_cache_sys_config_services(db, redis)
    redis.delete.assert_not_called()


@pytest.mark.asyncio
async def test_check_config_key_unique_branches() -> None:
    db = _db()
    existing = SimpleNamespace(config_id=2)
    with patch.object(ConfigDao, 'get_config_detail_by_info', new=AsyncMock(return_value=existing)):
        assert await ConfigService.check_config_key_unique_services(db, ConfigModel(configId=1, configKey='k')) is False
        assert await ConfigService.check_config_key_unique_services(db, ConfigModel(configId=2, configKey='k')) is True
    with patch.object(ConfigDao, 'get_config_detail_by_info', new=AsyncMock(return_value=None)):
        assert await ConfigService.check_config_key_unique_services(db, ConfigModel(configKey='k')) is True


@pytest.mark.asyncio
async def test_add_config_success_and_duplicate() -> None:
    db = _db()
    req = _request_with_redis()
    page = ConfigModel(configName='n', configKey='k', configValue='v')
    with patch.object(ConfigService, 'check_config_key_unique_services', new=AsyncMock(return_value=False)):
        with pytest.raises(ServiceException):
            await ConfigService.add_config_services(req, db, page)

    with (
        patch.object(ConfigService, 'check_config_key_unique_services', new=AsyncMock(return_value=True)),
        patch.object(ConfigDao, 'add_config_dao', new=AsyncMock()),
    ):
        result = await ConfigService.add_config_services(req, db, page)
        assert result.is_success is True

    with (
        patch.object(ConfigService, 'check_config_key_unique_services', new=AsyncMock(return_value=True)),
        patch.object(ConfigDao, 'add_config_dao', new=AsyncMock(side_effect=RuntimeError('db'))),
    ):
        with pytest.raises(RuntimeError):
            await ConfigService.add_config_services(req, db, page)
        db.rollback.assert_awaited()


@pytest.mark.asyncio
async def test_edit_config_branches() -> None:
    db = _db()
    redis = AsyncMock()
    req = _request_with_redis(redis)
    page = ConfigModel(configId=1, configName='n', configKey='new', configValue='v')

    with patch.object(ConfigService, 'config_detail_services', new=AsyncMock(return_value=ConfigModel())):
        with expect_service_error('不存在'):
            await ConfigService.edit_config_services(req, db, page)

    old = ConfigModel(configId=1, configKey='old', configName='n', configValue='v')
    with (
        patch.object(ConfigService, 'config_detail_services', new=AsyncMock(return_value=old)),
        patch.object(ConfigService, 'check_config_key_unique_services', new=AsyncMock(return_value=False)),
    ):
        with expect_service_error('已存在'):
            await ConfigService.edit_config_services(req, db, page)

    with (
        patch.object(ConfigService, 'config_detail_services', new=AsyncMock(return_value=old)),
        patch.object(ConfigService, 'check_config_key_unique_services', new=AsyncMock(return_value=True)),
        patch.object(ConfigDao, 'edit_config_dao', new=AsyncMock()),
    ):
        result = await ConfigService.edit_config_services(req, db, page)
        assert result.is_success is True
        redis.delete.assert_awaited()

    same_key = ConfigModel(configId=1, configKey='old', configName='n', configValue='v2')
    with (
        patch.object(ConfigService, 'config_detail_services', new=AsyncMock(return_value=old)),
        patch.object(ConfigService, 'check_config_key_unique_services', new=AsyncMock(return_value=True)),
        patch.object(ConfigDao, 'edit_config_dao', new=AsyncMock(side_effect=RuntimeError('x'))),
    ):
        with pytest.raises(RuntimeError):
            await ConfigService.edit_config_services(req, db, same_key)


@pytest.mark.asyncio
async def test_delete_config_branches() -> None:
    db = _db()
    redis = AsyncMock()
    req = _request_with_redis(redis)

    with expect_service_error('为空'):
        await ConfigService.delete_config_services(req, db, DeleteConfigModel(configIds=''))

    builtin = ConfigModel(configId=1, configKey='k', configType='Y')
    with patch.object(ConfigService, 'config_detail_services', new=AsyncMock(return_value=builtin)):
        with expect_service_error('内置'):
            await ConfigService.delete_config_services(req, db, DeleteConfigModel(configIds='1'))

    normal = ConfigModel(configId=2, configKey='k2', configType='N')
    with (
        patch.object(ConfigService, 'config_detail_services', new=AsyncMock(return_value=normal)),
        patch.object(ConfigDao, 'delete_config_dao', new=AsyncMock()),
    ):
        result = await ConfigService.delete_config_services(req, db, DeleteConfigModel(configIds='2'))
        assert result.is_success is True

    with (
        patch.object(ConfigService, 'config_detail_services', new=AsyncMock(return_value=normal)),
        patch.object(ConfigDao, 'delete_config_dao', new=AsyncMock(side_effect=RuntimeError('x'))),
    ):
        with pytest.raises(RuntimeError):
            await ConfigService.delete_config_services(req, db, DeleteConfigModel(configIds='2'))


@pytest.mark.asyncio
async def test_config_detail_and_export_and_refresh() -> None:
    db = _db()
    with (
        patch.object(ConfigDao, 'get_config_detail_by_id', new=AsyncMock(return_value=object())),
        patch(
            'module_admin.service.config_service.CamelCaseUtil.transform_result',
            return_value={'configId': 1, 'configName': 'n', 'configKey': 'k', 'configValue': 'v'},
        ),
    ):
        detail = await ConfigService.config_detail_services(db, 1)
        assert detail.config_id == 1
    with patch.object(ConfigDao, 'get_config_detail_by_id', new=AsyncMock(return_value=None)):
        empty = await ConfigService.config_detail_services(db, 9)
        assert empty.config_id is None

    with patch('module_admin.service.config_service.ExcelUtil.export_list2excel', return_value=b'xls') as export:
        data = await ConfigService.export_config_list_services(
            [{'configType': 'Y'}, {'configType': 'N'}]
        )
        assert data == b'xls'
        export.assert_called_once()

    req = _request_with_redis()
    with patch.object(ConfigService, 'init_cache_sys_config_services', new=AsyncMock()) as init:
        result = await ConfigService.refresh_sys_config_services(req, db)
        assert result.is_success is True
        init.assert_awaited()


# ---------------------------------------------------------------------------
# config dao
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_dao_crud_and_list() -> None:
    db = _db()
    db.execute = AsyncMock(return_value=_scalars_first(SimpleNamespace(config_id=1)))
    assert (await ConfigDao.get_config_detail_by_id(db, 1)).config_id == 1

    db.execute = AsyncMock(return_value=_scalars_first(SimpleNamespace(config_id=2)))
    assert (await ConfigDao.get_config_detail_by_info(db, ConfigModel(configKey='k', configValue='v'))).config_id == 2
    await ConfigDao.get_config_detail_by_info(db, ConfigModel())

    with patch('module_admin.dao.config_dao.PageUtil.paginate', new=AsyncMock(return_value=[])) as paginate:
        q = ConfigPageQueryModel(
            configName='n', configKey='k', configType='Y', beginTime='2024-01-01', endTime='2024-01-02'
        )
        await ConfigDao.get_config_list(db, q, True)
        await ConfigDao.get_config_list(db, ConfigPageQueryModel(), False)
        assert paginate.await_count == 2

    db.flush = AsyncMock()
    db.add = MagicMock()
    await ConfigDao.add_config_dao(db, ConfigModel(configKey='k', configName='n', configValue='v'))
    db.add.assert_called_once()

    db.execute = AsyncMock()
    await ConfigDao.edit_config_dao(db, {'config_id': 1, 'config_value': 'x'})
    await ConfigDao.delete_config_dao(db, ConfigModel(configId=1))
    assert db.execute.await_count == 2


# ---------------------------------------------------------------------------
# captcha leftovers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_captcha_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=lambda key: 'true')
    redis.set = AsyncMock()
    monkeypatch.setattr(
        CaptchaService,
        'create_captcha_image_service',
        AsyncMock(return_value=['imgdata', 7]),
    )
    result = await CaptchaService.build_captcha_code(redis)
    assert result.captcha_enabled is True
    assert result.img == 'imgdata'
    assert result.uuid
    redis.set.assert_awaited()


@pytest.mark.asyncio
async def test_create_captcha_image_all_ops(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('module_admin.service.captcha_service._captcha_font_path', lambda: None)
    monkeypatch.setattr('module_admin.service.captcha_service.random.randint', lambda a, b: 3)
    for op in ('+', '-', '*'):
        monkeypatch.setattr('module_admin.service.captcha_service.random.choice', lambda _lst, o=op: o)
        img, result = await CaptchaService.create_captcha_image_service()
        assert isinstance(img, str) and img
        assert isinstance(result, int)

    # subtraction with negative swap
    seq = iter([1, 5])  # num1 < num2 so result negative then swap
    monkeypatch.setattr('module_admin.service.captcha_service.random.randint', lambda a, b: next(seq))
    monkeypatch.setattr('module_admin.service.captcha_service.random.choice', lambda _lst: '-')
    _img, result = await CaptchaService.create_captcha_image_service()
    assert result >= 0


def test_captcha_font_windows_candidates(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('module_admin.service.captcha_service.get_package_root', lambda: tmp_path)
    monkeypatch.setattr('module_admin.service.captcha_service.os.name', 'nt', raising=False)
    windir = tmp_path / 'Windows'
    fonts = windir / 'Fonts'
    fonts.mkdir(parents=True)
    arial = fonts / 'arial.ttf'
    arial.write_bytes(b'x')
    monkeypatch.setenv('WINDIR', str(windir))
    assert _captcha_font_path() == arial


@pytest.mark.asyncio
async def test_create_captcha_font_oserror(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    bad = tmp_path / 'bad.ttf'
    bad.write_bytes(b'not-a-font')
    monkeypatch.setattr('module_admin.service.captcha_service._captcha_font_path', lambda: bad)

    def boom(*_a, **_k):
        raise OSError('bad font')

    monkeypatch.setattr('module_admin.service.captcha_service.ImageFont.truetype', boom)
    # Avoid real default font / draw measuring; only need OSError fallback branch.
    fake_font = object()
    monkeypatch.setattr(
        'module_admin.service.captcha_service.ImageFont.load_default',
        lambda: fake_font,
    )
    monkeypatch.setattr(
        'module_admin.service.captcha_service.ImageDraw.Draw',
        lambda *_a, **_k: MagicMock(),
    )
    img, _ = await CaptchaService.create_captcha_image_service()
    assert img


# ---------------------------------------------------------------------------
# health leftovers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_app_version_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'version' or name.startswith('version.'):
            raise ImportError('no version')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    assert HealthService._app_version()


@pytest.mark.asyncio
async def test_health_check_database_ok_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(HealthService, '_ping_database', staticmethod(AsyncMock()))
    ok = await HealthService._check_database()
    assert ok['status'] == 'ok'
    assert 'latencyMs' in ok

    async def boom():
        raise TimeoutError('slow')

    monkeypatch.setattr(HealthService, '_ping_database', staticmethod(boom))
    bad = await HealthService._check_database()
    assert bad['status'] == 'error'
    assert 'TimeoutError' in bad['error']


@pytest.mark.asyncio
async def test_health_ping_database(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = AsyncMock()
    conn.execute = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    engine = MagicMock()
    engine.connect.return_value = cm
    monkeypatch.setattr('module_admin.service.health_service.async_engine', engine)
    await HealthService._ping_database()
    conn.execute.assert_awaited()


def test_health_safe_error_truncates() -> None:
    long = RuntimeError('x' * 500)
    assert len(HealthService._safe_error(long)) == 240
