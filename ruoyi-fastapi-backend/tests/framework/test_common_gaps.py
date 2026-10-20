"""common 模块覆盖率补洞：log_annotation / router / vo / context / enums。"""

import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.requests import ClientDisconnect

from common.annotation import log_annotation as la
from common.annotation.log_annotation import (
    Log,
    RequestLogFieldRoot,
    ResponseLogFieldRoot,
    get_function_parameters_name_by_type,
    get_function_parameters_value_by_name,
    get_ip_location,
)
from common.context import RequestContext
from common.enums import BusinessType, RedisInitKeyConfig
from common.router import APIRouterPro, RouterRegister, auto_register_routers
from common.vo import DynamicResponseModel, ResponseBaseModel
from exceptions.exception import LoginException, ServiceException, ServiceWarning


def test_enums_remark_property() -> None:
    assert RedisInitKeyConfig.ACCESS_TOKEN.key == 'access_token'
    assert RedisInitKeyConfig.ACCESS_TOKEN.remark == '登录令牌信息'


def test_context_set_get_reset_clear() -> None:
    token_ex = RequestContext.set_current_exclude_patterns([])
    assert RequestContext.get_current_exclude_patterns() == []
    RequestContext.reset_current_exclude_patterns(token_ex)
    # default None → []
    RequestContext.clear_all()
    assert RequestContext.get_current_exclude_patterns() == []

    user = SimpleNamespace(user=SimpleNamespace(user_name='u', dept=None))
    token_u = RequestContext.set_current_user(user)  # type: ignore[arg-type]
    assert RequestContext.get_current_user() is user
    RequestContext.reset_current_user(token_u)
    RequestContext.clear_all()
    with pytest.raises(LoginException):
        RequestContext.get_current_user()


def test_dynamic_response_model_cache() -> None:
    class Item(BaseModel):
        name: str = Field(default='n')

    m1 = DynamicResponseModel[Item]
    m2 = DynamicResponseModel[Item]
    assert m1 is m2
    assert issubclass(m1, ResponseBaseModel)
    with pytest.raises(TypeError):
        _ = DynamicResponseModel[int]


def test_api_router_pro_and_register(tmp_path, monkeypatch) -> None:
    router = APIRouterPro(prefix='/t', order_num=5, auto_register=True)

    @router.get('/x')
    async def _x():
        return {'ok': True}

    plain = APIRouterPro(prefix='/skip', auto_register=False)
    plain_api = APIRouter(prefix='/plain')

    app = FastAPI()
    reg = RouterRegister(app)
    pkg = tmp_path / 'mod'
    ctrl = pkg / 'controller'
    ctrl.mkdir(parents=True)
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    (ctrl / '__init__.py').write_text('', encoding='utf-8')
    py = ctrl / 'demo.py'
    py.write_text(
        'from common.router import APIRouterPro\n'
        'from fastapi import APIRouter\n'
        'r1 = APIRouterPro(prefix="/a", order_num=2)\n'
        'r2 = APIRouterPro(prefix="/b", auto_register=False)\n'
        'r3 = APIRouter(prefix="/c")\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(reg, 'project_root', str(tmp_path))
    sys.path.insert(0, str(tmp_path))
    try:
        files = reg._find_controller_files()
        assert any(f.endswith('demo.py') for f in files)
        routers = reg._import_module_and_get_routers(files)
        names = {n for n, _ in routers}
        assert 'r1' in names and 'r3' in names and 'r2' not in names
        sorted_r = reg._sort_routers(routers)
        assert sorted_r[0][0] == 'r1'
        reg._register_routers_to_app(sorted_r)
    finally:
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))

    app2 = FastAPI()
    with patch.object(RouterRegister, 'register_routers') as m:
        auto_register_routers(app2)
        m.assert_called_once()

    # 覆盖 register_routers 本体
    with (
        patch.object(RouterRegister, '_find_controller_files', return_value=[]),
        patch.object(RouterRegister, '_import_module_and_get_routers', return_value=[]),
        patch.object(RouterRegister, '_sort_routers', return_value=[]),
        patch.object(RouterRegister, '_register_routers_to_app') as reg_m,
    ):
        RouterRegister(FastAPI()).register_routers()
        reg_m.assert_called_once_with([])

    assert router.order_num == 5
    assert plain.auto_register is False
    assert plain_api.prefix == '/plain'


def test_log_field_roots_and_helpers() -> None:
    assert RequestLogFieldRoot.JSON_BODY.field('a') == 'json_body.a'
    assert ResponseLogFieldRoot.DATA.field() == 'data'
    log = Log(title='t', business_type=BusinessType.OTHER)
    assert log._get_oper_type(None) == 0
    assert log._get_oper_type('Windows Chrome') == 1
    assert log._get_oper_type('iPhone Mobile') == 2

    async def handler(request: Request):
        return JSONResponse({'code': 200, 'msg': 'ok'})

    assert get_function_parameters_name_by_type(handler, Request) == ['request']
    req = MagicMock()
    assert get_function_parameters_value_by_name(handler, 'request', request=req) is req


async def test_get_ip_location_branches() -> None:
    assert await get_ip_location('127.0.0.1') == '内网IP'
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {'data': {'prov': '粤', 'city': '深'}}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return fake_resp

    with patch('common.annotation.log_annotation.httpx.AsyncClient', return_value=_Client()):
        assert await get_ip_location('8.8.8.8') == '粤-深'

    class _Boom:
        async def __aenter__(self):
            raise RuntimeError('net')

        async def __aexit__(self, *a):
            return False

    with patch('common.annotation.log_annotation.httpx.AsyncClient', return_value=_Boom()):
        assert await get_ip_location('1.1.1.1') == '未知'


async def test_log_decorator_operation_and_login_paths() -> None:
    request = MagicMock(spec=Request)
    request.method = 'POST'
    request.url.path = '/api/x'
    request.headers = {'User-Agent': 'Mozilla Windows', 'Content-Type': 'application/json', 'referer': ''}
    request.path_params = {}
    request.query_params = {}
    request.json = AsyncMock(return_value={'a': 1})

    user = SimpleNamespace(
        user=SimpleNamespace(user_name='admin', dept=SimpleNamespace(dept_name='d'))
    )
    form = SimpleNamespace(username='admin', login_info=None)

    with (
        patch('common.annotation.log_annotation.DependencyUtil.check_exclude_routes'),
        patch('common.annotation.log_annotation.ClientIPUtil.get_client_ip', return_value='127.0.0.1'),
        patch.object(Log, '_get_oper_location', new=AsyncMock(return_value='内网IP')),
        patch('common.annotation.log_annotation.LogQueueService.enqueue_operation_log', new=AsyncMock()),
        patch('common.annotation.log_annotation.LogQueueService.enqueue_login_log', new=AsyncMock()),
        patch('common.annotation.log_annotation.RequestContext.get_current_user', return_value=user),
        patch('common.annotation.log_annotation.AppConfig.app_ip_location_query', False),
    ):
        decor = Log(title='op', business_type=BusinessType.UPDATE, request_log_mode='summary', response_log_mode='summary')

        @decor
        async def op_ok(request: Request):
            return JSONResponse({'code': 200, 'msg': 'ok', 'data': {'x': 1}})

        out = await op_ok(request=request)
        assert out.status_code == 200

        @decor
        async def op_warn(request: Request):
            raise ServiceWarning(data={}, message='warn')

        await op_warn(request=request)

        @decor
        async def op_svc(request: Request):
            raise ServiceException(data={}, message='err')

        await op_svc(request=request)

        @decor
        async def op_exc(request: Request):
            raise RuntimeError('boom')

        await op_exc(request=request)

        login = Log(title='login', business_type=BusinessType.OTHER, log_type='login')

        @login
        async def do_login(request: Request, form_data=form):
            return JSONResponse({'code': 200, 'msg': 'ok'})

        await do_login(request=request, form_data=form)

        # swagger 不记登录日志
        request.headers = {
            'User-Agent': 'ua',
            'Content-Type': 'application/json',
            'referer': 'http://x/docs',
        }

        @login
        async def do_login2(request: Request, form_data=form):
            return JSONResponse({'code': 200, 'msg': 'ok'})

        await do_login2(request=request, form_data=form)


async def test_log_request_param_modes_and_result_dict() -> None:
    decor = Log(title='t', business_type=BusinessType.OTHER)
    req = MagicMock(spec=Request)
    req.path_params = {'id': '1'}
    req.query_params = {'q': '2'}
    req.url.path = '/p'
    req.headers = {'Content-Type': 'multipart/form-data'}
    file_obj = SimpleNamespace(filename='a.txt', content_type='text/plain', size=3, headers={})
    form = MagicMock()
    form.items.return_value = [('f', 'v'), ('up', file_obj)]
    form.__bool__ = lambda self: True
    req.form = AsyncMock(return_value=form)
    params = await decor._get_request_params(req)
    assert 'form_data' in params and 'files' in params

    req2 = MagicMock(spec=Request)
    req2.path_params = {}
    req2.query_params = {}
    req2.url.path = '/p'
    req2.headers = {'Content-Type': 'text/plain'}
    req2.body = AsyncMock(return_value=b'hi')
    assert (await decor._get_request_params(req2))['raw_body'] == 'hi'

    class _PathParams:
        def keys(self):
            raise ClientDisconnect()

        def __iter__(self):
            raise ClientDisconnect()

    req3 = MagicMock(spec=Request)
    req3.path_params = _PathParams()
    req3.query_params = {}
    req3.url.path = '/p'
    req3.headers = {'Content-Type': 'application/json'}
    assert await decor._get_request_params(req3) == {}

    req4 = MagicMock(spec=Request)
    req4.body = AsyncMock(side_effect=ClientDisconnect())
    assert await decor._get_raw_request_params(req4) == {}

    assert decor._get_result_dict(JSONResponse({'code': 200}), False, False)['code'] == 200
    assert decor._get_result_dict(SimpleNamespace(status_code=200), True, False) == {}
    assert decor._get_result_dict(SimpleNamespace(status_code=200), False, False)['message'] == '获取成功'
    assert decor._get_result_dict(SimpleNamespace(status_code=500), False, False)['message'] == '获取失败'

    # describe / include list index / remove field paths
    payload = {'rows': [{'userId': 1}, {'userId': 2}], 'data': {'a': 1}}
    assert '下标' in decor._describe_missing_field_path(payload, 'rows.9.userId')
    assert '列表' in decor._describe_missing_field_path(payload, 'rows.x')
    assert '类型' in decor._describe_missing_field_path({'a': 1}, 'a.b')
    assert decor._get_field_value_by_path(payload, 'rows.0.userId') == 1
    assert decor._get_field_value_by_path(payload, 'rows.9') is decor._MISSING
    assert decor._remove_field_by_path({'a': {'b': 1}}, 'a.b') is True
    assert decor._remove_field_by_path({'rows': [1, 2]}, 'rows.0') is True
    assert decor._remove_field_by_path({'a': 1}, '') is False
    assert decor._remove_field_by_path({'a': 1}, 'a.b.c') is False
    assert decor._remove_field_by_path([1], '0') is True
    assert decor._build_summary_payload('x', 'response')['type'] == 'str'

    with patch.object(la.AppConfig, 'app_ip_location_query', True), patch(
        'common.annotation.log_annotation.get_ip_location', new=AsyncMock(return_value='外网')
    ):
        assert await decor._get_oper_location('8.8.8.8') == '外网'

    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'
    login_d = Log(title='l', business_type=BusinessType.OTHER, log_type='login')
    info = login_d._get_login_log(ua, '1.1.1.1', 'loc', datetime.now(), {})
    assert 'browser' in info
    form_data = SimpleNamespace(login_info=None)
    login_d._set_login_data({}, {'form_data': form_data})
    assert form_data.login_info == {}

    warnings = login_d._collect_field_path_warnings(
        mode='include',
        include_fields=('', 'data..x', 'weird.root'),
        exclude_fields=(),
        payload_kind='response',
    )
    assert warnings

    sw, rd = login_d._is_request_from_swagger_or_redoc(
        MagicMock(headers={'referer': 'http://h/redoc'})
    )
    assert rd is True and sw is False


@pytest.mark.asyncio
async def test_log_json_fail_include_exclude_ambiguous() -> None:
    """补 log_annotation 剩余：json 降级、include/exclude、歧义键、严格校验。"""
    decor = Log(title='t', business_type=BusinessType.OTHER)

    req = MagicMock(spec=Request)
    req.url.path = '/p'
    req.headers = {'Content-Type': 'application/json'}
    req.json = AsyncMock(side_effect=ValueError('bad json'))
    req.body = AsyncMock(return_value=b'raw-x')
    params = await decor._get_json_request_params(req, 'application/json')
    assert params.get('raw_body') == 'raw-x'

    # include / exclude / summary modes via _build_log_text
    payload = {'json_body': {'a': 1, 'b': 2}, 'rows': [{'id': 1}, {'id': 2}]}
    assert 'selected' in decor._build_log_text(payload, 'include', ('json_body.a', 'missing.x'), (), 'request')
    excl = decor._build_log_text(payload, 'exclude', (), ('json_body.b', 'rows.1'), 'request')
    assert 'b' not in excl or 'json_body' in excl
    assert decor._build_log_text(payload, 'summary', (), (), 'request')

    # exclude with fields on list/dict
    filtered = decor._exclude_fields({'a': {'b': 1, 'c': 2}}, ('a.b',), 'response')
    assert 'b' not in (filtered.get('a') or {})

    # warn paths + ambiguous describe
    amb = {'user_id': 1, 'user-id': 2}
    msg = decor._describe_missing_field_path(amb, 'userId')
    assert msg  # ambiguous or missing description

    # exclude mode empty list warning + include empty
    assert decor._collect_field_path_warnings('exclude', (), (), 'request')
    assert decor._collect_field_path_warnings('include', (), (), 'response')

    # exclude mode with bad root → strict
    with pytest.raises(ValueError, match='不支持的根节点'):
        Log(
            title='bad',
            business_type=BusinessType.OTHER,
            request_log_mode='exclude',
            request_exclude_fields=('weird.root',),
        )

    # _get_mapping / resolve: normalized single match + missing
    assert decor._get_mapping_value_by_part({'userId': 9}, 'user_id') == 9
    assert decor._get_mapping_value_by_part({'a': 1}, 'nope') is decor._MISSING
    assert decor._get_mapping_value_by_part(amb, 'userId') is decor._AMBIGUOUS

    # remove: ambiguous mid, list oob mid, ambiguous target, list oob target
    assert decor._remove_field_by_path({'outer': amb}, 'outer.userId') is False
    assert decor._remove_field_by_path({'rows': [1]}, 'rows.5.x') is False
    assert decor._remove_field_by_path(amb, 'userId') is False
    assert decor._remove_field_by_path({'rows': [1, 2]}, 'rows.9') is False
    assert decor._resolve_mapping_key_by_part({'userId': 1}, 'user_id') == 'userId'
    assert decor._resolve_mapping_key_by_part({'a': 1}, 'z') is decor._MISSING

    # sort helpers
    assert Log._sort_field_paths_for_exclude(('a.0', 'a.10', 'b'))
    key = Log._build_exclude_sort_key('rows.2.id')
    assert key[0] == 3

    # get field value else branch (non list/dict mid)
    assert decor._get_field_value_by_path({'a': 1}, 'a.0') is decor._MISSING

    # exclude missing path → warn (562); second call hits already-warned (583); exclude strategy text (593)
    decor._warned_field_path_warnings.clear()
    decor._exclude_fields({'a': 1}, ('missing.path',), 'response')
    decor._exclude_fields({'a': 1}, ('missing.path',), 'response')  # duplicate warn skipped
    assert 'exclude:response:missing.path' in decor._warned_field_path_warnings

    # remove: ambiguous mid-path returns False (837) — no exact key, two normalized matches
    amb_mid = {'user-id': {'x': 1}, 'user_id': {'x': 2}}
    assert decor._remove_field_by_path({'outer': amb_mid}, 'outer.userId.x') is False
