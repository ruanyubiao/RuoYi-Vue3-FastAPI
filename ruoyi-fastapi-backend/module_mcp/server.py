"""
后端 MCP 服务（Streamable HTTP，默认挂在 ``/mcp``）。

设计要点：
- 工具不直接调 service，而是在进程内（httpx.ASGITransport）回调本应用已有的 GET 接口，
  因此 **登录校验、接口权限、参数校验、数据权限** 与前端走的是同一条链路，不会绕过。
- 认证：``/mcp`` 在传输层要求有效登录 Bearer（HTTP 401）。工具再把该 Token 转发给已有接口。
- 只读：只暴露 GET 查询；不提供打开设备、发送遥控、执行序列、改配置等有硬件/数据副作用的能力。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Annotated, Any, Literal

import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from config.env import AppConfig, McpConfig
from exceptions.exception import ServiceException
from module_admin.service.health_service import HealthService
from module_mcp.auth import McpBearerMiddleware, authorization_from_headers
from module_payload.protocol.protocol_catalog import bus_family_names
from utils.log_util import logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastapi import FastAPI

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_INTERNAL_BASE_URL = 'http://pgt-mcp.internal'
_TIMEOUT_SECONDS = 30.0
_HTTP_OK = 200
# 通用查询工具允许访问的 GET：/payload/ 为前缀，其余必须整段相等
_PAYLOAD_GET_PREFIX = '/payload/'
_EXACT_GET_PATHS = frozenset({'/getInfo', '/health'})
_PATH_SAFE = re.compile(r'^/[A-Za-z0-9_\-./{}]*$')
_FAMILY_NAMES = bus_family_names()
FamilyName = Literal.__getitem__(_FAMILY_NAMES if len(_FAMILY_NAMES) != 1 else _FAMILY_NAMES[0])
_FAMILY = Annotated[FamilyName, Field(description='已登记的总线族')]
_INTERNAL_ERROR = '内部错误'
_SAFE_TOOL_ERRORS = (ValueError, ServiceException)
_LIMIT_500 = Annotated[int, Field(ge=1, le=500, description='返回条数上限')]
_PAGE_NUM = Annotated[int, Field(ge=1, description='页码，从 1 开始')]
_PAGE_SIZE = Annotated[int, Field(ge=1, le=100, description='每页条数')]
_TRUNCATE_HINT = '结果已按条目截断。请减小 limit 或 page_size，或改用更具体的查询后再调用。'
_OBJECT_HINT = '结果过大，已省略正文，避免返回半截 JSON。请缩小查询范围，例如指定单条指令、单个遥测 type，或减小 limit。'


class McpToolError(ToolError):
    """工具调用失败（会以 isError 结果返回给 MCP 客户端）。"""


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in (value or '').split(',') if item.strip()]


def _auth_header(headers: Mapping[str, str] | None) -> str | None:
    return authorization_from_headers(headers)


def _clean_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if value is None:
            continue
        cleaned[key] = str(value).lower() if isinstance(value, bool) else value
    return cleaned


_EXCEPTION_GROUP_TYPES: tuple[type, ...] = tuple(
    group
    for name in ('BaseExceptionGroup',)
    if (group := getattr(__import__('builtins'), name, None)) is not None
)


def _exception_leaves(exc: BaseException) -> list[BaseException]:
    """展开 ExceptionGroup，得到最内层异常。"""
    nested = getattr(exc, 'exceptions', None)
    if isinstance(nested, tuple) and type(exc).__name__.endswith('ExceptionGroup'):
        leaves: list[BaseException] = []
        for item in nested:
            leaves.extend(_exception_leaves(item))
        return leaves
    return [exc]


def _tool_error_message(exc: BaseException) -> str:
    """业务异常返回原文；其他异常只返回通用提示。"""
    leaves = _exception_leaves(exc)
    if leaves and all(isinstance(item, _SAFE_TOOL_ERRORS) for item in leaves):
        return '; '.join(str(item).strip() or type(item).__name__ for item in leaves)
    return _INTERNAL_ERROR


class BackendApiProxy:
    """在进程内调用本应用接口，复用全部中间件与鉴权依赖。"""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def get(self, path: str, params: Mapping[str, Any] | None, headers: Mapping[str, str] | None) -> Any:
        auth = _auth_header(headers)
        if not auth:
            raise McpToolError('未提供认证信息：请在 MCP 客户端配置 Authorization: Bearer <登录token>')
        transport = httpx.ASGITransport(app=self._app, client=('127.0.0.1', 0))
        try:
            async with httpx.AsyncClient(
                transport=transport, base_url=_INTERNAL_BASE_URL, timeout=_TIMEOUT_SECONDS
            ) as client:
                response = await client.get(path, params=_clean_params(params), headers={'Authorization': auth})
        except McpToolError:
            raise
        except _EXCEPTION_GROUP_TYPES as exc:
            raise McpToolError(_tool_error_message(exc)) from exc
        except Exception as exc:
            raise McpToolError(_tool_error_message(exc)) from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise McpToolError(f'GET {path} 返回非 JSON（HTTP {response.status_code}）') from exc
        if response.status_code != _HTTP_OK:
            msg = body.get('msg') if isinstance(body, dict) else None
            raise McpToolError(f'GET {path} 失败 HTTP {response.status_code}: {msg or body}')
        if isinstance(body, dict) and 'code' in body:
            if body.get('code') != _HTTP_OK:
                raise McpToolError(f'GET {path} 业务失败 code={body.get("code")}: {body.get("msg")}')
            payload = {k: v for k, v in body.items() if k not in {'code', 'msg', 'success', 'time'}}
            return payload.get('data', payload) if set(payload) <= {'data'} else payload
        return body


def _json_len(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def _truncate(value: Any) -> Any:
    """超大结果按条目截断。对象放不进限额时返回说明，不返回半截 JSON。"""
    limit = McpConfig.mcp_max_result_chars
    if limit <= 0 or _json_len(value) <= limit:
        return value
    if isinstance(value, dict) and isinstance(value.get('items'), list):
        items: list[Any] = value['items']
        total = value.get('total', len(items))
        kept: list[Any] = []
        for item in items:
            candidate = {
                'truncated': True,
                'total': total,
                'returned': len(kept) + 1,
                'items': [*kept, item],
                'hint': _TRUNCATE_HINT,
            }
            if _json_len(candidate) > limit:
                break
            kept.append(item)
        return {
            'truncated': True,
            'total': total,
            'returned': len(kept),
            'items': kept,
            'hint': _TRUNCATE_HINT,
        }
    return {'truncated': True, 'totalChars': _json_len(value), 'hint': _OBJECT_HINT}


def present_tool_result(value: Any) -> Any:
    """列表包成一个对象，避免被拆成多块文本，空列表也不会变成 0 块。"""
    if isinstance(value, list):
        value = {'items': value, 'total': len(value)}
    return _truncate(value)


def telecontrol_index(data: Any) -> dict[str, Any]:
    """遥控配置只留分类页和指令 id、名称，不带参数定义。"""
    if not isinstance(data, dict):
        return {'pages': [], 'orders': []}
    raw_orders = data.get('order') if isinstance(data.get('order'), dict) else {}
    orders: list[dict[str, str]] = []
    for key, order in raw_orders.items():
        if isinstance(order, dict):
            orders.append({'id': str(order.get('id') or key), 'name': str(order.get('name') or '')})
        else:
            orders.append({'id': str(key), 'name': ''})
    pages: list[dict[str, Any]] = []
    for page in data.get('page') or []:
        if not isinstance(page, dict):
            continue
        order_ids = [str(item) for item in (page.get('orderList') or [])]
        pages.append({'id': page.get('id'), 'name': str(page.get('name') or ''), 'orderIds': order_ids})
    listed = {order_id for page in pages for order_id in page['orderIds']}
    if any(order['id'] not in listed for order in orders):
        pages.append({'id': None, 'name': '', 'orderIds': [order['id'] for order in orders if order['id'] not in listed]})
    return {
        'family': data.get('family'),
        'datetime': data.get('datetime') or '',
        'pages': pages,
        'orders': orders,
    }


def strip_config_paths(value: Any) -> Any:
    """配置文件列表去掉服务器绝对路径，只保留文件名等元数据。"""
    if not isinstance(value, list):
        return value
    cleaned: list[Any] = []
    for row in value:
        if isinstance(row, dict):
            cleaned.append({key: item for key, item in row.items() if key != 'path'})
        else:
            cleaned.append(row)
    return cleaned


def build_mcp_server(app: FastAPI) -> MCPServer:  # noqa: PLR0915
    """创建 MCP 服务并注册只读工具。"""
    proxy = BackendApiProxy(app)
    server = MCPServer(
        name=f'{AppConfig.app_name} MCP',
        version=AppConfig.app_version,
        instructions=(
            '激光终端地检系统后端（RuoYi-FastAPI）的只读查询工具。'
            'family 取值通常为 biu / xl / yj216；遥测 type 为 HEX 数据类型（如 FF）。'
            '先用 get_server_health 看服务是否可用，再用 telecontrol_config 拿指令目录，'
            '用 telecontrol_order 查单条指令定义。'
        ),
    )

    async def call(ctx: Context, path: str, **params: Any) -> Any:
        return present_tool_result(await proxy.get(path, params, ctx.headers))

    @server.tool(annotations=_READ_ONLY)
    async def get_server_health(ctx: Context) -> Any:
        """数据库、Redis 和采集进程是否可用。某一项失败时仍返回各项状态。"""
        if ctx is None:
            raise McpToolError('缺少调用上下文')
        payload, _status = await HealthService.check(getattr(app.state, 'redis', None))
        return present_tool_result(payload)

    # ---- 平台 / 设备 ----
    @server.tool(annotations=_READ_ONLY)
    async def payload_version(ctx: Context) -> Any:
        """地检平台服务版本信息。"""
        return await call(ctx, '/payload/device/version')

    @server.tool(annotations=_READ_ONLY)
    async def current_user(ctx: Context) -> Any:
        """当前 token 对应的用户、角色与权限（用于确认 MCP 认证是否生效）。"""
        return await call(ctx, '/getInfo')

    @server.tool(annotations=_READ_ONLY)
    async def list_device_sessions(ctx: Context) -> Any:
        """列出已打开的设备会话（串口 / CAN / 网络）。"""
        return await call(ctx, '/payload/device/sessions')

    @server.tool(annotations=_READ_ONLY)
    async def device_status(ctx: Context, device_id: str) -> Any:
        """查询单个设备状态。device_id 来自 list_device_sessions。"""
        return await call(ctx, '/payload/device/status', deviceId=device_id)

    @server.tool(annotations=_READ_ONLY)
    async def device_snapshot(ctx: Context, parts: str = '') -> Any:
        """设备只读数据批量快照，parts 为逗号分隔块名（如 serialOpened,parsers,assemblers），空为默认全部。"""
        return await call(ctx, '/payload/device/snapshot', parts=parts)

    @server.tool(annotations=_READ_ONLY)
    async def device_io_log(ctx: Context, device_id: str, since_seq: int = 0, limit: _LIMIT_500 = 200) -> Any:
        """查询设备原始收发日志（预览）。"""
        return await call(ctx, '/payload/device/io-log', deviceId=device_id, sinceSeq=since_seq, limit=limit)

    # ---- 遥控 ----
    @server.tool(annotations=_READ_ONLY)
    async def telecontrol_config(ctx: Context, family: _FAMILY) -> Any:
        """获取某总线族的遥控指令目录（分类页、指令 id 和名称）。明细用 telecontrol_order。"""
        raw = await proxy.get('/payload/telecontrol/config', {'family': family}, ctx.headers)
        return present_tool_result(telecontrol_index(raw))

    @server.tool(annotations=_READ_ONLY)
    async def telecontrol_order(ctx: Context, family: _FAMILY, order_id: str) -> Any:
        """获取单条遥控指令定义（参数、编码规则）。"""
        return await call(ctx, f'/payload/telecontrol/order/{_path_part(order_id)}', family=family)

    @server.tool(annotations=_READ_ONLY)
    async def telecontrol_history(ctx: Context, source: str, limit: _LIMIT_500 = 50) -> Any:
        """获取遥控发送历史。source 为页面来源，如 xl-camera-v17 / xl_can_a。"""
        return await call(ctx, '/payload/telecontrol/history', source=source, limit=limit)

    # ---- 遥测 ----
    @server.tool(annotations=_READ_ONLY)
    async def telemetry_config(ctx: Context, family: _FAMILY | None = None) -> Any:
        """获取遥测表配置（有哪些遥测表 / 页面）。family 可选 biu / xl。"""
        return await call(ctx, '/payload/telemetry/config', family=family)

    @server.tool(annotations=_READ_ONLY)
    async def telemetry_table_def(ctx: Context, type: str, family: _FAMILY | None = None) -> Any:  # noqa: A002
        """获取遥测表定义（字段 id、名称、单位、换算）。type 为 HEX 数据类型。"""
        return await call(ctx, '/payload/telemetry/def', type=type, family=family)

    @server.tool(annotations=_READ_ONLY)
    async def telemetry_table(ctx: Context, type: str, source: str = 'live') -> Any:  # noqa: A002
        """获取遥测表最新值。source: live=实时 / db=历史库 / file=历史文件。"""
        return await call(ctx, '/payload/telemetry/table', type=type, source=source)

    @server.tool(annotations=_READ_ONLY)
    async def telemetry_fields(ctx: Context, type: str, family: _FAMILY | None = None) -> Any:  # noqa: A002
        """获取某遥测表的遥测量列表（用于选曲线字段）。"""
        return await call(ctx, '/payload/telemetry/fields', type=type, family=family)

    @server.tool(annotations=_READ_ONLY)
    async def telemetry_curve(ctx: Context, type: str, field: str, limit: _LIMIT_500 = 200) -> Any:  # noqa: A002
        """获取遥测量曲线最近 limit 个点。"""
        return await call(ctx, '/payload/telemetry/curve/data', type=type, field=field, limit=limit)

    # ---- 指令序列 ----
    @server.tool(annotations=_READ_ONLY)
    async def sequence_list(
        ctx: Context,
        project: str | None = None,
        seq_name: str | None = None,
        page_num: _PAGE_NUM = 1,
        page_size: _PAGE_SIZE = 20,
    ) -> Any:
        """分页查询指令序列。project: biu / xl；seq_name 模糊匹配。"""
        return await call(
            ctx, '/payload/sequence/list', project=project, seqName=seq_name, pageNum=page_num, pageSize=page_size
        )

    @server.tool(annotations=_READ_ONLY)
    async def sequence_detail(ctx: Context, seq_id: int) -> Any:
        """获取指令序列详情（步骤列表）。"""
        return await call(ctx, f'/payload/sequence/{int(seq_id)}')

    @server.tool(annotations=_READ_ONLY)
    async def sequence_runs(ctx: Context, seq_id: int, limit: _LIMIT_500 = 20) -> Any:
        """查询指令序列执行历史。"""
        return await call(ctx, f'/payload/sequence/{int(seq_id)}/runs', limit=limit)

    # ---- 配置文件 ----
    @server.tool(annotations=_READ_ONLY)
    async def config_file_list(ctx: Context) -> Any:
        """遥控 / 遥测配置文件列表。只返回文件名和大小等元数据，不返回服务器绝对路径。"""
        rows = strip_config_paths(await proxy.get('/payload/config-files/list', None, ctx.headers))
        return present_tool_result(rows)

    # ---- 通用只读查询 ----
    @server.tool(annotations=_READ_ONLY)
    async def payload_api_get(ctx: Context, path: str, params: dict[str, Any] | None = None) -> Any:
        """通用 GET 查询：调用后端 /payload/ 下的只读接口，或 /getInfo、/health（同样走登录与接口权限）。

        path 如 /payload/lvds/signals，params 为查询参数（驼峰命名，与接口文档一致）。
        """
        normalized = '/' + path.strip().lstrip('/')
        if '..' in normalized or not _PATH_SAFE.match(normalized):
            raise McpToolError(f'非法路径: {path}')
        if not _is_allowed_get_path(normalized):
            raise McpToolError(f'仅允许 {_PAYLOAD_GET_PREFIX} 前缀，或 {", ".join(sorted(_EXACT_GET_PATHS))}')
        return await call(ctx, normalized, **(params or {}))

    return server


def _is_allowed_get_path(path: str) -> bool:
    """/payload/ 按前缀放行；/getInfo、/health 必须整段相等，避免 /getInfoExtra 被当成同一接口。"""
    return path in _EXACT_GET_PATHS or path.startswith(_PAYLOAD_GET_PREFIX)


def _path_part(value: str) -> str:
    text = str(value).strip()
    if not text or '/' in text or '..' in text:
        raise McpToolError(f'非法参数: {value!r}')
    return text


def setup_mcp(app: FastAPI) -> MCPServer | None:
    """按配置在 app 上挂载 MCP 路由；会话管理器需在 lifespan 中通过 ``app.state.mcp_server`` 启动。"""
    if not McpConfig.mcp_enabled:
        return None
    app.add_middleware(McpBearerMiddleware)
    server = build_mcp_server(app)
    allowed_hosts = _split_csv(McpConfig.mcp_allowed_hosts)
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(allowed_hosts),
        allowed_hosts=allowed_hosts,
        allowed_origins=_split_csv(McpConfig.mcp_allowed_origins),
    )
    mcp_app = server.streamable_http_app(
        streamable_http_path=McpConfig.mcp_path,
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )
    app.router.routes.extend(mcp_app.routes)
    app.state.mcp_server = server
    logger.info(f'🤖 MCP 服务已挂载: {McpConfig.mcp_path}（只读工具，鉴权沿用登录 token）')
    return server
