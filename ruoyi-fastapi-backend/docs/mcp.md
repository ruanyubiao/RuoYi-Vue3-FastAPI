# MCP 服务

后端内置一个 MCP（Model Context Protocol）服务，基于官方 Python SDK（`mcp` 2.x，`MCPServer`），以 **Streamable HTTP** 方式挂在主应用上（默认 `/mcp`）。AI 客户端（Cursor、Claude Desktop / Claude Code 等）连上后可以直接查询地检平台数据。

## 安全模型

- **只读**：只暴露 GET 查询；不提供打开设备、发遥控、执行序列、改配置等有硬件或数据副作用的能力。
- **鉴权不绕过**：工具在进程内回调已有 `/payload/*` 接口，登录校验、接口权限、数据权限与前端一致。
- **token**：MCP 请求头 `Authorization: Bearer <token>` 原样转发；token 即前端登录拿到的 token（浏览器 Cookie `Admin-Token`，或 `POST /login` 返回值）。过期后需重新获取（时长见 `JWT_EXPIRE_MINUTES` / `JWT_REDIS_EXPIRE_MINUTES`）。
- **DNS rebinding 防护**：默认只接受 Host 为 `127.0.0.1` / `localhost` 的请求；局域网访问需在 `MCP_ALLOWED_HOSTS` 中加上实际地址。

## 配置（环境文件 `.env.<env>` 或环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `MCP_ENABLED` | `false` | 是否挂载 MCP 服务 |
| `MCP_PATH` | `/mcp` | 路径 |
| `MCP_DEFAULT_TOKEN` | 空 | 客户端未带 `Authorization` 时使用的兜底 token；**仅建议本机调试**，留空则必须由客户端携带 |
| `MCP_ALLOWED_HOSTS` | `127.0.0.1:*,localhost:*` | 允许的 Host（逗号分隔，`host:*` 匹配任意端口）；置空关闭 Host 校验 |
| `MCP_ALLOWED_ORIGINS` | 空 | 允许的 Origin（逗号分隔） |
| `MCP_MAX_RESULT_CHARS` | `60000` | 单次结果最大字符数，超出返回截断预览；`<=0` 不截断 |

开启后启动日志会打印 `MCP 服务已挂载: /mcp`。

## 工具

| 工具 | 对应接口 |
|---|---|
| `payload_version` | `/payload/device/version` |
| `current_user` | `/getInfo`（确认 token 是否有效） |
| `list_device_sessions` / `device_status` / `device_snapshot` / `device_io_log` | `/payload/device/*` |
| `telecontrol_config` / `telecontrol_order` / `telecontrol_history` | `/payload/telecontrol/*` |
| `telemetry_config` / `telemetry_table_def` / `telemetry_table` / `telemetry_fields` / `telemetry_curve` | `/payload/telemetry/*` |
| `sequence_list` / `sequence_detail` / `sequence_runs` | `/payload/sequence/*` |
| `config_file_list` / `config_file_content` | `/payload/config-files/*` |
| `payload_api_get` | 通用 GET：任一 `/payload/*` 只读接口（参数驼峰，与 Swagger 一致） |

## 客户端配置

先拿 token（开发环境端口 9099，按实际 env 调整）：

```powershell
$r = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9099/login -Body @{username='admin';password='admin123'}
$r.token
```

### Cursor（`~/.cursor/mcp.json` 或项目 `.cursor/mcp.json`）

```json
{
  "mcpServers": {
    "pgt": {
      "url": "http://127.0.0.1:9099/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

### Claude Code

```bash
claude mcp add --transport http pgt http://127.0.0.1:9099/mcp --header "Authorization: Bearer <token>"
```

### Claude Desktop（只支持 stdio 的客户端，经 `mcp-remote` 桥接）

```json
{
  "mcpServers": {
    "pgt": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://127.0.0.1:9099/mcp", "--header", "Authorization: Bearer <token>"]
    }
  }
}
```

### 调试

```bash
npx @modelcontextprotocol/inspector
# Transport 选 Streamable HTTP，URL 填 http://127.0.0.1:9099/mcp，Header 加 Authorization
```

## 实现

- `module_mcp/server.py`：工具定义；`BackendApiProxy` 用 `httpx.ASGITransport` 在进程内调用本应用接口。
- `server.py`：`create_app()` 末尾 `setup_mcp(app)` 挂路由；`lifespan` 中启动 `session_manager.run()`。
- 以无状态（`stateless_http`）+ JSON 响应模式运行，不依赖粘性会话，多 worker 也可用。
- 测试：`tests/test_mcp_server.py`。
