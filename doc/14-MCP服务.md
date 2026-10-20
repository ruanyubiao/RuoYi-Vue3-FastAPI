# 14 · MCP 服务

后端启动后即挂载 MCP（Model Context Protocol）服务，供 Cursor、Claude Code、Claude Desktop 等 Agent 查询地检平台数据。实现基于官方 Python SDK（`mcp` 2.x，`MCPServer`），传输为 **Streamable HTTP**。

地址是后端本身，不是前端页面，也不是 `/dev-api` 代理：

```text
http://127.0.0.1:9099/mcp
```

端口按当前环境的 `APP_PORT` 调整。启动日志会出现 `MCP 服务已挂载: /mcp`。

## 能查什么

只读。Agent 可以看服务健康（数据库、Redis、采集进程）、版本、当前登录用户、设备会话与状态、IO 日志、遥控指令目录和单条指令定义、发送历史、遥测表与曲线、指令序列、配置文件名。不能打开设备、发遥控、执行序列或改配置，也不能读取配置文件原文。

`/mcp` 在传输层就检查登录 Bearer。没带 Token，或 Token 无效、已登出，直接返回 HTTP 401。真实部署带 `APP_ROOT_PATH` 时同样生效。通过之后，每次工具调用仍走现有登录校验和接口权限。

## 接入

### 1. 启动后端并取 token

```powershell
cd ruoyi-fastapi-backend
python app.py --env=dev
```

另开一个终端登录（开发环境默认账号见 `.env.dev`，下面按 `admin` / `admin123` 举例）：

```powershell
$r = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9099/login -Body @{username='admin';password='admin123'}
$r.token
```

token 即 `POST /login` 返回值，也是浏览器 Cookie `Admin-Token`。过期后重新登录。时长见 `JWT_EXPIRE_MINUTES` / `JWT_REDIS_EXPIRE_MINUTES`。不要把 token 写进会进 Git 的 `mcp.json`，放到环境变量 `PGT_MCP_TOKEN` 里。这个 token 和浏览器登录是同一份权限。只读用途只授予查询权限：`payload:device:query`、`payload:telecontrol:query`、`payload:board:query`，以及需要看遥测表时的 `payload:telemetry:view`。不要把 `payload:telecontrol:send` 或 `payload:device:operate` 授给它。页面上的查看权限（如 `payload:camera:view`）不能用来开关设备。

### 2. 把服务交给 Agent

客户端请求头带 `Authorization: Bearer <token>`。下面把 `<token>` 换成上一步拿到的字符串。

**Cursor**（项目 `.cursor/mcp.json`，或用户目录 `~/.cursor/mcp.json`）：

```json
{
  "mcpServers": {
    "pgt": {
      "url": "http://127.0.0.1:9099/mcp",
      "headers": { "Authorization": "Bearer ${env:PGT_MCP_TOKEN}" }
    }
  }
}
```

保存后在 Cursor 的 MCP 设置里确认 `pgt` 已连接、工具列表已出现。聊天里直接提问即可，Agent 会自己选工具，不需要手写调用。例如：

- 现在有哪些设备会话，哪些是活的？
- 数据库和 Redis 是否正常？
- 读一下某块单板最新遥测表。
- 某个总线族有哪些遥控指令？某条指令的参数是什么？

token 更新后重新保存 `mcp.json`，或在 MCP 面板里刷新该服务。

**Claude Code**：

```bash
claude mcp add --transport http pgt http://127.0.0.1:9099/mcp --header "Authorization: Bearer ${PGT_MCP_TOKEN}"
```

**Claude Desktop**（只支持 stdio，经 `mcp-remote` 桥到 HTTP）：

Windows 上把 `Authorization: Bearer …` 放进同一个参数，空格可能被拆开。按 mcp-remote 的写法把整段请求头放进环境变量：

```json
{
  "mcpServers": {
    "pgt": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://127.0.0.1:9099/mcp", "--header", "Authorization:${AUTH_HEADER}"],
      "env": { "AUTH_HEADER": "Bearer <token>" }
    }
  }
}
```

**检查工具是否挂上**（不经过 Agent）：

```bash
npx @modelcontextprotocol/inspector
```

用 Inspector 的 Proxy 模式。直连时浏览器 Origin 是 `http://localhost:6274`，而 `MCP_ALLOWED_ORIGINS` 默认是空的，带 Origin 的请求会返回 403。若必须直连，把该 Origin 写进 `MCP_ALLOWED_ORIGINS`。Transport 选 Streamable HTTP，URL 填 `http://127.0.0.1:9099/mcp`，Header 加 `Authorization`。能列出下表中的工具即表示服务可用。

## 工具

| 工具 | 说明 |
|---|---|
| `get_server_health` | 数据库、Redis、采集进程数量、版本和运行时间 |
| `payload_version` | `/payload/device/version` |
| `current_user` | `/getInfo`（确认 token 是否有效） |
| `list_device_sessions` / `device_status` / `device_snapshot` / `device_io_log` | `/payload/device/*` |
| `telecontrol_config` | 遥控指令目录：分类页、指令 id 和名称。整份参数定义不返回 |
| `telecontrol_order` / `telecontrol_history` | `/payload/telecontrol/order/{id}`、`/history` |
| `telemetry_config` / `telemetry_table_def` / `telemetry_table` / `telemetry_fields` / `telemetry_curve` | `/payload/telemetry/*` |
| `sequence_list` / `sequence_detail` / `sequence_runs` | `/payload/sequence/*` |
| `config_file_list` | `/payload/config-files/list`（文件名等元数据，无绝对路径，无原文） |
| `payload_api_get` | 通用 GET：`/payload/` 前缀的只读接口，以及整段匹配的 `/getInfo`、`/health`（参数驼峰，与 Swagger 一致） |

专用工具覆盖常用查询。Swagger 里已有、但上表没有单独列出的只读接口，用 `payload_api_get`，`path` 如 `/payload/lvds/signals`，`params` 与接口文档的驼峰参数一致。`/getInfo`、`/health` 必须整段相等，不能写成带后缀的路径。

列表结果是一个对象：`{"items": [...], "total": N}`。空列表也是这个对象，不会变成空响应。单次结果默认最多 60000 字。超出时按整条记录截断，并带 `truncated`、`returned` 和 `hint`；放不进条目的大对象只返回说明，不返回半截 JSON。配置文件列表不包含服务器绝对路径。

## 配置

写在 `.env.<env>` 或环境变量里。不写则用下表默认值。改完需重启后端。

| 变量 | 默认 | 说明 |
|---|---|---|
| `MCP_ENABLED` | `true` | 是否挂载。默认开启。`false` 关闭，且不导入 `mcp` 包 |
| `MCP_PATH` | `/mcp` | 路径 |
| `MCP_ALLOWED_HOSTS` | `127.0.0.1:*,localhost:*` | 允许的 Host（逗号分隔，`host:*` 匹配任意端口）。置空则不校验 Host |
| `MCP_ALLOWED_ORIGINS` | 空 | 允许的 Origin（逗号分隔）。为空时，带 Origin 的浏览器请求全部 403；不带 Origin 的本机客户端不受影响 |
| `MCP_MAX_RESULT_CHARS` | `60000` | 单次结果最大字符数；`<=0` 不截断 |

本机 Agent 连 `127.0.0.1` 即可。服务若绑在 `0.0.0.0`，用局域网 IP 访问会得到 421，需要把 `主机:端口` 加进 `MCP_ALLOWED_HOSTS`（例如 `192.168.1.10:*`），URL 改成对应地址。Host 校验用来挡住浏览器被骗去访问本机。

已有数据库执行对应补丁后，角色里才会出现设备查询、设备操作、遥控查询和单板配置查询，并授给已经拥有地检菜单的角色：`sql/patch-payload-query-perms-pg.sql`、`sql/patch-payload-query-perms-my.sql`、`sql/patch-payload-query-perms-sqlite.sql`。

`/mcp` 不走传输层加密。已有环境如果在 `TRANSPORT_CRYPTO_EXCLUDE_PATHS` 里手写了排除列表，要自己加上 `/mcp`。

## 实现

- `module_mcp/server.py`：工具定义。`BackendApiProxy` 用 `httpx.ASGITransport` 在进程内调用本应用的 GET。
- `server.py`：`create_app()` 末尾 `setup_mcp(app)` 挂路由；`lifespan` 中启动 `session_manager.run()`。
- 无状态（`stateless_http`）+ JSON 响应，不依赖粘性会话。
- 测试：`tests/framework/test_mcp_server.py`。
