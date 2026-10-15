# 地检上位机（卫星激光终端地面检测系统）

基于 [RuoYi-Vue3-FastAPI](https://github.com/insistence/RuoYi-Vue3-FastAPI) 二次开发的 B/S 地检平台：
FastAPI 后端 + Vue3 前端 + 多进程数据采集（CAN / 串口 / UDP），进程间经 Redis 交换数据。
设计文档见 [`doc/README.md`](doc/README.md)。

## 环境要求

| 组件 | 版本 | 依据 |
| ---- | ---- | ---- |
| Python | 3.11 – 3.13（推荐 3.13） | `ruoyi-fastapi-backend/pyproject.toml`（`requires-python >=3.11`）、`Dockerfile.my`（`python:3.13`） |
| Node.js | 18+（推荐 20） | Vite 6 要求 |
| 数据库 | MySQL 8（默认）/ PostgreSQL / SQLite 三选一 | `ruoyi-fastapi-backend/.env.*` 中 `DB_TYPE` |
| Redis | 6+（必需，采集进程与主进程通信） | `.env.*` 中 `REDIS_*` |

主要依赖版本（以仓库文件为准）：

| 后端（`ruoyi-fastapi-backend/requirements.txt`） | 前端（`ruoyi-fastapi-frontend/package.json`） |
| ---- | ---- |
| FastAPI 0.128.2、SQLAlchemy 2.0.46、Alembic 1.18.3 | Vue 3.5.26、Vite 6.4.1、Element Plus 2.13.1 |
| redis 7.1.0、APScheduler 3.11.2、pyserial 3.5 | Pinia 3.0.4、vue-router 4.6.4、ECharts 5.6.0 |
| 扩展包（不在 PyPI）：`gpcan` 1.0.5、`telemetryparser` 1.0.1，位于 `dist/pkg/` | 测试：Vitest 3、happy-dom、@vue/test-utils |

## 目录结构

| 目录 | 说明 |
| ---- | ---- |
| `ruoyi-fastapi-backend` | 后端（FastAPI）；业务模块 `module_payload`，框架模块 `module_admin` 等 |
| `ruoyi-fastapi-frontend` | 前端（Vue3 + Element Plus） |
| `ruoyi-fastapi-app` | 手机前端 |
| `ruoyi-fastapi-test` | Playwright E2E 测试 |
| `dist` | 离线安装脚本；**`dist/pkg/` 下是扩展 wheel**（gpcan、telemetryparser） |
| `doc` | 设计文档 |
| `.github/workflows` | CI：单元测试、E2E、Ruff |

## 一、准备数据库与 Redis

默认（`--env=dev`）使用 MySQL，连接参数在 `ruoyi-fastapi-backend/.env.dev`
（`DB_HOST=localhost`、`DB_PORT=3306`、`DB_USERNAME=root`、`DB_PASSWORD=123456`、`DB_DATABASE=ruoyi-fastapi`，
`REDIS_HOST=localhost`、`REDIS_PORT=6379`），按本机实际修改。

初始化库（三选一，SQL 都在 `ruoyi-fastapi-backend/sql/`）：

```bash
# MySQL（默认）
mysql -uroot -p -e "CREATE DATABASE IF NOT EXISTS \`ruoyi-fastapi\` DEFAULT CHARSET utf8mb4"
mysql -uroot -p ruoyi-fastapi < ruoyi-fastapi-backend/sql/ruoyi-fastapi-my.sql

# PostgreSQL：导入 sql/ruoyi-fastapi-pg.sql，并在 .env 中设置 DB_TYPE='postgresql'（需另装 requirements-pg.txt）

# SQLite：无需数据库服务，使用 .env.sqlite（DB_TYPE='sqlite'，自动生成 ruoyi-fastapi.db）
cd ruoyi-fastapi-backend
sqlite3 ruoyi-fastapi.db < sql/ruoyi-fastapi-sqlite.sql
```

启动 Redis（任选）：本机安装的 `redis-server`，或 `docker run -d -p 6379:6379 redis`。

## 二、后端

**Windows（cmd）**

```bat
cd ruoyi-fastapi-backend
python -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
:: 扩展包不在 PyPI，从 dist\pkg 安装
pip install ..\dist\pkg\telemetryparser-1.0.1-py3-none-any.whl ..\dist\pkg\gpcan-1.0.5-py3-none-any.whl

python app.py --env=dev
:: 或使用 CLI：ruoyi app run --env=dev   （见 docs/cli_usage.md）
```

**Linux / macOS**

```bash
cd ruoyi-fastapi-backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install ../dist/pkg/telemetryparser-1.0.1-py3-none-any.whl ../dist/pkg/gpcan-1.0.5-py3-none-any.whl

python app.py --env=dev
```

`--env` 对应 `ruoyi-fastapi-backend/.env.<env>`：

| `--env` | 数据库 | 用途 |
| ---- | ---- | ---- |
| `dev` | MySQL `localhost:3306` | 本机开发（默认推荐） |
| `sqlite` | SQLite `ruoyi-fastapi.db` | 免数据库服务 |
| `test` | MySQL `127.0.0.1:13307`，Redis `16380`，后端端口 `19099` | E2E 测试栈（见 `ruoyi-fastapi-test/README.md`） |
| `prod` / `dockermy` / `dockerpg` | 见对应 `.env` 文件 | 生产 / Docker |

后端默认监听 `0.0.0.0:9099`（`.env.dev` 中 `APP_PORT`）；启动日志会打印 Swagger 文档地址（`APP_ROOT_PATH` 为 `/dev-api`）。

## 三、前端

```bash
cd ruoyi-fastapi-frontend
npm install            # 国内可加 --registry=https://registry.npmmirror.com
npm run dev            # 开发服务器 http://localhost:80，/dev-api 代理到 127.0.0.1:9099（vite.config.js）
npm run build:prod     # 生产打包到 dist/
```

> Linux / macOS 普通用户无法监听 80 端口，可临时 `npm run dev -- --port 8080`。

## 四、访问

- 地址：`http://localhost:80`（开发服务器）
- 默认账号：`admin` / `admin123`

## 五、测试

| 测试 | 位置 | 命令 |
| ---- | ---- | ---- |
| 后端单元/集成（pytest） | `ruoyi-fastapi-backend/tests` | `cd ruoyi-fastapi-backend && pip install pytest pytest-asyncio pytest-cov && python -m pytest tests`（详见 `tests/README.md`） |
| 前端单元/组件（Vitest） | `ruoyi-fastapi-frontend/tests` | `cd ruoyi-fastapi-frontend && npm run test:run`（覆盖率 `npm run test:coverage`） |
| E2E（Playwright） | `ruoyi-fastapi-test` | Windows：`run_test.bat`；详见 `ruoyi-fastapi-test/README.md` |

CI：`.github/workflows/unit-tests.yml`（Linux + Windows 跑 pytest，Linux 跑 Vitest）、`playwright.yml`（E2E）、`ruff.yml`。

## 六、离线部署（Windows 现场机）

见 [`dist/README.md`](dist/README.md)：`install_backend.bat` / `install_frontend.bat`，扩展 wheel 同样取自 `dist\pkg`。

## 关于

[基于 RuoYi-Vue3-FastAPI 二次开发](https://github.com/insistence/RuoYi-Vue3-FastAPI)
