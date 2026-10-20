"""Coverage boost for utils: common_util, gen_util, server_util, log_util leftovers."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from sqlalchemy import Column, Integer, String, create_engine, text
from sqlalchemy.orm.collections import InstrumentedList

from common.constant import GenConstant
from config.database import Base
from config.env import AppConfig, CachePathConfig, GenConfig, LogConfig
from module_generator.entity.vo.gen_vo import GenTableColumnModel, GenTableModel
from utils import common_util, gen_util, log_util, server_util
from utils.common_util import (
    CamelCaseUtil,
    SnakeCaseUtil,
    SqlalchemyUtil,
    bytes2file_response,
    bytes2human,
    export_list2excel,
    get_excel_template,
    get_filepath_from_url,
    worship,
)
from utils.gen_util import GenUtils
from utils.log_util import (
    InterceptHandler,
    LoggerInitializer,
    LogSanitizer,
    _build_text_assignment_patterns,
    _build_text_key_pattern,
    _split_field_tokens,
)
from utils.server_util import APIDocsUtil, IPUtil, StartupUtil, WorkerIdUtil


# ---------------------------------------------------------------------------
# common_util
# ---------------------------------------------------------------------------


def _make_base_model(**kwargs):
    tn = f't_cov_{uuid.uuid4().hex[:10]}'
    cls_name = f'M_{tn}'
    cls = type(
        cls_name,
        (Base,),
        {
            '__tablename__': tn,
            'id': Column(Integer, primary_key=True),
            'user_name': Column(String),
        },
    )
    return cls(**({'id': 1, 'user_name': 'alice'} | kwargs))


class _FakeRow:
    """Stand-in used while patching utils.common_util.Row for isinstance branches."""

    def __init__(self, values, mapping=None):
        self._values = values
        self._mapping = mapping or {}

    def __iter__(self):
        return iter(self._values)

    def _asdict(self):
        return dict(self._mapping)


def test_worship_logs_without_error() -> None:
    with patch.object(common_util.logger, 'info') as mock_info:
        worship()
    mock_info.assert_called_once()
    assert '_ooOoo_' in mock_info.call_args.args[0]


def test_sqlalchemy_base_to_dict_and_case_transforms() -> None:
    obj = _make_base_model()
    obj.__dict__['kids'] = InstrumentedList()

    plain = SqlalchemyUtil.base_to_dict(obj)
    assert plain['user_name'] == 'alice'
    assert '_sa_instance_state' not in plain
    assert plain['kids'] == []

    camel = SqlalchemyUtil.base_to_dict(obj, 'snake_to_camel')
    assert camel['userName'] == 'alice'

    snake = SqlalchemyUtil.base_to_dict({'userName': 'bob'}, 'camel_to_snake')
    assert snake == {'user_name': 'bob'}

    no_case = SqlalchemyUtil.base_to_dict({'a': 1}, 'no_case')
    assert no_case == {'a': 1}


def test_sqlalchemy_serialize_result_variants() -> None:
    obj = _make_base_model()
    assert SqlalchemyUtil.serialize_result(obj)['user_name'] == 'alice'
    assert SqlalchemyUtil.serialize_result({'x': 1}) == {'x': 1}
    assert SqlalchemyUtil.serialize_result([{'a_b': 1}], 'snake_to_camel') == [{'aB': 1}]
    assert SqlalchemyUtil.serialize_result(42) == 42

    eng = create_engine('sqlite://')
    with eng.connect() as conn:
        row = conn.execute(text('select 1 as user_name, 2 as age')).one()
        assert SqlalchemyUtil.serialize_result(row) == {'user_name': 1, 'age': 2}
        assert SqlalchemyUtil.serialize_result(row, 'snake_to_camel') == {'userName': 1, 'age': 2}
        assert SqlalchemyUtil.serialize_result(row, 'camel_to_snake') == {'user_name': 1, 'age': 2}
    eng.dispose()

    m1, m2 = _make_base_model(), _make_base_model(user_name='b')
    with patch.object(common_util, 'Row', _FakeRow):
        all_base = SqlalchemyUtil.serialize_result(_FakeRow([m1, m2]))
        assert len(all_base) == 2
        mixed = SqlalchemyUtil.serialize_result(_FakeRow([m1, 'x']))
        assert mixed[1] == 'x'
        plain_row = SqlalchemyUtil.serialize_result(
            _FakeRow([1, 2], {'user_name': 1, 'age': 2}), 'snake_to_camel'
        )
        assert plain_row == {'userName': 1, 'age': 2}
        plain_snake = SqlalchemyUtil.serialize_result(
            _FakeRow([1], {'userName': 1}), 'camel_to_snake'
        )
        assert plain_snake == {'user_name': 1}
        plain_no = SqlalchemyUtil.serialize_result(_FakeRow([1], {'a': 1}))
        assert plain_no == {'a': 1}


def test_get_server_default_null() -> None:
    assert SqlalchemyUtil.get_server_default_null('postgresql', True) is not None
    assert SqlalchemyUtil.get_server_default_null('postgresql', False) is None
    assert SqlalchemyUtil.get_server_default_null('mysql', True) is None


def test_camel_snake_case_utils() -> None:
    assert CamelCaseUtil.snake_to_camel('user_name') == 'userName'
    assert SnakeCaseUtil.camel_to_snake('userName') == 'user_name'
    assert CamelCaseUtil.transform_result({'user_name': 1}) == {'userName': 1}
    assert SnakeCaseUtil.transform_result({'userName': 1}) == {'user_name': 1}


def test_bytes2human_and_file_response() -> None:
    assert bytes2human(100) == '100.0B'
    assert 'K' in bytes2human(10000)
    assert 'M' in bytes2human(100001221)
    assert list(bytes2file_response(b'abc')) == [b'abc']


def test_export_list2excel_and_template() -> None:
    data = export_list2excel([{'a': 1, 'b': 2}])
    assert isinstance(data, bytes) and len(data) > 0

    template = get_excel_template(
        header_list=['姓名', '状态'],
        selector_header_list=['状态'],
        option_list=[{'状态': ['启用', '停用']}, {'其他': ['x']}],
    )
    assert isinstance(template, bytes) and len(template) > 0


def test_get_filepath_from_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(CachePathConfig, 'PATH', str(tmp_path))
    url = 'http://x/download?id=tid&fileName=a.txt&path=sub'
    path = get_filepath_from_url(url)
    assert path == os.path.join(str(tmp_path), 'sub', 'tid', 'a.txt')


# ---------------------------------------------------------------------------
# gen_util
# ---------------------------------------------------------------------------


def _column(**kwargs) -> GenTableColumnModel:
    defaults = dict(
        columnName='user_name',
        columnType='varchar(64)',
        columnComment='用户名',
        pythonField='userName',
        isPk='0',
    )
    defaults.update(kwargs)
    return GenTableColumnModel(**defaults)


def _table(**kwargs) -> GenTableModel:
    defaults = dict(
        tableId=1,
        tableName='sys_user',
        tableComment='用户表',
        createBy='admin',
        updateBy='admin',
    )
    defaults.update(kwargs)
    return GenTableModel(**defaults)


def test_gen_utils_init_table_and_helpers(monkeypatch) -> None:
    monkeypatch.setattr(GenConfig, 'package_name', 'module_admin.system')
    monkeypatch.setattr(GenConfig, 'author', 'tester')
    monkeypatch.setattr(GenConfig, 'auto_remove_pre', True)
    monkeypatch.setattr(GenConfig, 'table_prefix', 'sys_,biz_')

    table = _table()
    GenUtils.init_table(table, 'oper')
    assert table.class_name == 'User'
    assert table.module_name == 'system'
    assert table.business_name == 'user'
    assert table.function_name == '用户'
    assert table.function_author == 'tester'
    assert table.create_by == 'oper'

    assert GenUtils.arrays_contains(['a', 'b'], 'a') is True
    assert GenUtils.arrays_contains(['a'], 'z') is False
    assert GenUtils.get_module_name('a.b.c') == 'c'
    assert GenUtils.get_business_name('sys_user') == 'user'
    assert GenUtils.replace_first('sys_user', ['sys_', 'biz_']) == 'user'
    assert GenUtils.replace_first('other', ['sys_']) == 'other'
    assert GenUtils.replace_text('若依用户表') == '用户'
    assert GenUtils.get_db_type('varchar(64)') == 'varchar'
    assert GenUtils.get_db_type('int') == 'int'
    assert GenUtils.get_column_length('varchar(64)') == 2  # len('64')
    assert GenUtils.get_column_length('int') == 0
    assert GenUtils.split_column_type('decimal(10,2)') == ['10', '2']
    assert GenUtils.split_column_type('int') == []
    assert GenUtils.to_camel_case('user_name') == 'userName'

    monkeypatch.setattr(GenConfig, 'auto_remove_pre', False)
    assert GenUtils.convert_class_name('sys_user') == 'SysUser'
    monkeypatch.setattr(GenConfig, 'auto_remove_pre', True)
    monkeypatch.setattr(GenConfig, 'table_prefix', '')
    assert GenUtils.convert_class_name('sys_user') == 'SysUser'


@pytest.mark.parametrize(
    'column_name,column_type,is_pk,expect_html,expect_query',
    [
        ('remark', 'varchar(64)', '0', GenConstant.HTML_INPUT, GenConstant.QUERY_EQ),
        ('body', f'varchar({"x" * 500})', '0', GenConstant.HTML_TEXTAREA, GenConstant.QUERY_EQ),
        ('note', 'text', '0', GenConstant.HTML_TEXTAREA, GenConstant.QUERY_EQ),
        ('create_time', 'datetime', '0', GenConstant.HTML_DATETIME, GenConstant.QUERY_EQ),
        ('amount', 'int', '0', GenConstant.HTML_INPUT, GenConstant.QUERY_EQ),
        ('user_name', 'varchar(32)', '0', GenConstant.HTML_INPUT, GenConstant.QUERY_LIKE),
        ('order_status', 'char(1)', '0', GenConstant.HTML_RADIO, GenConstant.QUERY_EQ),
        ('user_type', 'varchar(16)', '0', GenConstant.HTML_SELECT, GenConstant.QUERY_EQ),
        ('user_sex', 'char(1)', '0', GenConstant.HTML_SELECT, GenConstant.QUERY_EQ),
        ('avatar_image', 'varchar(128)', '0', GenConstant.HTML_IMAGE_UPLOAD, GenConstant.QUERY_EQ),
        ('attach_file', 'varchar(128)', '0', GenConstant.HTML_FILE_UPLOAD, GenConstant.QUERY_EQ),
        ('post_content', 'text', '0', GenConstant.HTML_EDITOR, GenConstant.QUERY_EQ),
        ('id', 'bigint', '1', GenConstant.HTML_INPUT, GenConstant.QUERY_EQ),
        ('create_by', 'varchar(64)', '0', GenConstant.HTML_INPUT, GenConstant.QUERY_EQ),
    ],
)
def test_gen_utils_init_column_field_branches(
    column_name, column_type, is_pk, expect_html, expect_query
) -> None:
    table = _table()
    column = _column(columnName=column_name, columnType=column_type, isPk=is_pk)
    GenUtils.init_column_field(column, table)
    assert column.html_type == expect_html
    assert column.query_type == expect_query
    assert column.table_id == table.table_id
    assert column.is_insert == GenConstant.REQUIRE
    if is_pk != '1' and column_name not in GenConstant.COLUMNNAME_NOT_EDIT:
        assert column.is_edit == GenConstant.REQUIRE


# ---------------------------------------------------------------------------
# server_util
# ---------------------------------------------------------------------------


def test_api_docs_util_url_helpers(monkeypatch) -> None:
    monkeypatch.setattr(AppConfig, 'app_disable_swagger', False)
    monkeypatch.setattr(AppConfig, 'app_disable_redoc', False)
    assert APIDocsUtil.proxy_openapi_url() == APIDocsUtil._PROXY_OPENAPI_URL
    assert APIDocsUtil.docs_url() == APIDocsUtil._DOCS_URL
    assert APIDocsUtil.proxy_docs_url() == APIDocsUtil._PROXY_DOCS_URL
    assert APIDocsUtil.redoc_url() == APIDocsUtil._REDOC_URL
    assert APIDocsUtil.proxy_redoc_url() == APIDocsUtil._PROXY_REDOC_URL
    assert APIDocsUtil.proxy_oauth2_redirect_url() == APIDocsUtil._PROXY_OAUTH2_REDIRECT_URL

    monkeypatch.setattr(AppConfig, 'app_disable_swagger', True)
    monkeypatch.setattr(AppConfig, 'app_disable_redoc', True)
    assert APIDocsUtil.proxy_openapi_url() is None
    assert APIDocsUtil.proxy_docs_url() is None
    assert APIDocsUtil.proxy_redoc_url() is None
    assert APIDocsUtil.proxy_oauth2_redirect_url() is None


def test_api_docs_setup_and_custom_router(monkeypatch) -> None:
    monkeypatch.setattr(AppConfig, 'app_disable_swagger', False)
    monkeypatch.setattr(AppConfig, 'app_disable_redoc', False)
    APIDocsUtil.setup_docs_static_resources()
    from fastapi import applications as fastapi_apps

    html = fastapi_apps.get_redoc_html(openapi_url='/o', title='t')
    assert html.status_code == 200
    html2 = fastapi_apps.get_swagger_ui_html(openapi_url='/o', title='t')
    assert html2.status_code == 200

    app = FastAPI(title='CovApp', version='0.0.1')
    APIDocsUtil.custom_api_docs_router(app)
    paths = {getattr(r, 'path', None) for r in app.routes}
    assert APIDocsUtil._OPENAPI_URL in paths
    assert APIDocsUtil._DOCS_URL in paths
    assert APIDocsUtil._REDOC_URL in paths
    assert APIDocsUtil._OAUTH2_REDIRECT_URL in paths


@pytest.mark.asyncio
async def test_api_docs_registered_route_wrappers(monkeypatch) -> None:
    monkeypatch.setattr(AppConfig, 'app_disable_swagger', False)
    monkeypatch.setattr(AppConfig, 'app_disable_redoc', False)
    app = FastAPI(title='WrapApp', version='0.0.1')
    APIDocsUtil.custom_api_docs_router(app)
    route_map = {getattr(r, 'path', None): r for r in app.routes}
    dummy_req = MagicMock()
    for path in (
        APIDocsUtil._OPENAPI_URL,
        APIDocsUtil._DOCS_URL,
        APIDocsUtil._REDOC_URL,
        APIDocsUtil._OAUTH2_REDIRECT_URL,
    ):
        resp = await route_map[path].endpoint(dummy_req)
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_docs_handlers_enabled_and_disabled(monkeypatch) -> None:
    app = FastAPI(title='DocApp')
    monkeypatch.setattr(AppConfig, 'app_disable_swagger', False)
    monkeypatch.setattr(AppConfig, 'app_disable_redoc', False)

    openapi = await APIDocsUtil._custom_openapi(app)
    assert openapi.status_code == 200

    redoc = await APIDocsUtil._custom_redoc(app, APIDocsUtil.DEFAULT_REDOC_JS_URL, APIDocsUtil.DEFAULT_REDOC_FAVICON_URL)
    assert 'redoc' in redoc.body.decode().lower() or redoc.status_code == 200

    swagger = await APIDocsUtil._custom_swagger(
        app,
        APIDocsUtil.DEFAULT_SWAGGER_JS_URL,
        APIDocsUtil.DEFAULT_SWAGGER_CSS_URL,
        APIDocsUtil.DEFAULT_SWAGGER_FAVICON_URL,
    )
    assert swagger.status_code == 200

    redirect = await APIDocsUtil._custom_swagger_ui_redirect(app, APIDocsUtil.DEFAULT_SWAGGER_FAVICON_URL)
    assert redirect.status_code == 200

    monkeypatch.setattr(AppConfig, 'app_disable_swagger', True)
    monkeypatch.setattr(AppConfig, 'app_disable_redoc', True)
    disabled_redoc = await APIDocsUtil._custom_redoc(
        app, APIDocsUtil.DEFAULT_REDOC_JS_URL, APIDocsUtil.DEFAULT_REDOC_FAVICON_URL
    )
    assert 'disabled' in disabled_redoc.body.decode().lower()
    disabled_swagger = await APIDocsUtil._custom_swagger(
        app,
        APIDocsUtil.DEFAULT_SWAGGER_JS_URL,
        APIDocsUtil.DEFAULT_SWAGGER_CSS_URL,
        APIDocsUtil.DEFAULT_SWAGGER_FAVICON_URL,
    )
    assert 'disabled' in disabled_swagger.body.decode().lower()
    disabled_redirect = await APIDocsUtil._custom_swagger_ui_redirect(app, APIDocsUtil.DEFAULT_SWAGGER_FAVICON_URL)
    assert 'disabled' in disabled_redirect.body.decode().lower()

    app2 = FastAPI()
    APIDocsUtil._register_docs_routes(app2, lambda r: None, lambda r: None, lambda r: None)
    paths = {getattr(r, 'path', None) for r in app2.routes}
    assert APIDocsUtil._PROXY_DOCS_URL in paths
    assert APIDocsUtil._PROXY_REDOC_URL in paths
    assert APIDocsUtil._PROXY_OAUTH2_REDIRECT_URL in paths


@pytest.mark.asyncio
async def test_startup_util_lock_and_renewal() -> None:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    assert await StartupUtil.acquire_startup_log_gate(redis, 'k', 'w1', 10) is True

    redis.set = AsyncMock(return_value=False)
    redis.get = AsyncMock(return_value='w1')
    assert await StartupUtil.acquire_startup_log_gate(redis, 'k', 'w1', 10) is True
    redis.get = AsyncMock(return_value='other')
    assert await StartupUtil.acquire_startup_log_gate(redis, 'k', 'w1', 10) is False

    lost = []
    redis.get = AsyncMock(side_effect=['w1', 'other'])
    redis.expire = AsyncMock()
    task = StartupUtil.start_lock_renewal(
        redis, 'k', 'w1', 10, 0.01, on_lock_lost=lambda: lost.append(1)
    )
    await asyncio.wait_for(task, timeout=2)
    assert lost == [1]

    # exception path then lock lost
    redis.get = AsyncMock(side_effect=[RuntimeError('boom'), 'other'])
    redis.expire = AsyncMock()
    task2 = StartupUtil.start_lock_renewal(redis, 'k', 'w1', 10, 0.01, on_lock_lost=None)
    await asyncio.wait_for(task2, timeout=2)


def test_worker_id_util(monkeypatch) -> None:
    WorkerIdUtil._worker_id = None
    wid = WorkerIdUtil.get_worker_id('fixed-worker')
    assert wid == 'fixed-worker'
    assert WorkerIdUtil.get_worker_id('ignored') == 'fixed-worker'

    WorkerIdUtil._worker_id = None
    auto = WorkerIdUtil.get_worker_id('auto')
    assert '-' in auto
    WorkerIdUtil._worker_id = None
    auto2 = WorkerIdUtil.get_worker_id(None)
    assert '-' in auto2
    WorkerIdUtil._worker_id = None


def test_ip_util_local_and_network(monkeypatch) -> None:
    loop_snic = SimpleNamespace(family=socket.AF_INET, address='127.0.0.1')
    net_snic = SimpleNamespace(family=socket.AF_INET, address='10.0.0.5')
    link_local = SimpleNamespace(family=socket.AF_INET, address='169.254.1.1')
    bad_snic = SimpleNamespace(family=socket.AF_INET, address='not-an-ip')
    other_fam = SimpleNamespace(family=socket.AF_INET6, address='::1')

    with patch.object(
        server_util.psutil,
        'net_if_addrs',
        return_value={'lo': [loop_snic, other_fam], 'eth0': [net_snic]},
    ):
        assert IPUtil.get_local_ip() == '127.0.0.1'

    with patch.object(server_util.psutil, 'net_if_addrs', side_effect=RuntimeError('x')):
        assert IPUtil.get_local_ip() == '127.0.0.1'

    stats = {
        'eth0': SimpleNamespace(isup=True),
        'down0': SimpleNamespace(isup=False),
    }
    addrs = {
        'eth0': [net_snic, link_local, bad_snic, other_fam],
        'down0': [SimpleNamespace(family=socket.AF_INET, address='10.0.0.9')],
        'eth1': [SimpleNamespace(family=socket.AF_INET, address='10.0.0.8')],
    }

    class _Sock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def settimeout(self, *_a):
            return None

        def connect(self, *_a):
            return None

        def getsockname(self):
            return ('10.0.0.5', 0)

    with (
        patch.object(server_util.psutil, 'net_if_stats', return_value=stats),
        patch.object(server_util.psutil, 'net_if_addrs', return_value=addrs),
        patch.object(server_util.socket, 'socket', return_value=_Sock()),
    ):
        ips = IPUtil.get_network_ips()
    assert ips[0] == '10.0.0.5'
    assert '10.0.0.8' in ips
    assert '10.0.0.9' not in ips
    assert '169.254.1.1' not in ips

    class _FailSock(_Sock):
        def connect(self, *_a):
            raise OSError('fail')

    with (
        patch.object(server_util.psutil, 'net_if_stats', return_value={}),
        patch.object(server_util.psutil, 'net_if_addrs', return_value={}),
        patch.object(server_util.socket, 'socket', return_value=_FailSock()),
    ):
        assert IPUtil.get_network_ips() == ['127.0.0.1']

    with (
        patch.object(server_util.psutil, 'net_if_stats', side_effect=RuntimeError('x')),
        patch.object(server_util.psutil, 'net_if_addrs', side_effect=RuntimeError('x')),
        patch.object(server_util.socket, 'socket', return_value=_FailSock()),
    ):
        assert IPUtil.get_network_ips() == ['127.0.0.1']

    # preferred IP not already in list → insert only
    class _PrefSock(_Sock):
        def getsockname(self):
            return ('192.168.1.50', 0)

    with (
        patch.object(server_util.psutil, 'net_if_stats', return_value={'eth0': SimpleNamespace(isup=True)}),
        patch.object(
            server_util.psutil,
            'net_if_addrs',
            return_value={'eth0': [SimpleNamespace(family=socket.AF_INET, address='10.0.0.5')]},
        ),
        patch.object(server_util.socket, 'socket', return_value=_PrefSock()),
    ):
        ips2 = IPUtil.get_network_ips()
    assert ips2[0] == '192.168.1.50'
    assert '10.0.0.5' in ips2


# ---------------------------------------------------------------------------
# log_util remaining branches
# ---------------------------------------------------------------------------


def test_log_split_and_key_pattern_edge_cases() -> None:
    assert _split_field_tokens('!!!') == ()
    assert _build_text_key_pattern('!!!') == '!!!'
    assert _build_text_assignment_patterns('') == []


def test_log_sanitizer_disabled_and_special_types() -> None:
    with patch.object(LogConfig, 'log_mask_enabled', False):
        assert LogSanitizer.sanitize_data({'password': 'x'}) == {'password': 'x'}

    class _Model:
        def model_dump(self, by_alias=True, exclude_none=True):
            return {'password': 'secret'}

    with patch.object(LogConfig, 'log_mask_enabled', True):
        assert LogSanitizer.sanitize_data(_Model())['password'] == LogSanitizer._MASK
        assert LogSanitizer.sanitize_data(b'abc') == '<bytes:3>'
        assert LogSanitizer.sanitize_data(None) is None
        # sanitize_text non-str with mask enabled
        assert LogSanitizer.sanitize_text(123) == 123  # type: ignore[arg-type]
        # captchacode/smscode branch is after _SENSITIVE_FIELDS — force empty to hit it
        with patch.object(LogSanitizer, '_SENSITIVE_FIELDS', set()):
            assert LogSanitizer._should_fully_mask_field('captchacode', 'ABCD') is True
            assert LogSanitizer._should_fully_mask_field('smscode', '123456') is True

    with patch.object(LogConfig, 'log_mask_enabled', False):
        assert LogSanitizer.sanitize_text(123) == 123  # type: ignore[arg-type]


def test_log_sanitizer_string_field_and_literal_eval() -> None:
    with patch.object(LogConfig, 'log_mask_enabled', True):
        assert LogSanitizer.sanitize_data('plain', 'password') == LogSanitizer._MASK
        assert '****' in LogSanitizer.sanitize_data('13812345678', 'phonenumber')

        # invalid json then literal_eval success
        text = "{'password': 'abc', 'ok': 1}"
        out = LogSanitizer._sanitize_string(text)
        assert isinstance(out, str)
        assert 'abc' not in out

        # invalid json and invalid literal → fall through to kv patterns
        messy = '{not-json password=secret'
        out2 = LogSanitizer._sanitize_string(messy)
        assert 'secret' not in out2

        # dump structured non-dict/list
        assert LogSanitizer._dump_sanitized_structured_text('x', 'x') == 'x'

        assert LogSanitizer._should_fully_mask_field('smscode', '1234') is True
        assert LogSanitizer._mask_partial_value('x', 'unknown') == LogSanitizer._MASK
        assert LogSanitizer._mask_phone('123') == LogSanitizer._MASK
        assert LogSanitizer._mask_email('no-at') == LogSanitizer._MASK
        assert LogSanitizer._mask_ip('1.2.3') == LogSanitizer._MASK
        assert LogSanitizer._mask_ip('a:b:c:d') == 'a:b:*:*'
        assert LogSanitizer._mask_ip('notaip') == LogSanitizer._MASK


def test_log_replace_quote_none_branches() -> None:
    match = MagicMock()
    match.group.side_effect = lambda name: 'prefix=' if name == 'prefix' else 'val'
    match.groupdict.return_value = {'quote': None, 'key': 'password'}
    assert '******' in LogSanitizer._replace_text_secret(match)

    match2 = MagicMock()
    match2.group.side_effect = lambda name: 'email=' if name == 'prefix' else 'a@b.com'
    match2.groupdict.return_value = {'quote': None, 'key': 'email'}
    assert '@' in LogSanitizer._replace_text_partial_secret(match2)


def test_intercept_handler_and_initializer_filters(tmp_path, monkeypatch) -> None:
    handler = InterceptHandler()
    record = logging.LogRecord('n', logging.INFO, __file__, 1, 'hello', (), None)
    with patch.object(handler, 'target_logger') as tl:
        tl.level.side_effect = ValueError('bad')
        tl.opt.return_value = tl
        handler.emit(record)
        tl.log.assert_called()

    # walk logging frames depth loop
    record2 = logging.LogRecord('n', logging.WARNING, logging.__file__, 1, 'x', (), None)
    with patch.object(handler, 'target_logger') as tl2:
        tl2.level.return_value = SimpleNamespace(name='WARNING')
        tl2.opt.return_value = tl2
        with patch('utils.log_util.logging.currentframe') as cf:
            frame1 = SimpleNamespace(f_code=SimpleNamespace(co_filename=logging.__file__), f_back=None)
            # first frame is logging, then None
            outer = SimpleNamespace(f_code=SimpleNamespace(co_filename=logging.__file__), f_back=None)
            cf.return_value = outer
            handler.emit(record2)
            tl2.log.assert_called()

    monkeypatch.setattr(LogConfig, 'log_file_enabled', False)
    init = LoggerInitializer()
    init._ensure_log_directory_exists()

    monkeypatch.setattr(LogConfig, 'log_file_enabled', True)
    monkeypatch.setattr(LogConfig, 'log_file_base_dir', str(tmp_path / 'logs_new'))
    init2 = LoggerInitializer()
    assert os.path.isdir(init2._log_base_dir)

    record_dict = {
        'extra': {'startup_phase': True, 'startup_log_enabled': False},
        'message': 'm',
    }
    with patch.object(LogSanitizer, 'sanitize_data', side_effect=lambda d, *a, **k: d):
        assert init2._filter(record_dict) is False
        record_dict['extra']['startup_log_enabled'] = True
        assert init2._filter(record_dict) is True

    assert init2._get_exception_value_text(None) is None
    assert init2._get_exception_value_text(SimpleNamespace(value=None)) is None
    assert init2._get_exception_traceback_text(None) is None
    assert init2._get_exception_traceback_text(SimpleNamespace(traceback=None)) is None
    assert (
        init2._get_exception_traceback_text(SimpleNamespace(traceback='tb text', type=None, value=None))
        == 'tb text'
    )
    assert (
        init2._get_exception_traceback_text(SimpleNamespace(traceback=123, type=None, value=None)) == '123'
    )

    level = SimpleNamespace(name='INFO', no=logging.INFO)
    rec = {'level': level, 'extra': {}}
    with patch.object(init2, '_filter', return_value=True):
        assert init2._info_file_filter(rec) is True
        warn = {'level': SimpleNamespace(name='WARNING', no=logging.WARNING), 'extra': {}}
        assert init2._error_file_filter(warn) is True


def test_logger_initializer_init_log_json_and_plain(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(LogConfig, 'log_file_enabled', True)
    monkeypatch.setattr(LogConfig, 'log_file_base_dir', str(tmp_path))
    monkeypatch.setattr(LogConfig, 'loguru_stdout', True)
    monkeypatch.setattr(LogConfig, 'loguru_json', True)
    monkeypatch.setattr(LogConfig, 'loguru_level', 'INFO')
    monkeypatch.setattr(LogConfig, 'loguru_rotation', '10 MB')
    monkeypatch.setattr(LogConfig, 'loguru_retention', '7 days')
    monkeypatch.setattr(LogConfig, 'loguru_compression', None)

    init = LoggerInitializer()
    with patch.object(log_util._logger, 'patch', return_value=log_util._logger), patch.object(
        log_util._logger, 'remove'
    ), patch.object(log_util._logger, 'add') as add, patch.object(init, '_configure_logging'):
        out = init.init_log()
        assert out is log_util._logger
        assert add.call_count >= 3  # stdout + info + error

    monkeypatch.setattr(LogConfig, 'loguru_json', False)
    with patch.object(log_util._logger, 'patch', return_value=log_util._logger), patch.object(
        log_util._logger, 'remove'
    ), patch.object(log_util._logger, 'add') as add2, patch.object(init, '_configure_logging'):
        init.init_log()
        assert add2.call_count >= 3

    monkeypatch.setattr(LogConfig, 'loguru_stdout', False)
    monkeypatch.setattr(LogConfig, 'log_file_enabled', False)
    init_nofile = LoggerInitializer()
    with patch.object(log_util._logger, 'patch', return_value=log_util._logger), patch.object(
        log_util._logger, 'remove'
    ), patch.object(log_util._logger, 'add') as add3, patch.object(init_nofile, '_configure_logging'):
        init_nofile.init_log()
        add3.assert_not_called()
