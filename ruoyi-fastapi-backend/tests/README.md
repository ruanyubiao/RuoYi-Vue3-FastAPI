# 后端 tests


## 测试依赖

在本目录执行（需已安装 `pytest`、`pytest-asyncio`；覆盖率另需 `pytest-cov`）：

```bash
pip install pytest pytest-asyncio pytest-cov
```


## 单元测试

在 `ruoyi-fastapi-backend` 目录执行：

```text
python -m pytest tests
```


## 覆盖率（全后端）

统计范围见根目录 `.coveragerc`：`cli` / `common` / `config` / `exceptions` / `middlewares` / `module_admin` / `module_generator` / `module_payload` / `module_task` / `sub_applications` / `utils`（含框架与 payload；不含 `tests`、`alembic/versions`）。

```bash
# Windows PowerShell
$env:PYTHONPATH = (Get-Location).Path
python -m pytest tests --cov --cov-config=.coveragerc --cov-report=term:skip-covered

# Linux / macOS
export PYTHONPATH="$PWD"
python -m pytest tests --cov --cov-config=.coveragerc --cov-report=term:skip-covered
```

可选：生成 HTML / JSON 报告（用完可删）：

```bash
python -m pytest tests --cov --cov-config=.coveragerc --cov-report=html:coverage-backend-html --cov-report=json:coverage-backend.json --cov-report=term:skip-covered
```

仅看 payload（历史命令，可选）：

```bash
python -m pytest tests --ignore=tests/cli --cov=module_payload --cov=common --cov-report=term:skip-covered
```


## 遥测解析回归

对照数据放在 `assets/data/`（打包进 wheel），hex 清单仍在 `tests/`。

| 文件 | 作用 |
|------|------|
| `tests/遥测数据.txt` | 人工维护的 hex 样本清单，每种遥测一行（或一组）原始帧 |
| `assets/data/tm_golden_cases.json` | 回归对照：一种类型一个对象，含 `kind`、`hex`、`result` |
| `_gen_tm_golden.py` | **仅在解析代码确认正确时**运行，根据 txt 重新生成 json |
| `test_tm_golden_parse.py` | pytest：解析 json 里的 `hex`，与同对象的 `result` 对比 |

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
python -m pytest tests/test_tm_golden_parse.py
```

`遥测数据.txt` 里每一条 hex 都必须出现在 json 的某个类型对象中。

公式算出的 `inf` / `nan` 在 json 里写成 `null`（标准 JSON 没有 Infinity）。
