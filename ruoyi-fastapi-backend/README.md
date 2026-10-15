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
| `module_admin/` / `module_generator/` / `module_task/` | 若依框架模块 |
| `cli/` | `ruoyi` 命令行（见 [docs/cli_usage.md](docs/cli_usage.md)） |
| `alembic/` | 数据库迁移（`alembic.ini`） |
| `sql/` | MySQL / PostgreSQL / SQLite 初始化脚本 |
| `assets/config/` | 遥控/遥测 JSON 配置（见 `doc/06-配置文件说明.md`） |
| `tests/` | pytest 测试 |

## 文档

- 测试用例：[tests/README.md](tests/README.md)
- CLI：[docs/cli_usage.md](docs/cli_usage.md)
- 传输加密配置：[docs/transport_crypto_config.md](docs/transport_crypto_config.md)
- 接口设计：[../doc/04-后端接口设计.md](../doc/04-后端接口设计.md)
