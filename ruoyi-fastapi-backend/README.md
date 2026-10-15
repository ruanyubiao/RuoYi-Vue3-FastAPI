# ruoyi-fastapi-backend

地检平台后端（FastAPI）。安装与启动步骤见仓库根目录 [README.md](../README.md)。

## 快速开始

```bash
pip install -r requirements.txt
# 扩展包不在 PyPI，从 dist/pkg 安装（Windows 用 ..\dist\pkg\...）
pip install ../dist/pkg/telemetryparser-1.0.1-py3-none-any.whl ../dist/pkg/gpcan-1.0.5-py3-none-any.whl
python app.py --env=dev        # 环境文件 .env.dev（MySQL + Redis）；--env=sqlite 免数据库服务
```

## 目录

| 目录 | 说明 |
|------|------|
| `module_payload/` | 地检业务：`controller/`（8 个 `/payload/*` 路由器）、`service/`、`collectors/`（采集进程）、`protocol/`（组帧/解析） |
| `module_mcp/` | MCP 服务（只读工具，Streamable HTTP `/mcp`，见 [docs/mcp.md](docs/mcp.md)） |
| `module_admin/` / `module_generator/` / `module_task/` | 若依框架模块 |
| `cli/` | `ruoyi` 命令行（见 [docs/cli_usage.md](docs/cli_usage.md)） |
| `alembic/` | 数据库迁移（`alembic.ini`） |
| `sql/` | MySQL / PostgreSQL / SQLite 初始化脚本 |
| `assets/config/` | 遥控/遥测 JSON 配置（见 `doc/06-配置文件说明.md`） |
| `tests/` | pytest 测试 |

## 文档

- 测试用例：[tests/README.md](tests/README.md)
- CLI：[docs/cli_usage.md](docs/cli_usage.md)
- MCP 服务（AI 客户端接入）：[docs/mcp.md](docs/mcp.md)
- 传输加密配置：[docs/transport_crypto_config.md](docs/transport_crypto_config.md)
- 接口设计：[../doc/04-后端接口设计.md](../doc/04-后端接口设计.md)

## MCP 服务

后端可作为 MCP（Model Context Protocol）服务给 Claude / Cursor 等 AI 客户端调用，提供遥控/遥测配置、遥测表、指令序列、设备状态等**只读**查询工具。默认关闭，在环境文件（如 `.env.dev`）中开启：

```ini
MCP_ENABLED=true
```

重启后端后地址为 `http://127.0.0.1:9099/mcp`（Streamable HTTP），客户端需带登录 token：`Authorization: Bearer <token>`。Cursor 配置示例与全部配置项见 [docs/mcp.md](docs/mcp.md)。
