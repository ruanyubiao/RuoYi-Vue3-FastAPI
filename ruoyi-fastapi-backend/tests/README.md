# 后端 tests


## 测试依赖

在本目录执行（需已安装 `pytest`、`pytest-asyncio`；覆盖率另需 `pytest-cov`）：

```bash
pip install pytest pytest-asyncio pytest-cov
```


## 单元测试

在 `ruoyi-fastapi-backend` 目录执行（不带参数，与根目录 `run_test.bat` 里的 `venv\Scripts\pytest.exe` 相同，收集下面全部分目录）：

```text
pytest
```

| 目录 | 保护什么 |
|------|----------|
| `tests/web/` | 地检页面的 controller、service、fileplay、canplay、主进程 Redis |
| `tests/collect/` | 采集进程、采集侧 Redis、硬件 |
| `tests/protocol/` | 协议、组帧、配置、遥测解析、黄金样本 |
| `tests/shared/` | Redis key、常量、分层 import 守门、`store/` |
| `tests/framework/` | 若依、中间件、utils、config、MCP |
| `tests/coverage/` | 为覆盖率补行数的用例，以及把源码导入分母的用例 |
| `tests/cli/` | 命令行。其中文件名带 coverage 的，以及列在下面的 7 个补覆盖率文件，留在原处 |

`conftest.py`、`redis_fakes.py`、`platform_marks.py`、`extension_checks.py`、`tests/data/`、`_gen_tm_golden.py` 留在 `tests/` 根上。

只看行为锁（仍在后端目录执行）：

```text
pytest --ignore=tests/coverage --ignore-glob="*coverage*.py" --ignore=tests/cli/wizard/test_wizard_leftovers.py --ignore=tests/cli/completion/test_providers_leftovers.py --ignore=tests/cli/completion/test_installers_leftovers.py --ignore=tests/cli/tui/screens/test_screens_gap_boost.py --ignore=tests/cli/tui/test_app_commands_diagnostics_leftovers.py --ignore=tests/cli/test_wizard_shared_gaps.py --ignore=tests/cli/test_completion_gaps.py
```


## 覆盖率（全后端）

统计范围见后端目录下的 `ruoyi-fastapi-backend/.coveragerc`：`cli` / `common` / `config` / `exceptions` / `middlewares` / `module_admin` / `module_generator` / `module_payload` / `module_task` / `sub_applications` / `utils`（含框架与 payload；不含 `tests`、`alembic/versions`）。

```bash
# Windows PowerShell
$env:PYTHONPATH = (Get-Location).Path
python -m pytest tests --cov --cov-config=.coveragerc --cov-report=term:skip-covered

# Linux / macOS
export PYTHONPATH="$PWD"
python -m pytest tests --cov --cov-config=.coveragerc --cov-report=term:skip-covered
```

> **统计口径说明**：`module_payload/`、`module_admin/` 等是命名空间包（无 `__init__.py`），coverage.py 只统计被导入过的文件。
> `tests/coverage/test_import_all_sources.py` 会逐个导入 `.coveragerc` source 下全部模块，保证未被测试触达的文件（例如控制器）也计入分母，避免覆盖率虚高。

## 平台相关与不稳定用例

| 机制 | 位置 | 说明 |
|------|------|------|
| `@windows_only` | `tests/platform_marks.py` | 依赖 `WindowsPath` / `LOCALAPPDATA` / `ctypes.WinDLL` 的用例在非 Windows 自动跳过 |
| DEMO 虚拟 CAN 探测 | `tests/collect/test_can_demo_cross_process.py` | gpcan DEMO 厂商依赖 Windows 命名管道，不可用时整文件跳过（marker `virtual_hw`） |
| `PGT_PERF_SCALE` | `tests/protocol/test_d9v17_5000hz.py`、`tests/protocol/test_d9v17_600hz.py` | 性能预算倍率，默认 1；CI 共享 runner 设为 3。600 帧逐帧写入的基准是 4s |
| PNG 黄金比对 | `tests/protocol/test_camera_image_capture_frames.py` | 只比解码后的像素，不比 PNG 压缩字节（随 Pillow/zlib 版本变化） |

## 接口层测试

`tests/web/test_payload_controllers_api.py`：挂载 `module_payload/controller` 全部 8 个路由器（不连 MySQL/Redis），
校验路由前缀、每个接口未登录返回 401、缺按钮权限返回 403、典型接口的参数透传与 422 校验。

## CI

`.github/workflows/unit-tests.yml` 在 Ubuntu 与 Windows 上运行本目录测试（含 `dist/pkg` 扩展 wheel）。

可选：生成 HTML / JSON 报告（用完可删）：

```bash
python -m pytest tests --cov --cov-config=.coveragerc --cov-report=html:coverage-backend-html --cov-report=json:coverage-backend.json --cov-report=term:skip-covered
```

仅看 payload（历史命令，可选）：

```bash
python -m pytest tests --ignore=tests/cli --cov=module_payload --cov=common --cov-report=term:skip-covered
```


## 遥测解析回归

黄金对照 ``tm_golden_cases.json`` 在 `assets/data/`（后端模拟页也会读，需打包）。
人工 hex 清单与其它**仅测试用**样本放在 `tests/data/`。

| 文件 | 作用 |
|------|------|
| `tests/data/遥测数据.txt` | 人工维护的 hex 样本清单，每种遥测一行（或一组）原始帧 |
| `tests/data/camera_ctrl_serial_COM4_*_recv.bin` | 历史文件回放：相机 **v1.6** 控制串口实采（混有 D8/D9） |
| `tests/data/biu_can_a_can_*_recv.txt` | 历史文件回放：BIU CAN 实采（FF/FD/FB/F9/F7/FE/FC） |
| `tests/data/payload_tm_frame.sql` | MySQL 归档导出（BIU 实采行）：供 canplay open/get_frame 回归 |
| `tests/data/telecontrol_wire_goldens.json` | 遥控组帧 wire hex 黄金（BIU / 相机 / 热控单板） |
| `assets/data/tm_golden_cases.json` | 回归对照（亦供后端模拟页）：含 `kind`、`hex`、`result` |
| `_gen_tm_golden.py` | **仅在解析代码确认正确时**运行，根据 txt 重新生成 json |
| `test_tm_golden_parse.py` | pytest：解析 json 里的 `hex`，与同对象的 `result` 对比 |
| `test_fileplay_camera_recv_regression.py` | 相机 recv.bin → fileplay 索引/真实解析 |
| `test_fileplay_biu_can_recv_regression.py` | BIU CAN recv.txt → 多表类型索引/真实解析；与归档 points_json 对拍 |
| `test_canplay_archive_regression.py` | canplay：SQL 归档行 → open 计数 + raw_hex/`points_json` 全键对拍 |
| `test_telecontrol_wire_golden.py` | 遥控固定指令 → 整帧 hex 字节级锁定 |
| `test_eng_multi_subpkt_regression.py` | 工程遥测多包子包拼装 + 内层 DJ 解析对齐 |

`assets/data/tm_golden_cases.json` 形态：

```json
{
    "passthrough_cam_d8": {
    "kind": "camera",
    "hex": "EB 90 D8 ...",
    "result": { "table_key": "D8", "fields": [] }
  },
  "passthrough_cam_v17_d8": {
    "kind": "camera_v17",
    "hex": "EB 90 D8 ...",
    "result": { "table_key": "D8V17", "fields": [] }
  }
}
```

测试流程：读 json → 用 `hex` 走 ingest → 与 `result` 对比。测试文件**不引用** `_gen_tm_golden.py`。

重新冻结对照（cfg 或解析规则变更、且当前解析结果已核对正确）：

```text
python tests/_gen_tm_golden.py
```

然后检查 `assets/data/tm_golden_cases.json` 的 diff，再跑：

```text
pytest tests/protocol/test_tm_golden_parse.py
```

`遥测数据.txt` 里每一条 hex 都必须出现在 json 的某个类型对象中。

公式算出的 `inf` / `nan` 在 json 里写成 `null`（标准 JSON 没有 Infinity）。
