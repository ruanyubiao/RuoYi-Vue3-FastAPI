"""MCP（Model Context Protocol）服务：把后端只读能力以 MCP 工具形式暴露给 AI 客户端。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from config.env import McpConfig

if TYPE_CHECKING:
    from fastapi import FastAPI
    from mcp.server.mcpserver import MCPServer


def setup_mcp(app: FastAPI) -> MCPServer | None:
    """默认挂载 MCP 路由；MCP_ENABLED=false 时不导入 mcp 依赖。"""
    if not McpConfig.mcp_enabled:
        return None
    from module_mcp.server import setup_mcp as _setup_mcp  # noqa: PLC0415

    return _setup_mcp(app)


__all__ = ['setup_mcp']
