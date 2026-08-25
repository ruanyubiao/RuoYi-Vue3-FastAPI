"""SQLite find_in_set 兼容、采集 runner 类型分发、插件包再导出。"""

from __future__ import annotations

import inspect

import pytest

from config import database as dbmod
from module_payload.collectors import plugins as plugins_pkg
from module_payload.collectors.plugins.registry import PLUGIN_ID_CAMERA_IMAGE
from module_payload.collectors.redis_sync import dumps_json, loads_json
from module_payload.collectors.runner import run_collector


def _find_in_set(value, set_str):
    """与 config.database 注册的 SQLite 函数语义一致。"""
    if not set_str:
        return 0
    return 1 if str(value) in set_str.split(',') else 0


def test_sqlite_find_in_set_registered_in_engine_source() -> None:
    src = inspect.getsource(dbmod.create_sync_db_engine) + inspect.getsource(dbmod.create_async_db_engine)
    assert 'create_function("find_in_set"' in src.replace("'", '"') or "create_function('find_in_set'" in src
    assert 'str(value) in set_str.split' in src


def test_find_in_set_semantics() -> None:
    assert _find_in_set('admin', 'admin,common') == 1
    assert _find_in_set('x', 'admin,common') == 0
    assert _find_in_set('admin', '') == 0
    assert _find_in_set(1, '1,2,3') == 1
    assert _find_in_set('1', '11,21') == 0


def test_run_collector_unknown_type() -> None:
    with pytest.raises(ValueError, match='未知采集类型'):
        run_collector('foo', 'x', {})


def test_plugin_package_reexports() -> None:
    assert plugins_pkg.resolve_plugin_id_for_source('camera_image') == PLUGIN_ID_CAMERA_IMAGE
    assert plugins_pkg.resolve_plugin_id_for_source('home') is None
    plugin = plugins_pkg.create_serial_plugin(PLUGIN_ID_CAMERA_IMAGE)
    assert plugin is not None
    assert plugin.plugin_id == PLUGIN_ID_CAMERA_IMAGE
    assert plugins_pkg.create_serial_plugin(None) is None
    ids = {p['id'] for p in plugins_pkg.list_serial_plugins()}
    assert PLUGIN_ID_CAMERA_IMAGE in ids


def test_redis_sync_json() -> None:
    assert loads_json(None) is None
    assert loads_json('') is None
    text = dumps_json({'ok': True, 'msg': '中文'})
    assert '中文' in text
    assert loads_json(text)['ok'] is True
