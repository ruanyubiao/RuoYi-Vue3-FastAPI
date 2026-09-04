"""Raise coverage of utils modules toward 99%+ (batch A)."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request, UploadFile
from pydantic import BaseModel
from starlette.background import BackgroundTask

from common.constant import HttpStatusConstant
from common.context import RequestContext
from common.enums import HttpMethod
from config.database import Base
from config.env import AppConfig, UploadConfig
from exceptions.exception import PermissionException
from utils.api_annotation_util import ApiAnnotationUtil
from utils.api_response_header_util import ApiResponseHeaderUtil
from utils.client_ip_util import ClientIPUtil
from utils.cron_util import CronUtil
from utils.dependency_util import DependencyUtil
from utils.excel_util import ExcelUtil
from utils.import_util import ImportUtil
from utils.message_util import message_service
from utils.page_util import PageUtil, get_page_obj
from utils.pwd_util import PwdUtil
from utils.response_util import ResponseUtil
from utils.string_util import StringUtil
from utils.time_format_util import (
    TimeFormatUtil,
    format_datetime_dict_list,
    list_format_datetime,
    object_format_datetime,
)
from utils.upload_util import UploadUtil


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_request(
    *,
    path: str = '/api/test',
    method: str = 'GET',
    headers: dict[str, str] | None = None,
    client_host: str | None = '127.0.0.1',
    redis: object | None = ...,
) -> Request:
    header_items = []
    if headers:
        for key, value in headers.items():
            header_items.append((key.lower().encode('latin-1'), value.encode('latin-1')))
    app_state = SimpleNamespace()
    if redis is not ...:
        app_state.redis = redis
    app = SimpleNamespace(state=app_state)
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0'},
        'http_version': '1.1',
        'method': method,
        'scheme': 'http',
        'path': path,
        'raw_path': path.encode(),
        'query_string': b'',
        'headers': header_items,
        'client': (client_host, 12345) if client_host is not None else None,
        'server': ('testserver', 80),
        'root_path': '',
        'app': app,
    }
    return Request(scope)


class _SampleModel(BaseModel):
    user_name: str = 'admin'

    model_config = {'populate_by_name': True}


# ---------------------------------------------------------------------------
# pwd_util
# ---------------------------------------------------------------------------


def test_pwd_util_hash_and_verify() -> None:
    hashed = PwdUtil.get_password_hash('secret-pass')
    assert hashed.startswith('$2')
    assert PwdUtil.verify_password('secret-pass', hashed) is True
    assert PwdUtil.verify_password('wrong', hashed) is False


def test_pwd_util_verify_empty_hash_returns_none() -> None:
    assert PwdUtil.verify_password('any', '') is None


# ---------------------------------------------------------------------------
# message_util
# ---------------------------------------------------------------------------


def test_message_service_logs_code() -> None:
    with patch('utils.message_util.logger.info') as mock_info:
        message_service('A1B2')
    mock_info.assert_called_once()
    assert 'A1B2' in mock_info.call_args.args[0]


# ---------------------------------------------------------------------------
# api_response_header_util
# ---------------------------------------------------------------------------


def test_api_response_header_merge_none_and_empty() -> None:
    request = _make_request()
    ApiResponseHeaderUtil.merge_headers(request, None)
    ApiResponseHeaderUtil.merge_headers(request, {})
    assert not hasattr(request.state, 'api_response_headers') or not request.state.api_response_headers


def test_api_response_header_merge_and_update() -> None:
    request = _make_request()
    ApiResponseHeaderUtil.merge_headers(request, {'X-A': '1'})
    assert request.state.api_response_headers == {'X-A': '1'}
    ApiResponseHeaderUtil.merge_headers(request, {'X-B': '2'})
    assert request.state.api_response_headers == {'X-A': '1', 'X-B': '2'}


# ---------------------------------------------------------------------------
# api_annotation_util
# ---------------------------------------------------------------------------


async def _annotated_endpoint(request: Request, value: int = 1) -> int:
    return value


def test_api_annotation_get_request_from_args_and_kwargs() -> None:
    request = _make_request()
    assert ApiAnnotationUtil.get_request(_annotated_endpoint, request) is request
    assert ApiAnnotationUtil.get_request(_annotated_endpoint, request=request) is request
    assert ApiAnnotationUtil.get_request(_annotated_endpoint, value=2) is None


def test_api_annotation_get_redis_client() -> None:
    redis = object()
    request = _make_request(redis=redis)
    assert ApiAnnotationUtil.get_redis_client(request, 'skip') is redis

    bare = _make_request()
    with patch('utils.api_annotation_util.logger.warning') as mock_warning:
        assert ApiAnnotationUtil.get_redis_client(bare, 'no redis') is None
    mock_warning.assert_called_once_with('no redis')


def test_api_annotation_resolve_request_redis() -> None:
    redis = object()
    request = _make_request(redis=redis)
    got_req, got_redis = ApiAnnotationUtil.resolve_request_redis(
        _annotated_endpoint, 'skip', request
    )
    assert got_req is request
    assert got_redis is redis

    none_req, none_redis = ApiAnnotationUtil.resolve_request_redis(
        _annotated_endpoint, 'skip', value=1
    )
    assert none_req is None and none_redis is None


def test_api_annotation_normalize_http_methods() -> None:
    assert ApiAnnotationUtil.normalize_http_methods(None) == ()
    assert ApiAnnotationUtil.normalize_http_methods(None, None) == ()
    assert ApiAnnotationUtil.normalize_http_methods(None, [HttpMethod.GET]) == ('GET',)
    assert ApiAnnotationUtil.normalize_http_methods(
        [HttpMethod.GET, HttpMethod.POST, HttpMethod.GET]
    ) == ('GET', 'POST')
    with pytest.raises(TypeError, match='HttpMethod'):
        ApiAnnotationUtil.normalize_http_methods(['GET'])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# import_util
# ---------------------------------------------------------------------------


def test_import_util_find_project_root() -> None:
    root = ImportUtil.find_project_root()
    assert (root / 'requirements.txt').exists() or (root / 'pyproject.toml').exists()


def test_import_util_find_project_root_fallback() -> None:
    """When no marker files exist up the tree, fall back to utils parent."""
    current = MagicMock(name='current')
    current.parent = current
    current.joinpath.return_value.exists.return_value = False
    file_path = MagicMock(name='file_path')
    file_path.resolve.return_value = current
    fallback = MagicMock(name='fallback')
    fallback.resolve.return_value = fallback
    fallback.parent = fallback

    call_count = {'n': 0}

    def path_factory(*args, **kwargs):
        call_count['n'] += 1
        # first Path(__file__) → file_path; later Path(__file__) for fallback
        if call_count['n'] == 1:
            return file_path
        return fallback

    with patch('utils.import_util.Path', side_effect=path_factory):
        result = ImportUtil.find_project_root()
    assert result is fallback.parent


def test_import_util_is_valid_model() -> None:
    assert ImportUtil.is_valid_model(object(), Base) is False
    assert ImportUtil.is_valid_model(Base, Base) is False

    class FakePlain:
        __tablename__ = 't1'

    assert ImportUtil.is_valid_model(FakePlain, Base) is False

    # Subclass of Base without usable columns → False via sa_inspect exception / empty
    class Abstractish(Base):
        __abstract__ = True

    assert ImportUtil.is_valid_model(Abstractish, Base) is False

    class NoTablenameAttr(Base):
        __abstract__ = True

    # force hasattr __tablename__ True but None
    NoTablenameAttr.__tablename__ = None  # type: ignore[misc]
    assert ImportUtil.is_valid_model(NoTablenameAttr, Base) is False

    class InspectFail(Base):
        __tablename__ = 'inspect_fail_cov'
        __abstract__ = True

    InspectFail.__abstract__ = False  # type: ignore[misc]
    with patch('utils.import_util.sa_inspect', side_effect=RuntimeError('boom')):
        # still needs issubclass Base + tablename; columns path raises
        InspectFail.__tablename__ = 'inspect_fail_cov'
        assert ImportUtil.is_valid_model(InspectFail, Base) is False

    from sqlalchemy import Column, Integer

    class GoodModel(Base):
        __tablename__ = 'cov_good_model_unique'
        id = Column(Integer, primary_key=True)

    assert ImportUtil.is_valid_model(GoodModel, Base) is True


def test_import_util_find_models_with_mocks(tmp_path: Path) -> None:
    ImportUtil.find_models.cache_clear()

    class ModelA:
        __tablename__ = 'cov_model_a'

    class ModelSameTable:
        __tablename__ = 'cov_model_a'

    class NotModel:
        pass

    module_ok = SimpleNamespace(ModelA=ModelA, Dup=ModelA, Same=ModelSameTable, NotModel=NotModel)

    walk_root = str(tmp_path)
    walk_data = [
        (walk_root, ['__pycache__', 'models'], ['__init__.py', 'good.py']),
        (str(tmp_path / 'models'), [], ['entity.py', 'bad.py', 'err.py']),
    ]

    def fake_import(name: str):
        if name.endswith('good') or name.endswith('entity'):
            return module_ok
        if name.endswith('bad'):
            raise ImportError('cannot import name X')
        if name.endswith('err'):
            raise ImportError('other failure')
        raise RuntimeError('process fail')

    printed: list[str] = []

    def capture_print(*args, **kwargs):
        printed.append(' '.join(str(a) for a in args))

    with patch('builtins.print', side_effect=capture_print):
        with (
            patch.object(ImportUtil, 'find_project_root', return_value=tmp_path),
            patch('utils.import_util.os.walk', return_value=walk_data),
            patch('utils.import_util.importlib.import_module', side_effect=fake_import),
            patch.object(
                ImportUtil,
                'is_valid_model',
                side_effect=lambda obj, base: obj in (ModelA, ModelSameTable),
            ),
        ):
            models = ImportUtil.find_models(Base)

    assert ModelA in models
    assert ModelSameTable not in models  # duplicate table name skipped
    assert any('警告' in line for line in printed)
    ImportUtil.find_models.cache_clear()


def test_import_util_find_models_general_exception(tmp_path: Path) -> None:
    ImportUtil.find_models.cache_clear()
    walk_data = [(str(tmp_path), [], ['boom.py'])]
    printed: list[str] = []

    def capture_print(*args, **kwargs):
        printed.append(' '.join(str(a) for a in args))

    # Patch print before import_module so resolve_name for builtins.print works
    with patch('builtins.print', side_effect=capture_print):
        with (
            patch.object(ImportUtil, 'find_project_root', return_value=tmp_path),
            patch('utils.import_util.os.walk', return_value=walk_data),
            patch('utils.import_util.importlib.import_module', side_effect=ValueError('x')),
        ):
            models = ImportUtil.find_models(Base)

    assert models == []
    assert any('出错' in line for line in printed)
    ImportUtil.find_models.cache_clear()


# ---------------------------------------------------------------------------
# upload_util
# ---------------------------------------------------------------------------


def test_upload_util_random_and_exists(tmp_path: Path) -> None:
    code = UploadUtil.generate_random_number()
    assert len(code) == 3 and code.isdigit()
    f = tmp_path / 'a.txt'
    f.write_text('x', encoding='utf-8')
    assert UploadUtil.check_file_exists(str(f)) is True
    assert UploadUtil.check_file_exists(str(tmp_path / 'missing.txt')) is False


def test_upload_util_extension_timestamp_machine_random() -> None:
    good = MagicMock(spec=UploadFile)
    good.filename = 'photo.jpg'
    assert UploadUtil.check_file_extension(good) is True
    bad = MagicMock(spec=UploadFile)
    bad.filename = 'virus.exe'
    assert UploadUtil.check_file_extension(bad) is False

    machine = UploadConfig.UPLOAD_MACHINE
    ts = '20260101120000'
    # filename pattern: name_{timestamp}{machine}{random}.ext
    valid_name = f'file_{ts}{machine}001.jpg'
    assert UploadUtil.check_file_timestamp(valid_name) is True
    assert UploadUtil.check_file_timestamp('file_notatsA001.jpg') is False
    assert UploadUtil.check_file_machine(valid_name) is True
    assert UploadUtil.check_file_machine(f'file_{ts}B001.jpg') is False
    assert UploadUtil.check_file_random_code(valid_name) is True
    assert UploadUtil.check_file_random_code(f'file_{ts}{machine}000.jpg') is False


@pytest.mark.asyncio
async def test_upload_util_generate_and_delete(tmp_path: Path) -> None:
    target = tmp_path / 'blob.bin'
    target.write_bytes(b'abc123')
    chunks = [chunk async for chunk in UploadUtil.generate_file(str(target))]
    assert b''.join(chunks) == b'abc123'
    UploadUtil.delete_file(str(target))
    assert not target.exists()


# ---------------------------------------------------------------------------
# client_ip_util
# ---------------------------------------------------------------------------


def test_client_ip_hops_disabled() -> None:
    request = _make_request(client_host='10.0.0.1', headers={'X-Forwarded-For': '1.1.1.1'})
    with patch.object(AppConfig, 'app_trusted_proxy_hops', 0):
        assert ClientIPUtil.get_client_ip(request) == '10.0.0.1'


def test_client_ip_untrusted_proxy() -> None:
    request = _make_request(client_host='8.8.8.8', headers={'X-Forwarded-For': '1.1.1.1'})
    with (
        patch.object(AppConfig, 'app_trusted_proxy_hops', 1),
        patch.object(AppConfig, 'app_trusted_proxy_ips', '127.0.0.1'),
    ):
        assert ClientIPUtil.get_client_ip(request) == '8.8.8.8'


def test_client_ip_forwarded_chain_and_real_ip() -> None:
    with (
        patch.object(AppConfig, 'app_trusted_proxy_hops', 1),
        patch.object(AppConfig, 'app_trusted_proxy_ips', '*'),
    ):
        long_chain = _make_request(
            client_host='127.0.0.1',
            headers={'X-Forwarded-For': '1.1.1.1, 2.2.2.2, 3.3.3.3'},
        )
        # hops=1 → index -(1+1) = -2 → 2.2.2.2
        assert ClientIPUtil.get_client_ip(long_chain) == '2.2.2.2'

        short_chain = _make_request(
            client_host='127.0.0.1',
            headers={'X-Forwarded-For': '9.9.9.9'},
        )
        assert ClientIPUtil.get_client_ip(short_chain) == '9.9.9.9'

        real_only = _make_request(
            client_host='127.0.0.1',
            headers={'X-Real-IP': '5.5.5.5'},
        )
        assert ClientIPUtil.get_client_ip(real_only) == '5.5.5.5'

        no_headers = _make_request(client_host='127.0.0.1')
        assert ClientIPUtil.get_client_ip(no_headers) == '127.0.0.1'


def test_client_ip_unknown_when_no_client() -> None:
    request = _make_request(client_host=None)
    with patch.object(AppConfig, 'app_trusted_proxy_hops', 0):
        assert ClientIPUtil.get_client_ip(request) == 'unknown'


def test_client_ip_trusted_list_parsing() -> None:
    with patch.object(AppConfig, 'app_trusted_proxy_ips', ' 10.0.0.1 , ,10.0.0.2 '):
        assert ClientIPUtil._get_trusted_proxy_ips() == {'10.0.0.1', '10.0.0.2'}
    assert ClientIPUtil._should_trust_proxy_headers('10.0.0.1') is False


# ---------------------------------------------------------------------------
# dependency_util
# ---------------------------------------------------------------------------


def test_dependency_util_exclude_routes() -> None:
    pattern = re.compile(r'^/public/.*')
    token = RequestContext.set_current_exclude_patterns(
        [
            {
                'pattern': pattern,
                'methods': ['GET'],
                'ignore_paths': ['/public/health'],
            }
        ]
    )
    try:
        with patch.object(AppConfig, 'app_root_path', '/dev-api'):
            # ignored path
            DependencyUtil.check_exclude_routes(
                _make_request(path='/dev-api/public/health', method='GET')
            )
            # matching exclude → raise
            with pytest.raises(PermissionException):
                DependencyUtil.check_exclude_routes(
                    _make_request(path='/dev-api/public/info', method='GET')
                )
            # method not in list → ok
            DependencyUtil.check_exclude_routes(
                _make_request(path='/dev-api/public/info', method='POST')
            )
            # empty methods match all
            RequestContext.clear_all()
            token2 = RequestContext.set_current_exclude_patterns(
                [{'pattern': pattern, 'methods': [], 'ignore_paths': []}]
            )
            try:
                with pytest.raises(PermissionException):
                    DependencyUtil.check_exclude_routes(
                        _make_request(path='/dev-api/public/x', method='PUT'),
                        err_msg='blocked',
                    )
            finally:
                RequestContext.reset_current_exclude_patterns(token2)
    finally:
        RequestContext.clear_all()


def test_dependency_util_no_patterns_noop() -> None:
    RequestContext.clear_all()
    DependencyUtil.check_exclude_routes(_make_request(path='/any', method='GET'))


# ---------------------------------------------------------------------------
# string_util
# ---------------------------------------------------------------------------


def test_string_util_blank_empty_http() -> None:
    assert StringUtil.is_blank(None) is False
    assert StringUtil.is_blank('') is True
    assert StringUtil.is_blank('   ') is True
    assert StringUtil.is_blank(' a ') is False
    assert StringUtil.is_empty(None) is True  # type: ignore[arg-type]
    assert StringUtil.is_empty('') is True
    assert StringUtil.is_empty('x') is False
    assert StringUtil.is_not_empty('x') is True
    assert StringUtil.is_not_empty('') is False
    assert StringUtil.is_http('http://a') is True
    assert StringUtil.is_http('https://a') is True
    assert StringUtil.is_http('ftp://a') is False


def test_string_util_contains_equals_startswith() -> None:
    assert StringUtil.contains_ignore_case('HelloWorld', 'WORLD') is True
    assert StringUtil.contains_ignore_case('', 'a') is False
    assert StringUtil.contains_ignore_case('a', '') is False
    assert StringUtil.contains_any_ignore_case('AbC', ['x', 'ab']) is True
    assert StringUtil.contains_any_ignore_case('', ['a']) is False
    assert StringUtil.contains_any_ignore_case('a', []) is False
    assert StringUtil.equals_ignore_case('Ab', 'aB') is True
    assert StringUtil.equals_ignore_case('', 'a') is False
    assert StringUtil.equals_any_ignore_case('Ab', ['x', 'ab']) is True
    assert StringUtil.equals_any_ignore_case('', ['a']) is False
    assert StringUtil.startswith_case('hello', 'he') is True
    assert StringUtil.startswith_case('', 'he') is False
    assert StringUtil.startswith_any_case('hello', ['x', 'he']) is True
    assert StringUtil.startswith_any_case('', ['he']) is False


def test_string_util_camel_and_mapping() -> None:
    assert StringUtil.convert_to_camel_case('') == ''
    assert StringUtil.convert_to_camel_case('hello') == 'Hello'
    assert StringUtil.convert_to_camel_case('HELLO_WORLD') == 'HelloWorld'
    assert StringUtil.convert_to_camel_case('A__B') == 'AB'
    assert StringUtil.get_mapping_value_by_key_ignore_case({'UserName': 'u'}, 'username') == 'u'
    assert StringUtil.get_mapping_value_by_key_ignore_case({'a': '1'}, 'b') == ''


# ---------------------------------------------------------------------------
# cron_util
# ---------------------------------------------------------------------------


def test_cron_util_valid_range_and_sum_helpers() -> None:
    assert CronUtil._CronUtil__valid_range('1-5', 0, 59) is True
    assert CronUtil._CronUtil__valid_range('5-1', 0, 59) is False
    assert CronUtil._CronUtil__valid_range('x', 0, 59) is False
    assert CronUtil._CronUtil__valid_sum('0/10', 0, 58, 1, 59, 59) is True
    assert CronUtil._CronUtil__valid_sum('0/100', 0, 58, 1, 59, 59) is False
    assert CronUtil._CronUtil__valid_sum('bad', 0, 58, 1, 59, 59) is False


def test_cron_util_field_validators() -> None:
    assert CronUtil.validate_second_or_minute('*')
    assert CronUtil.validate_second_or_minute('0-30')
    assert CronUtil.validate_second_or_minute('0/5')
    assert CronUtil.validate_second_or_minute('0,15,30')
    assert not CronUtil.validate_second_or_minute('x')

    assert CronUtil.validate_hour('*')
    assert CronUtil.validate_hour('0-12')
    assert CronUtil.validate_hour('0/2')
    assert CronUtil.validate_hour('0,12,23')
    assert not CronUtil.validate_hour('99')

    assert CronUtil.validate_day('*')
    assert CronUtil.validate_day('?')
    assert CronUtil.validate_day('L')
    assert CronUtil.validate_day('1-10')
    assert CronUtil.validate_day('1/2')
    assert CronUtil.validate_day('15W')
    assert CronUtil.validate_day('1,15,31')
    assert not CronUtil.validate_day('xx')

    assert CronUtil.validate_month('*')
    assert CronUtil.validate_month('1-6')
    assert CronUtil.validate_month('1/2')
    assert CronUtil.validate_month('1,6,12')
    assert not CronUtil.validate_month('13')

    assert CronUtil.validate_week('*')
    assert CronUtil.validate_week('?')
    assert CronUtil.validate_week('1-5')
    assert CronUtil.validate_week('1#2')
    assert CronUtil.validate_week('5L')
    assert CronUtil.validate_week('1,3,5')
    assert not CronUtil.validate_week('8')

    year = str(datetime.now().year)
    assert CronUtil.validate_year('*')
    assert CronUtil.validate_year(f'{year}-2099')
    assert CronUtil.validate_year(f'{year}/1')
    assert CronUtil.validate_year('1#2')
    assert CronUtil.validate_year('5L')
    assert CronUtil.validate_year(year)
    assert CronUtil.validate_year(f'{year},{int(year) + 1}')
    assert not CronUtil.validate_year('1999')


def test_cron_util_expression() -> None:
    assert CronUtil.validate_cron_expression('0 0 12 * * ?') is True
    year = str(datetime.now().year)
    assert CronUtil.validate_cron_expression(f'0 0 12 * * ? {year}') is True
    assert CronUtil.validate_cron_expression('too short') is False
    assert CronUtil.validate_cron_expression('x 0 12 * * ?') is False


# ---------------------------------------------------------------------------
# time_format_util
# ---------------------------------------------------------------------------


def test_object_and_list_format_datetime() -> None:
    obj = SimpleNamespace(created=datetime(2026, 1, 2, 3, 4, 5), name='a')
    object_format_datetime(obj)
    assert obj.created == '2026-01-02 03:04:05'
    lst = [SimpleNamespace(ts=datetime(2026, 2, 3, 4, 5, 6))]
    list_format_datetime(lst)
    assert lst[0].ts == '2026-02-03 04:05:06'


def test_format_datetime_dict_list() -> None:
    data = [
        {
            'a': datetime(2026, 1, 1, 0, 0, 0),
            'nested': {'b': datetime(2026, 1, 2, 0, 0, 0)},
            'n': 1,
        }
    ]
    out = format_datetime_dict_list(data)
    assert out[0]['a'] == '2026-01-01 00:00:00'
    assert out[0]['nested']['b'] == '2026-01-02 00:00:00'
    assert out[0]['n'] == 1


def test_time_format_util_class_methods() -> None:
    assert TimeFormatUtil.format_time(datetime(2026, 3, 4, 5, 6, 7)) == '2026-03-04 05:06:07'
    assert TimeFormatUtil.format_time('2026-03-04 05:06:07') == '2026-03-04 05:06:07'
    assert TimeFormatUtil.format_time('not-a-date') == 'not-a-date'
    assert TimeFormatUtil.parse_date('2026-03-04') == date(2026, 3, 4)
    assert TimeFormatUtil.parse_date('bad') == 'bad'

    nested = {
        't': datetime(2026, 1, 1, 1, 1, 1),
        's': '2026-01-01 02:02:02',
        'd': {'inner': datetime(2026, 1, 1, 3, 3, 3)},
        'l': [datetime(2026, 1, 1, 4, 4, 4), {'x': '2026-01-01 05:05:05'}, [datetime(2026, 1, 1, 6, 6, 6)], 9],
        'n': 3,
    }
    formatted = TimeFormatUtil.format_time_dict(nested)
    assert formatted['t'] == '2026-01-01 01:01:01'
    assert formatted['d']['inner'] == '2026-01-01 03:03:03'
    assert formatted['l'][0] == '2026-01-01 04:04:04'
    assert formatted['l'][1]['x'] == '2026-01-01 05:05:05'
    assert formatted['l'][2][0] == '2026-01-01 06:06:06'
    assert formatted['l'][3] == 9
    assert formatted['n'] == 3


# ---------------------------------------------------------------------------
# page_util
# ---------------------------------------------------------------------------


def test_page_util_get_page_obj() -> None:
    data = list(range(10))
    page = PageUtil.get_page_obj(data, 2, 3)
    assert page.rows == [3, 4, 5]
    assert page.total == 10
    assert page.has_next is True or page.hasNext is True
    page2 = get_page_obj(data, 4, 3)
    assert page2.rows == [9]
    assert page2.has_next is False or page2.hasNext is False


@pytest.mark.asyncio
async def test_page_util_paginate_with_and_without_page() -> None:
    class FakeRow(tuple):
        pass

    single = FakeRow(({'user_name': 'a'},))
    multi = FakeRow(({'user_name': 'b'}, {'extra': 1}))
    empty = FakeRow(())

    count_result = MagicMock()
    count_result.scalar.return_value = 5
    page_result = [single, multi]
    no_page_result = [single, multi, empty]

    query = MagicMock()
    query.subquery.return_value = 'subq'
    query.offset.return_value = query
    query.limit.return_value = query

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[count_result, page_result])

    count_select = MagicMock()
    count_select.select_from.return_value = count_select

    with (
        patch('utils.page_util.select', return_value=count_select),
        patch('utils.page_util.func.count', return_value='cnt'),
        patch('utils.page_util.CamelCaseUtil.transform_result', side_effect=lambda x: x),
    ):
        page = await PageUtil.paginate(db, query, 1, 2, is_page=True)
    assert page.total == 5
    assert len(page.rows) == 2
    assert page.rows[0] == {'user_name': 'a'}
    assert page.rows[1] == multi

    db2 = AsyncMock()
    db2.execute = AsyncMock(return_value=no_page_result)
    with patch('utils.page_util.CamelCaseUtil.transform_result', side_effect=lambda x: x):
        rows = await PageUtil.paginate(db2, query, 1, 10, is_page=False)
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# excel_util
# ---------------------------------------------------------------------------


def test_excel_util_export_and_template() -> None:
    mapping = {'name': '姓名', 'age': '年龄'}
    data = [{'name': '张三', 'age': 18}]
    binary = ExcelUtil.export_list2excel(data, mapping)
    assert isinstance(binary, (bytes, bytearray))
    assert len(binary) > 0

    template = ExcelUtil.get_excel_template(
        header_list=['姓名', '性别', '状态'],
        selector_header_list=['性别', '状态'],
        option_list=[{'性别': ['男', '女']}, {'状态': ['启用', '停用']}],
    )
    assert isinstance(template, (bytes, bytearray))
    assert len(template) > 0


# ---------------------------------------------------------------------------
# response_util
# ---------------------------------------------------------------------------


def _assert_json_body(resp, *, code: int, success: bool | None = None) -> dict:
    import json

    body = json.loads(resp.body.decode())
    assert body['code'] == code
    if success is not None:
        assert body['success'] is success
    assert 'time' in body
    return body


def test_response_util_success_variants() -> None:
    bare = ResponseUtil.success()
    body = _assert_json_body(bare, code=HttpStatusConstant.SUCCESS, success=True)
    assert body['msg'] == '操作成功'

    model = _SampleModel(user_name='root')
    full = ResponseUtil.success(
        msg='ok',
        data={'a': 1},
        rows=[1],
        dict_content={'extra': True},
        model_content=model,
        headers={'X-T': '1'},
        media_type='application/json',
        background=BackgroundTask(lambda: None),
    )
    body = _assert_json_body(full, code=HttpStatusConstant.SUCCESS, success=True)
    assert body['data'] == {'a': 1}
    assert body['rows'] == [1]
    assert body['extra'] is True
    assert 'userName' in body or 'user_name' in body


def test_response_util_failure_unauthorized_forbidden_error() -> None:
    model = _SampleModel()
    kwargs = dict(
        data=1,
        rows=[2],
        dict_content={'k': 'v'},
        model_content=model,
        headers={'H': '1'},
        media_type='application/json',
        background=BackgroundTask(lambda: None),
    )
    _assert_json_body(ResponseUtil.failure(**kwargs), code=HttpStatusConstant.WARN, success=False)
    _assert_json_body(
        ResponseUtil.unauthorized(**kwargs), code=HttpStatusConstant.UNAUTHORIZED, success=False
    )
    _assert_json_body(
        ResponseUtil.forbidden(**kwargs), code=HttpStatusConstant.FORBIDDEN, success=False
    )
    _assert_json_body(ResponseUtil.error(**kwargs), code=HttpStatusConstant.ERROR, success=False)


def test_response_util_too_many_and_streaming() -> None:
    resp = ResponseUtil.too_many_requests(
        data='x',
        rows=[],
        dict_content={'a': 1},
        model_content=_SampleModel(),
        headers={'X-R': '1'},
        media_type='application/json',
        background=BackgroundTask(lambda: None),
    )
    assert resp.status_code == 429
    _assert_json_body(resp, code=HttpStatusConstant.TOO_MANY_REQUESTS, success=False)

    async def gen():
        yield b'chunk'

    stream = ResponseUtil.streaming(
        data=gen(),
        headers={'X-S': '1'},
        media_type='text/plain',
        background=BackgroundTask(lambda: None),
    )
    assert stream.status_code == 200


def test_response_util_bare_branches() -> None:
    assert ResponseUtil.failure().status_code == 200
    assert ResponseUtil.unauthorized().status_code == 200
    assert ResponseUtil.forbidden().status_code == 200
    assert ResponseUtil.error().status_code == 200
    assert ResponseUtil.too_many_requests().status_code == 429
    assert ResponseUtil.streaming(data=iter([b'x'])).status_code == 200
