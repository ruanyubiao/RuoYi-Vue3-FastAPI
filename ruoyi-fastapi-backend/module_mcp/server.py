"""
后端 MCP 服务（Streamable HTTP，默认挂在 ``/mcp``）。

设计要点：
- 工具不直接调 service，而是在进程内（httpx.ASGITransport）回调本应用已有的 GET 接口，
  因此 **登录校验、接口权限、参数校验、数据权限** 与前端走的是同一条链路，不会绕过。
- 认证：转发 MCP 请求自带的 ``Authorization: Bearer <token>``（与前端同一个登录 token）；
  请求未带时可回落到 ``MCP_DEFAULT_TOKEN``（仅建议本机调试使用）。
- 只读：只暴露 GET 查询；不提供打开设备、发送遥控、执行序列、改配置等有硬件/数据副作用的能力。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from config.env import AppConfig, McpConfig
from utils.log_util import logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastapi import FastAPI

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_INTERNAL_BASE_URL = 'http://pgt-mcp.internal'
_TIMEOUT_SECONDS = 30.0
_HTTP_OK = 200
# 通用查询工具允许访问的 GET 前缀（payload 业务 + 少量只读系统信息）
_GENERIC_GET_PREFIXES = ('/payload/', '/getInfo', '/health')
_PATH_SAFE = re.compile(r'^/[A-Za-z0-9_\-./{}]*$')


class McpToolError(ToolError):
    """工具调用失败（会以 isError 结果返回给 MCP 客户端）。"""


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in (value or '').split(',') if item.strip()]


def _auth_header(headers: Mapping[str, str] | None) -> str | None:
    if headers:
        for key, value in headers.items():
            if key.lower() == 'authorization' and value:
                return value
    if McpConfig.mcp_default_token:
        token = McpConfig.mcp_default_token
        return token if token.lower().startswith('bearer ') else f'Bearer {token}'
    return None


def _clean_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if value is None:
            continue
        cleaned[key] = str(value).lower() if isinstance(value, bool) else value
    return cleaned


class BackendApiProxy:
    """在进程内调用本应用接口，复用全部中间件与鉴权依赖。"""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def get(self, path: str, params: Mapping[str, Any] | None, headers: Mapping[str, str] | None) -> Any:
        auth = _auth_header(headers)
        if not auth:
            raise McpToolError('未提供认证信息：请在 MCP 客户端配置 Authorization: Bearer <登录token>')
        transport = httpx.ASGITransport(app=self._app, client=('127.0.0.1', 0))
        async with httpx.AsyncClient(
            transport=transport, base_url=_INTERNAL_BASE_URL, timeout=_TIMEOUT_SECONDS
        ) as client:
            response = await client.get(path, params=_clean_params(params), headers={'Authorization': auth})
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


def _truncate(value: Any) -> Any:
    """超大结果截断，避免把几 MB 的遥测数据灌进模型上下文。"""
    limit = McpConfig.mcp_max_result_chars
    if limit <= 0:
        return value
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return value
    return {'truncated': True, 'totalChars': len(text), 'preview': text[:limit]}


def build_mcp_server(app: FastAPI) -> MCPServer:
    """创建 MCP 服务并注册只读工具。"""
    proxy = BackendApiProxy(app)
    server = MCPServer(
        name=f'{AppConfig.app_name} MCP',
        version=AppConfig.app_version,
        instructions=(
            '激光终端地检系统后端（RuoYi-FastAPI）的只读查询工具。'
            'family 取值通常为 biu / xl / yj216；遥测 type 为 HEX 数据类型（如 FF）。'
            '先用 telemetry_config / telecontrol_config 拿到可用的表与指令，再查明细。'
        ),
    )

    async def call(ctx: Context, path: str, **params: Any) -> Any:
        return _truncate(await proxy.get(path, params, ctx.headers))

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
    async def device_io_log(ctx: Context, device_id: str, since_seq: int = 0, limit: int = 200) -> Any:
        """查询设备原始收发日志（预览）。"""
        return await call(ctx, '/payload/device/io-log', deviceId=device_id, sinceSeq=since_seq, limit=limit)

    # ---- 遥控 ----
    @server.tool(annotations=_READ_ONLY)
    async def telecontrol_config(ctx: Context, family: str) -> Any:
        """获取某总线族的遥控配置（页面、指令列表等）。family: biu / xl / yj216。"""
        return await call(ctx, '/payload/telecontrol/config', family=family)

    @server.tool(annotations=_READ_ONLY)
    async def telecontrol_order(ctx: Context, family: str, order_id: str) -> Any:
        """获取单条遥控指令定义（参数、编码规则）。"""
        return await call(ctx, f'/payload/telecontrol/order/{_path_part(order_id)}', family=family)

    @server.tool(annotations=_READ_ONLY)
    async def telecontrol_history(ctx: Context, source: str, limit: int = 50) -> Any:
        """获取遥控发送历史。source 为页面来源，如 xl-camera-v17 / xl_can_a。"""
        return await call(ctx, '/payload/telecontrol/history', source=source, limit=limit)

    # ---- 遥测 ----
    @server.tool(annotations=_READ_ONLY)
    async def telemetry_config(ctx: Context, family: str | None = None) -> Any:
        """获取遥测表配置（有哪些遥测表 / 页面）。family 可选 biu / xl。"""
        return await call(ctx, '/payload/telemetry/config', family=family)

    @server.tool(annotations=_READ_ONLY)
    async def telemetry_table_def(ctx: Context, type: str, family: str | None = None) -> Any:  # noqa: A002
        """获取遥测表定义（字段 id、名称、单位、换算）。type 为 HEX 数据类型。"""
        return await call(ctx, '/payload/telemetry/def', type=type, family=family)

    @server.tool(annotations=_READ_ONLY)
    async def telemetry_table(ctx: Context, type: str, source: str = 'live') -> Any:  # noqa: A002
        """获取遥测表最新值。source: live=实时 / db=历史库 / file=历史文件。"""
        return await call(ctx, '/payload/telemetry/table', type=type, source=source)

    @server.tool(annotations=_READ_ONLY)
    async def telemetry_fields(ctx: Context, type: str, family: str | None = None) -> Any:  # noqa: A002
        """获取某遥测表的遥测量列表（用于选曲线字段）。"""
        return await call(ctx, '/payload/telemetry/fields', type=type, family=family)

    @server.tool(annotations=_READ_ONLY)
    async def telemetry_curve(ctx: Context, type: str, field: str, limit: int = 200) -> Any:  # noqa: A002
        """获取遥测量曲线最近 limit 个点。"""
        return await call(ctx, '/payload/telemetry/curve/data', type=type, field=field, limit=limit)

    # ---- 指令序列 ----
    @server.tool(annotations=_READ_ONLY)
    async def sequence_list(
        ctx: Context,
        project: str | None = None,
        seq_name: str | None = None,
        page_num: int = 1,
        page_size: int = 20,
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
    async def sequence_runs(ctx: Context, seq_id: int, limit: int = 20) -> Any:
        """查询指令序列执行历史。"""
        return await call(ctx, f'/payload/sequence/{int(seq_id)}/runs', limit=limit)

    # ---- 配置文件 ----
    @server.tool(annotations=_READ_ONLY)
    async def config_file_list(ctx: Context) -> Any:
        """遥控 / 遥测配置文件列表。"""
        return await call(ctx, '/payload/config-files/list')

    @server.tool(annotations=_READ_ONLY)
    async def config_file_content(ctx: Context, name: str) -> Any:
        """读取配置文件原文（name 来自 config_file_list）。"""
        return await call(ctx, '/payload/config-files/content', name=name)

    # ---- 通用只读查询 ----
    @server.tool(annotations=_READ_ONLY)
    async def payload_api_get(ctx: Context, path: str, params: dict[str, Any] | None = None) -> Any:
        """通用 GET 查询：调用后端任一 /payload/* 只读接口（同样走登录与接口权限）。

        path 如 /payload/lvds/signals，params 为查询参数（驼峰命名，与接口文档一致）。
        """
        normalized = '/' + path.strip().lstrip('/')
        if '..' in normalized or not _PATH_SAFE.match(normalized):
            raise McpToolError(f'非法路径: {path}')
        if not normalized.startswith(_GENERIC_GET_PREFIXES):
            raise McpToolError(f'仅允许 {", ".join(_GENERIC_GET_PREFIXES)} 开头的接口')
        return await call(ctx, normalized, **(params or {}))

    return server


def _path_part(value: str) -> str:
    text = str(value).strip()
    if not text or '/' in text or '..' in text:
        raise McpToolError(f'非法参数: {value!r}')
    return text


def setup_mcp(app: FastAPI) -> MCPServer | None:
    """按配置在 app 上挂载 MCP 路由；会话管理器需在 lifespan 中通过 ``app.state.mcp_server`` 启动。"""
    if not McpConfig.mcp_enabled:
        return None
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
