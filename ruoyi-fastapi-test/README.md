# 地检 E2E（Playwright）

测的是浏览器里的若依后台 + 地检业务页（登录、系统管理、遥控/遥测/单板/调试菜单）。**不打开**串口、CAN、PCIe，也不对真实载荷下指令。
Python 后端必须在 **PC** 上跑。MySQL、Redis、Nginx 用一套独立的 `test-*` 容器，**不会**动你正在用的 `mysql8` / `redis` / `nginx`。

日常一条命令（在 `ruoyi-fastapi-test`）：

```bat
run_test.bat
```

前端 `dist` 不存在时会先 `npm run build`。界面改过需要重新打包时：

```bat
run_test.bat rebuild
```

脚本会：重建 `test-*` 容器（用最新 SQL 初始化）→ 本机 `python app.py --env=test` → `pytest` → 停测试后端并 `docker compose down -v`。只操作 `docker\compose.yml` 这一份，不会 `stop`/`rm` 开发容器。

## 端口（不要和开发抢）

| 服务 | 开发（勿动） | 测试 |
|---|---|---|
| MySQL | `mysql8` → 3306 | `test-mysql` → **13307** |
| Redis | `redis` → 6379 | `test-redis` → **16380** |
| Nginx | `nginx` → 12580 | `test-nginx` → **18080** |
| 后端 | `--env=dev` → 9099 | `--env=test` → **19099** |

后端只用 `ruoyi-fastapi-backend/.env.test`。不要用 `.env.dev` / `.env.prod`。

Playwright 访问：前端 `http://localhost:18080`，接口直连 `http://localhost:19099`。浏览器里的 `/prod-api` 由 `test-nginx` 转到本机 19099。

账号：`admin` / `admin123`。验证码：库脚本里已关，初始化时再执行一次 `disable_captcha.sql`。

## SQL 映射

`test-mysql` **每次空库启动**都会执行：

`ruoyi-fastapi-backend/sql/ruoyi-fastapi-my.sql`

这是仓库里的正本。不要再维护 `docker/mysql/sql` 副本。MySQL 只在数据目录为空时跑 `initdb.d`；本测试栈 **不挂数据卷**，每次 `down` 后下次 `up` 都是空库，因此会吃到最新 SQL。

路径注意：compose 在 `docker/compose.yml`，相对路径是 `../../ruoyi-fastapi-backend/sql/ruoyi-fastapi-my.sql`（不是 `../ruoyi-fastapi-backend/...`）。

## 手工步骤（不用 bat 时）

```bat
cd ruoyi-fastapi-frontend
npm run build

cd ..\ruoyi-fastapi-test
docker compose -f docker\compose.yml down -v
docker compose -f docker\compose.yml up -d

cd ..\ruoyi-fastapi-backend
python app.py --env=test

cd ..\ruoyi-fastapi-test
python -m pytest -v

docker compose -f docker\compose.yml down -v
```

测试后端窗口自己关掉。

## 清理

`run_test.bat` 结束时会 `down -v`。只拆 `test-mysql` / `test-redis` / `test-nginx` 和本项目的匿名层，**不会**删 `mysql8` 的数据目录。

若中途 Ctrl+C 没清干净：

```bat
cd ruoyi-fastapi-test
docker compose -f docker\compose.yml down -v
```

再在任务管理器里结束带 `app.py --env=test` 的 python（不要杀 `--env=dev`）。

## 依赖（已装过可跳过）

```bat
cd ruoyi-fastapi-test
pip install -r requirements.txt
playwright install
```

## 测什么

| 目录 | 内容 |
|---|---|
| `test_login.py` / `test_pages.py` | 登录、首页、若依工具页 |
| `system/` `monitor/` `tool/` | 原若依用户/角色/菜单/监控等 |
| `payload/test_payload_pages.py` | 地检菜单页冒烟（BIU/XL 控制与遥控、指令序列、遥测表/曲线/归档、相机/热控/ZK、LVDS、重构、调试四页）；序列「新增」只进编辑页，不保存 |
| `payload/test_payload_api.py` | 地检 `/payload/*` 无硬件副作用的读/安全写；**模拟页样例注入 → 拉遥测表，与 `tm_golden_cases` 解析结果逐字段比对**。**跳过** open/send/run、改盘配置、文件 upload/parse |

冒烟固定打 **test 栈**（`common/config.py`：后端 `19099` / 前端 `18080`），由 `run_test.bat` 拉起。开发调试后端 `:9099` 只用于写用例时手工取数，**不要**当作冒烟目标。

只跑地检相关（需先起 test 栈）：

```bat
python -m pytest payload -v
```

只跑模拟注入→黄金比对：

```bat
python -m pytest payload/test_payload_api.py::test_simulate_pipeline_then_telemetry_table -v
```

## 目录

- `payload/`：地检新增功能的页面 + 接口测试
- `docker/compose.yml`：测试栈（唯一要 `up` 的 compose）
- `docker/nginx/conf.d/test.conf`：测试 nginx，`/prod-api` → `host.docker.internal:19099`
- `docker-compose.test.pg.yml` 等旧全容器方案已去掉
