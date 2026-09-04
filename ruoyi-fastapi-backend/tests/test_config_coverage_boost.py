"""Raise coverage of config/, exceptions/, sub_applications/, module_task/."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from redis.exceptions import AuthenticationError, RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError
from starlette.requests import ClientDisconnect

from config import database as dbmod
from config import env as envmod
from config import get_db as get_db_mod
from config import get_redis as get_redis_mod
from config import paths as cfg_paths
from exceptions.exception import (
    AuthException,
    LoginException,
    ModelValidatorException,
    PermissionException,
    ServiceException,
    ServiceWarning,
)
from exceptions.handle import handle_exception
from module_task import payload_tm_partition_job, scheduler_test
from sub_applications.handle import handle_sub_applications
from sub_applications.staticfiles import mount_staticfiles


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------


def test_dotenv_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg_paths, 'get_package_root', lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cfg_paths.dotenv_filename(None) == '.env.dev'
    assert cfg_paths.dotenv_filename('  ') == '.env.dev'
    assert cfg_paths.dotenv_filename('prod') == '.env.prod'
    (tmp_path / '.env.prod').write_text('X=1', encoding='utf-8')
    assert cfg_paths.resolve_dotenv_path('prod') == (tmp_path / '.env.prod').resolve()
    assert cfg_paths.resolve_dotenv_path('missing').name == '.env.missing'
    dirs = cfg_paths.dotenv_search_dirs()
    assert dirs[0] == tmp_path.resolve()


def test_windows_system_profile_and_local_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert cfg_paths._is_windows_system_profile(Path(r'C:\Windows\System32\config\systemprofile\AppData\Local'))
    assert cfg_paths._is_windows_system_profile(Path(r'C:\Windows\System32\config\foo'))
    assert cfg_paths._is_windows_system_profile(Path(r'C:\Windows\ServiceProfiles\LocalService'))
    assert not cfg_paths._is_windows_system_profile(Path(r'C:\Users\ryb\AppData\Local'))

    monkeypatch.setenv('SystemDrive', str(tmp_path).rstrip('\\/'))
    users = tmp_path / 'Users'
    (users / 'Public').mkdir(parents=True)
    good = users / 'alice' / 'AppData' / 'Local'
    (good / 'pgt').mkdir(parents=True)
    bad = users / 'Default' / 'AppData' / 'Local'
    (bad / 'pgt').mkdir(parents=True)
    found = cfg_paths._windows_existing_pgt_local_bases()
    assert good in found
    assert bad not in found

    monkeypatch.delenv('LOCALAPPDATA', raising=False)
    monkeypatch.setattr(cfg_paths, '_windows_console_user_local_appdata', lambda: None)
    monkeypatch.setattr(cfg_paths, '_windows_existing_pgt_local_bases', lambda: [good])
    assert cfg_paths._windows_local_appdata_base().resolve() == good.resolve()

    monkeypatch.setattr(cfg_paths, '_windows_existing_pgt_local_bases', lambda: [])
    monkeypatch.setenv('USERPROFILE', str(users / 'bob'))
    bob_local = users / 'bob' / 'AppData' / 'Local'
    bob_local.mkdir(parents=True)
    assert cfg_paths._windows_local_appdata_base().resolve() == bob_local.resolve()

    monkeypatch.delenv('USERPROFILE', raising=False)
    monkeypatch.setenv('PROGRAMDATA', str(tmp_path / 'ProgramData'))
    assert cfg_paths._windows_local_appdata_base() == Path(str(tmp_path / 'ProgramData'))


def _install_fake_win_modules(fake_ctypes, fake_winreg):
    return patch.dict(
        'sys.modules',
        {
            'ctypes': fake_ctypes,
            'ctypes.wintypes': getattr(fake_ctypes, 'wintypes', MagicMock()),
            'winreg': fake_winreg,
        },
    )


def test_windows_console_user_local_appdata_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # ImportError when ctypes unavailable
    import builtins

    real_import = builtins.__import__

    def boom_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'ctypes' or (name == 'ctypes.wintypes'):
            raise ImportError('no ctypes')
        return real_import(name, globals, locals, fromlist, level)

    # Remove cached modules so local import re-runs
    saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k == 'ctypes' or k.startswith('ctypes.')}
    try:
        with patch('builtins.__import__', side_effect=boom_import):
            assert cfg_paths._windows_console_user_local_appdata() is None
    finally:
        sys.modules.update(saved)

    class Buf:
        value = 'alice'

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class FakeWindll:
        class kernel32:
            @staticmethod
            def WTSGetActiveConsoleSessionId():
                return 7

        class wtsapi32:
            @staticmethod
            def WTSQuerySessionInformationW(server, sid, info, buf, nbytes):
                buf.value = 'alice'
                return 1

            @staticmethod
            def WTSFreeMemory(*a):
                return None

    class FakeCtypes:
        windll = FakeWindll()
        c_wchar_p = Buf
        byref = staticmethod(lambda x: x)

        class wintypes:
            DWORD = object

    def fake_enum_key(root, index):
        mapping = {0: 'S-1-5-18', 1: 'S-1-5-21-alice'}
        if index in mapping:
            return mapping[index]
        raise OSError('done')

    def fake_query(sid_key, name):
        return (str(tmp_path / 'Users' / 'alice'), 1)

    class FakeWinreg:
        HKEY_LOCAL_MACHINE = 1
        OpenKey = staticmethod(lambda *a, **k: FakeKey())
        EnumKey = staticmethod(fake_enum_key)
        QueryValueEx = staticmethod(fake_query)
        CloseKey = staticmethod(lambda *a: None)

    (tmp_path / 'Users' / 'alice' / 'AppData' / 'Local').mkdir(parents=True)
    monkeypatch.setenv('SystemDrive', str(tmp_path).rstrip('\\/'))
    saved2 = {k: sys.modules.pop(k) for k in list(sys.modules) if k in {'ctypes', 'winreg'} or k.startswith('ctypes.')}
    try:
        with _install_fake_win_modules(FakeCtypes, FakeWinreg):
            result = cfg_paths._windows_console_user_local_appdata()
            assert result is not None
            assert result.name == 'Local'
    finally:
        sys.modules.update(saved2)

    # generic Exception path
    bad = MagicMock()
    bad.windll.kernel32.WTSGetActiveConsoleSessionId.side_effect = Exception('fail')
    saved3 = {k: sys.modules.pop(k) for k in list(sys.modules) if k in {'ctypes', 'winreg'} or k.startswith('ctypes.')}
    try:
        with _install_fake_win_modules(bad, MagicMock()):
            assert cfg_paths._windows_console_user_local_appdata() is None
    finally:
        sys.modules.update(saved3)


def test_windows_console_user_session_edge_cases(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class Buf:
        value = ''

    class FakeWindll:
        class kernel32:
            session = 0xFFFFFFFF

            @classmethod
            def WTSGetActiveConsoleSessionId(cls):
                return cls.session

        class wtsapi32:
            qsi = staticmethod(lambda *a: 0)
            WTSFreeMemory = staticmethod(lambda *a: None)

            @classmethod
            def WTSQuerySessionInformationW(cls, *a):
                return cls.qsi(*a)

    class FakeCtypes:
        windll = FakeWindll()
        c_wchar_p = Buf
        byref = staticmethod(lambda x: x)

        class wintypes:
            DWORD = object

    def run_with(fake_winreg=None):
        saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k in {'ctypes', 'winreg'} or k.startswith('ctypes.')}
        try:
            with _install_fake_win_modules(FakeCtypes, fake_winreg or MagicMock()):
                return cfg_paths._windows_console_user_local_appdata()
        finally:
            sys.modules.update(saved)

    assert run_with() is None  # session invalid

    FakeWindll.kernel32.session = 3
    assert run_with() is None  # WTSQuery fails

    def qsi_system(server, sid, info, buf, nbytes):
        buf.value = 'network service'
        return 1

    FakeWindll.wtsapi32.qsi = staticmethod(qsi_system)
    assert run_with() is None

    def qsi_ok(server, sid, info, buf, nbytes):
        buf.value = 'carol'
        return 1

    FakeWindll.wtsapi32.qsi = staticmethod(qsi_ok)

    class WR:
        HKEY_LOCAL_MACHINE = 1
        OpenKey = staticmethod(lambda *a, **k: object())
        EnumKey = staticmethod(lambda *a, **k: (_ for _ in ()).throw(OSError('empty')))
        CloseKey = staticmethod(lambda *a: None)

    carol = tmp_path / 'Users' / 'carol' / 'AppData' / 'Local'
    carol.mkdir(parents=True)
    monkeypatch.setenv('SystemDrive', str(tmp_path).rstrip('\\/'))
    assert run_with(WR) == carol


def test_runtime_data_dir_override_and_posix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / 'data'
    monkeypatch.setenv('PGT_DATA_DIR', str(data))
    assert cfg_paths.get_runtime_data_dir() == data.resolve()

    monkeypatch.delenv('PGT_DATA_DIR', raising=False)
    pkg = tmp_path / 'site-packages' / 'pgt'
    pkg.mkdir(parents=True)
    monkeypatch.setattr(cfg_paths, 'get_package_root', lambda: pkg)
    xdg = tmp_path / 'xdg'
    monkeypatch.setenv('XDG_DATA_HOME', str(xdg))
    # Changing os.name to posix makes pathlib try PosixPath on Windows; keep Path as WindowsPath.
    from pathlib import WindowsPath

    with patch.object(cfg_paths.os, 'name', 'posix'), patch('config.paths.Path', WindowsPath):
        got = cfg_paths.get_runtime_data_dir()
    assert got == (xdg / 'pgt').resolve()


def test_path_subdir_and_sqlite_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('PGT_DATA_DIR', str(tmp_path))
    assert cfg_paths.get_vf_admin_dir().is_dir()
    assert cfg_paths.get_upload_log_data_dir().name == 'log_data'
    assert cfg_paths.resolve_data_subdir('', default='caches').name == 'caches'
    abs_dir = tmp_path / 'abs'
    assert cfg_paths.resolve_data_subdir(str(abs_dir), default='x') == abs_dir.resolve()

    rel = cfg_paths.get_sqlite_path('mydb')
    assert rel.name == 'mydb.db'
    assert cfg_paths.get_sqlite_path('').name.endswith('.db')
    assert cfg_paths.get_sqlite_path('   ').name.endswith('.db')
    abs_db = tmp_path / 'nested' / 'x.db'
    got = cfg_paths.get_sqlite_path(str(abs_db))
    assert got == abs_db
    assert abs_db.parent.is_dir()


def test_config_dir_payload_override_and_layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ext = tmp_path / 'ext_cfg'
    monkeypatch.setenv('PAYLOAD_CONFIG_DIR', str(ext))
    assert cfg_paths.get_external_config_dir() == ext.resolve()
    assert cfg_paths.get_config_dir() == ext.resolve()

    packaged = tmp_path / 'pkg'
    external = tmp_path / 'ext'
    packaged.mkdir()
    external.mkdir()
    monkeypatch.setattr(cfg_paths, 'get_packaged_config_dir', lambda: packaged)
    monkeypatch.setattr(cfg_paths, 'get_external_config_dir', lambda: external)
    assert cfg_paths._config_dirs_are_same() is False
    monkeypatch.setattr(cfg_paths, 'get_external_config_dir', lambda: packaged)
    assert cfg_paths._config_dirs_are_same() is True

    def boom_resolve():
        raise OSError('x')

    monkeypatch.setattr(cfg_paths, 'get_external_config_dir', lambda: SimpleNamespace(resolve=boom_resolve))
    monkeypatch.setattr(cfg_paths, 'get_packaged_config_dir', lambda: packaged)
    assert cfg_paths._config_dirs_are_same() is False

    with pytest.raises(ValueError):
        cfg_paths.require_config_name('bad name.json')
    assert cfg_paths._glob_cfg_names(tmp_path / 'missing', '*.json') == []

    (packaged / 'a.json').write_text('{"datetime":"2026-01-01"}', encoding='utf-8')
    monkeypatch.setattr(cfg_paths, 'get_external_config_dir', lambda: external)
    monkeypatch.setattr(cfg_paths, 'get_packaged_config_dir', lambda: packaged)
    files = cfg_paths.iter_resolved_config_files()
    assert files and files[0].name == 'a.json'
    assert cfg_paths.config_file_layer(packaged / 'a.json') == 'packaged'

    monkeypatch.setattr(cfg_paths, '_config_dirs_are_same', lambda: True)
    assert cfg_paths.config_file_layer(packaged / 'a.json') == 'source'


def test_display_path_and_peek_and_stat_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / 'f.json'
    p.write_text('not-json', encoding='utf-8')
    assert cfg_paths._peek_cfg_datetime(p) == ''
    p.write_text('[]', encoding='utf-8')
    assert cfg_paths._peek_cfg_datetime(p) == ''

    bad = MagicMock()
    bad.resolve.side_effect = OSError('x')
    bad.__str__ = lambda self: 'bad'
    assert cfg_paths.display_config_path(bad) == 'bad'

    monkeypatch.setattr(cfg_paths, '_config_dirs_are_same', lambda: False)
    path = MagicMock()
    path.resolve.side_effect = OSError('x')
    assert cfg_paths.config_file_layer(path) == 'packaged'

    with pytest.raises(FileNotFoundError):
        cfg_paths.stat_config_file('nope.json')
    with pytest.raises(FileNotFoundError):
        cfg_paths.read_config_text('nope.json')


def test_datetime_stamp_files_identical_reconcile_edges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    packaged = tmp_path / 'pkg'
    external = tmp_path / 'ext'
    packaged.mkdir()
    external.mkdir()
    monkeypatch.setattr(cfg_paths, 'get_packaged_config_dir', lambda: packaged)
    monkeypatch.setattr(cfg_paths, 'get_external_config_dir', lambda: external)
    monkeypatch.setattr(cfg_paths, '_config_dirs_are_same', lambda: False)

    p = external / 'a.json'
    p.write_text('{"datetime":"short"}', encoding='utf-8')
    stamp = cfg_paths._datetime_stamp(p)
    assert len(stamp) == 14

    missing = tmp_path / 'gone.json'
    with patch.object(Path, 'stat', side_effect=OSError('x')):
        assert cfg_paths._datetime_stamp(missing) == '00000000000000'

    assert cfg_paths._packaged_cfg_newer(packaged / 'x.json', external / 'x.json') is False
    (packaged / 'b.json').write_text('{"datetime":"2026-02-01"}', encoding='utf-8')
    (external / 'b.json').write_text('{}', encoding='utf-8')
    assert cfg_paths._packaged_cfg_newer(packaged / 'b.json', external / 'b.json') is True
    (external / 'b.json').write_text('{"datetime":"2026-03-01"}', encoding='utf-8')
    assert cfg_paths._packaged_cfg_newer(packaged / 'b.json', external / 'b.json') is False

    with patch('config.paths.filecmp.cmp', side_effect=OSError('x')):
        assert cfg_paths._files_identical(p, p) is False

    assert cfg_paths.drop_redundant_overlay('missing.json') is False
    (packaged / 'c.json').write_text('same', encoding='utf-8')
    (external / 'c.json').write_text('diff', encoding='utf-8')
    assert cfg_paths.drop_redundant_overlay('c.json') is False

    (external / 'c.json').write_text('same', encoding='utf-8')
    # 钉在具体 Path 子类上（Windows 为 WindowsPath），避免只 patch Path 未命中
    ext_c = external / 'c.json'
    with patch.object(type(ext_c), 'unlink', side_effect=OSError('x')):
        assert cfg_paths.drop_redundant_overlay('c.json') is False

    (external / 'c.json').write_text('same', encoding='utf-8')
    assert cfg_paths.drop_redundant_overlay('c.json') is True
    assert not (external / 'c.json').exists()

    monkeypatch.setattr(cfg_paths, '_config_dirs_are_same', lambda: True)
    assert cfg_paths.drop_redundant_overlay('c.json') is False
    cfg_paths.reconcile_external_configs()

    monkeypatch.setattr(cfg_paths, '_config_dirs_are_same', lambda: False)
    monkeypatch.setattr(cfg_paths, 'get_packaged_config_dir', lambda: tmp_path / 'nope')
    cfg_paths.reconcile_external_configs()

    monkeypatch.setattr(cfg_paths, 'get_packaged_config_dir', lambda: packaged)
    monkeypatch.setattr(cfg_paths, 'get_external_config_dir', lambda: tmp_path / 'noext')
    cfg_paths.reconcile_external_configs()

    # bak exists + rename failure
    monkeypatch.setattr(cfg_paths, 'get_external_config_dir', lambda: external)
    (packaged / 'd.json').write_text('{"datetime":"2026-09-01 00:00:00"}', encoding='utf-8')
    (external / 'd.json').write_text('{"datetime":"2025-01-01 00:00:00","v":1}', encoding='utf-8')
    bak = external / 'd.json.20250101000000.bak'
    bak.write_text('old', encoding='utf-8')
    cfg_paths.reconcile_external_configs()
    assert not (external / 'd.json').exists()

    (packaged / 'e.json').write_text('{"datetime":"2026-09-01 00:00:00"}', encoding='utf-8')
    (external / 'e.json').write_text('{"datetime":"2025-01-01 00:00:00"}', encoding='utf-8')
    with patch.object(Path, 'rename', side_effect=OSError('x')):
        cfg_paths.reconcile_external_configs()


def test_drop_redundant_overlay_unlink_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """覆盖 drop_redundant_overlay 中 unlink 失败的 except OSError 分支。"""
    packaged = tmp_path / 'pkg'
    external = tmp_path / 'ext'
    packaged.mkdir()
    external.mkdir()
    monkeypatch.setattr(cfg_paths, 'get_packaged_config_dir', lambda: packaged)
    monkeypatch.setattr(cfg_paths, 'get_external_config_dir', lambda: external)
    monkeypatch.setattr(cfg_paths, '_config_dirs_are_same', lambda: False)
    (packaged / 'lock.json').write_bytes(b'same-bytes')
    target = external / 'lock.json'
    target.write_bytes(b'same-bytes')

    def _boom(self, *args, **kwargs):
        raise OSError('locked')

    monkeypatch.setattr(type(target), 'unlink', _boom)
    assert cfg_paths.drop_redundant_overlay('lock.json') is False
    assert target.exists()


def test_resolve_data_file_and_ensure_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg_paths, 'get_package_root', lambda: tmp_path)
    assert cfg_paths.resolve_data_file('../x.json').name == 'x.json'
    monkeypatch.setattr(cfg_paths, 'reconcile_external_configs', lambda: None)
    monkeypatch.setattr(cfg_paths, 'get_external_config_dir', lambda: tmp_path / 'ext')
    assert cfg_paths.ensure_config_dir() == tmp_path / 'ext'


# ---------------------------------------------------------------------------
# database
# ---------------------------------------------------------------------------


def test_build_database_urls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dbmod.DataBaseConfig, 'db_type', 'postgresql')
    monkeypatch.setattr(dbmod.DataBaseConfig, 'db_username', 'u')
    monkeypatch.setattr(dbmod.DataBaseConfig, 'db_password', 'p@ss')
    monkeypatch.setattr(dbmod.DataBaseConfig, 'db_host', 'h')
    monkeypatch.setattr(dbmod.DataBaseConfig, 'db_port', 5432)
    monkeypatch.setattr(dbmod.DataBaseConfig, 'db_database', 'db')
    assert 'postgresql+asyncpg://' in dbmod.build_async_sqlalchemy_database_url()
    assert 'postgresql+psycopg2://' in dbmod.build_sync_sqlalchemy_database_url()

    monkeypatch.setattr(dbmod.DataBaseConfig, 'db_type', 'sqlite')
    monkeypatch.setattr(dbmod, 'get_sqlite_path', lambda name: tmp_path / f'{name}.db')
    assert dbmod.build_async_sqlalchemy_database_url().startswith('sqlite+aiosqlite:///')
    assert dbmod.build_sync_sqlalchemy_database_url().startswith('sqlite:///')

    monkeypatch.setattr(dbmod.DataBaseConfig, 'db_type', 'mysql')
    assert 'mysql+asyncmy://' in dbmod.build_async_sqlalchemy_database_url()
    assert 'mysql+pymysql://' in dbmod.build_sync_sqlalchemy_database_url()


def test_create_engines_sqlite_and_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dbmod.DataBaseConfig, 'db_echo', False)
    monkeypatch.setattr(dbmod.DataBaseConfig, 'db_max_overflow', 1)
    monkeypatch.setattr(dbmod.DataBaseConfig, 'db_pool_size', 2)
    monkeypatch.setattr(dbmod.DataBaseConfig, 'db_pool_recycle', 3)
    monkeypatch.setattr(dbmod.DataBaseConfig, 'db_pool_timeout', 4)

    listeners: list = []

    def capture(target, event):
        def deco(fn):
            listeners.append((target, event, fn))
            return fn

        return deco

    async_engine = MagicMock()
    async_engine.sync_engine = MagicMock()
    sync_engine = MagicMock()

    monkeypatch.setattr(dbmod.DataBaseConfig, 'db_type', 'sqlite')
    with (
        patch('config.database.create_async_engine', return_value=async_engine) as cae,
        patch('config.database.create_engine', return_value=sync_engine) as ce,
        patch('config.database.event.listens_for', side_effect=capture),
    ):
        assert dbmod.create_async_db_engine(echo=False) is async_engine
        assert dbmod.create_sync_db_engine(echo=True) is sync_engine
        assert cae.called and ce.called

    # exercise find_in_set callbacks
    for _target, _event, fn in listeners:
        conn = MagicMock()
        created = {}

        def create_function(name, n, cb, _c=created):
            _c['cb'] = cb

        conn.create_function.side_effect = create_function
        fn(conn, None)
        assert created['cb'](None, '') == 0
        assert created['cb']('a', 'a,b') == 1
        assert created['cb']('z', 'a,b') == 0

    monkeypatch.setattr(dbmod.DataBaseConfig, 'db_type', 'mysql')
    with (
        patch('config.database.create_async_engine', return_value=async_engine) as cae2,
        patch('config.database.create_engine', return_value=sync_engine) as ce2,
    ):
        assert dbmod.create_async_db_engine() is async_engine
        assert dbmod.create_sync_db_engine() is sync_engine
        assert 'pool_size' in cae2.call_args.kwargs
        assert 'pool_size' in ce2.call_args.kwargs

    factory = dbmod.create_sync_session_local(sync_engine)
    assert factory is not None


# ---------------------------------------------------------------------------
# get_db / get_redis / env
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_db_and_lifecycle() -> None:
    session = MagicMock()

    class CM:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *a):
            return False

    with patch.object(get_db_mod, 'AsyncSessionLocal', return_value=CM()):
        gen = get_db_mod.get_db()
        assert await gen.__anext__() is session
        await gen.aclose()

    begin_cm = MagicMock()
    begin_cm.__aenter__ = AsyncMock(return_value=MagicMock(run_sync=AsyncMock()))
    begin_cm.__aexit__ = AsyncMock(return_value=False)
    fake_engine = MagicMock()
    fake_engine.begin.return_value = begin_cm
    fake_engine.dispose = AsyncMock()
    with patch.object(get_db_mod, 'async_engine', fake_engine):
        await get_db_mod.init_create_table()
        await get_db_mod.close_async_engine()
        fake_engine.dispose.assert_awaited()


@pytest.mark.asyncio
async def test_redis_util_all_branches() -> None:
    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    with patch.object(get_redis_mod.aioredis, 'from_url', new=AsyncMock(return_value=redis)):
        got = await get_redis_mod.RedisUtil.create_redis_pool(log_enabled=True)
        assert got is redis
        await get_redis_mod.RedisUtil.create_redis_pool(log_enabled=False, log_start_enabled=True)

    redis.ping = AsyncMock(return_value=False)
    await get_redis_mod.RedisUtil.check_redis_connection(redis, log_enabled=True)
    await get_redis_mod.RedisUtil.check_redis_connection(redis, log_enabled=False)

    for exc in (AuthenticationError('a'), RedisTimeoutError('t'), RedisError('r')):
        redis.ping = AsyncMock(side_effect=exc)
        await get_redis_mod.RedisUtil.check_redis_connection(redis, log_enabled=True)
        await get_redis_mod.RedisUtil.check_redis_connection(redis, log_enabled=False)

    app = SimpleNamespace(state=SimpleNamespace(redis=AsyncMock()))
    app.state.redis.close = AsyncMock()
    await get_redis_mod.RedisUtil.close_redis_pool(app)

    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    session_cm.__aexit__ = AsyncMock(return_value=False)
    with (
        patch.object(get_redis_mod, 'AsyncSessionLocal', return_value=session_cm),
        patch.object(get_redis_mod.DictDataService, 'init_cache_sys_dict_services', new=AsyncMock()) as d,
        patch.object(get_redis_mod.ConfigService, 'init_cache_sys_config_services', new=AsyncMock()) as c,
    ):
        await get_redis_mod.RedisUtil.init_sys_dict(redis)
        await get_redis_mod.RedisUtil.init_sys_config(redis)
        d.assert_awaited()
        c.assert_awaited()


def test_env_default_and_sqlglot_and_parse_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, 'argv', ['pytest'])
    assert envmod._default_app_env() == 'dev'
    monkeypatch.setattr(sys, 'argv', ['app.py'])
    assert envmod._default_app_env() == 'prod'
    monkeypatch.setattr(sys, 'argv', ['app.exe'])
    assert envmod._default_app_env() == 'prod'

    cfg = envmod.DataBaseSettings(db_type='postgresql')
    assert cfg.sqlglot_parse_dialect == 'postgres'
    cfg2 = envmod.DataBaseSettings(db_type='mysql')
    assert cfg2.sqlglot_parse_dialect == 'mysql'

    ini = tmp_path / 'alembic.ini'
    ini.write_text('[settings]\nenv = testenv\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['alembic', 'upgrade'])
    with (
        patch('config.env.load_dotenv'),
        patch('config.env.ensure_config_dir'),
        patch('config.env.resolve_dotenv_path', return_value=tmp_path / '.env.dev'),
    ):
        envmod.GetConfig.parse_cli_args()
        assert os.environ['APP_ENV'] == 'testenv'

    ini.write_text('[settings]\n', encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', [str(tmp_path / 'alembic')])
    with (
        patch('config.env.load_dotenv'),
        patch('config.env.ensure_config_dir'),
        patch('config.env.resolve_dotenv_path', return_value=tmp_path / '.env.dev'),
    ):
        envmod.GetConfig.parse_cli_args()
        assert os.environ['APP_ENV'] == 'dev'

    monkeypatch.setattr(sys, 'argv', ['uvicorn', 'app:app'])
    with (
        patch('config.env.load_dotenv'),
        patch('config.env.ensure_config_dir'),
        patch('config.env.resolve_dotenv_path', return_value=tmp_path / '.env.dev'),
    ):
        # uvicorn branch leaves APP_ENV as-is from environ
        os.environ['APP_ENV'] = 'uvicorn-env'
        envmod.GetConfig.parse_cli_args()


# ---------------------------------------------------------------------------
# exceptions / sub_applications / module_task
# ---------------------------------------------------------------------------


def test_handle_exception_handlers() -> None:
    app = FastAPI()

    @app.get('/boom/{kind}')
    async def boom(kind: str):
        mapping = {
            'auth': AuthException(data='d', message='m'),
            'login': LoginException(data='d', message='m'),
            'model': ModelValidatorException(data='d', message='m'),
            'perm': PermissionException(data='d', message='m'),
            'svc': ServiceException(data='d', message='m'),
            'warn': ServiceWarning(data='d', message='m'),
            'http': HTTPException(status_code=418, detail='teapot'),
            'disc': ClientDisconnect(),
            'exc': RuntimeError('x'),
        }
        raise mapping[kind]

    handle_exception(app)
    client = TestClient(app, raise_server_exceptions=False)
    for kind in ('auth', 'login', 'model', 'perm', 'svc', 'warn', 'http', 'exc'):
        r = client.get(f'/boom/{kind}')
        assert r.status_code != 500 or kind == 'exc'

    # FieldValidationError + ClientDisconnect via direct handler invoke
    from pydantic_validation_decorator import FieldValidationError

    handlers = app.exception_handlers
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
    }
    req = Request(scope)

    async def _run():
        fv = FieldValidationError(message='bad field')
        await handlers[FieldValidationError](req, fv)
        await handlers[ClientDisconnect](req, ClientDisconnect())

    asyncio.run(_run())


def test_sub_applications_and_module_task(monkeypatch: pytest.MonkeyPatch) -> None:
    app = MagicMock()
    with patch('sub_applications.staticfiles.StaticFiles') as SF:
        SF.return_value = MagicMock()
        mount_staticfiles(app)
        app.mount.assert_called_once()
    with patch('sub_applications.handle.mount_staticfiles') as m:
        handle_sub_applications(app)
        m.assert_called_once_with(app)

    scheduler_test.job(1, y=2)
    asyncio.run(scheduler_test.async_job(3, x=4))
    with patch(
        'module_task.payload_tm_partition_job.run_partition_maintenance',
        new=AsyncMock(),
    ) as run:
        asyncio.run(payload_tm_partition_job.job())
        run.assert_awaited()


def test_paths_leftover_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('PGT_DATA_DIR', str(tmp_path / 'data'))
    assert cfg_paths.get_logs_data_dir().name == 'logs_data'

    monkeypatch.setenv('SystemDrive', str(tmp_path / 'nosuchdrive').rstrip('\\/'))
    assert cfg_paths._windows_existing_pgt_local_bases() == []

    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    with patch.object(Path, 'resolve', side_effect=OSError('x')):
        base = cfg_paths._windows_local_appdata_base()
        assert base is not None

    user_local = tmp_path / 'Users' / 'zoe' / 'AppData' / 'Local'
    user_local.mkdir(parents=True)
    monkeypatch.delenv('LOCALAPPDATA', raising=False)
    monkeypatch.setattr(cfg_paths, '_windows_console_user_local_appdata', lambda: user_local)
    monkeypatch.setattr(cfg_paths, '_windows_existing_pgt_local_bases', lambda: [])
    assert cfg_paths._windows_local_appdata_base().resolve() == user_local.resolve()
    monkeypatch.undo()

    # re-apply data dir after undo
    monkeypatch.setenv('PGT_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('SystemDrive', str(tmp_path).rstrip('\\/'))

    class Buf:
        value = 'dave'

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class FakeWindll:
        class kernel32:
            @staticmethod
            def WTSGetActiveConsoleSessionId():
                return 9

        class wtsapi32:
            @staticmethod
            def WTSQuerySessionInformationW(server, sid, info, buf, nbytes):
                buf.value = 'dave'
                return 1

            @staticmethod
            def WTSFreeMemory(*a):
                return None

    class FakeCtypes:
        windll = FakeWindll()
        c_wchar_p = Buf
        byref = staticmethod(lambda x: x)

        class wintypes:
            DWORD = object

    def fake_enum(root, index):
        if index == 0:
            return 'S-1-5-21-dave'
        raise OSError('done')

    def fake_query(sid_key, name):
        raise OSError('no profile')

    class FakeWinreg:
        HKEY_LOCAL_MACHINE = 1
        OpenKey = staticmethod(lambda *a, **k: FakeKey())
        EnumKey = staticmethod(fake_enum)
        QueryValueEx = staticmethod(fake_query)
        CloseKey = staticmethod(lambda *a: None)

    # do not create Users/dave so guess path fails -> return None (141)
    saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k in {'ctypes', 'winreg'} or k.startswith('ctypes.')}
    try:
        with _install_fake_win_modules(FakeCtypes, FakeWinreg):
            assert cfg_paths._windows_console_user_local_appdata() is None
    finally:
        sys.modules.update(saved)

    packaged = tmp_path / 'pkg'
    external = tmp_path / 'ext'
    packaged.mkdir(exist_ok=True)
    external.mkdir(exist_ok=True)
    (packaged / 'dir.json').mkdir(exist_ok=True)
    monkeypatch.setattr(cfg_paths, 'get_packaged_config_dir', lambda: packaged)
    monkeypatch.setattr(cfg_paths, 'get_external_config_dir', lambda: external)
    monkeypatch.setattr(cfg_paths, '_config_dirs_are_same', lambda: False)
    cfg_paths.reconcile_external_configs()
