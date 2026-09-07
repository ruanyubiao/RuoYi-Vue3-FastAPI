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

黄金对照 ``tm_golden_cases.json`` 在 `assets/data/`（后端模拟页也会读，需打包）。
人工 hex 清单与其它**仅测试用**样本放在 `tests/data/`。

| 文件 | 作用 |
|------|------|
| `tests/data/遥测数据.txt` | 人工维护的 hex 样本清单，每种遥测一行（或一组）原始帧 |
| `tests/data/camera_ctrl_serial_COM4_*_recv.bin` | 历史文件回放：相机 **v1.6** 控制串口实采（混有 D8/D9） |
| `tests/data/biu_can_a_can_*_recv.txt` | 历史文件回放：BIU CAN 实采（FF/FD/FB/F9/F7/FE/FC） |
| `tests/data/payload_tm_frame.sql` | MySQL 归档导出（BIU 实采行）：供 canplay open/get_frame 回归 |
| `assets/data/tm_golden_cases.json` | 回归对照（亦供后端模拟页）：含 `kind`、`hex`、`result` |
| `_gen_tm_golden.py` | **仅在解析代码确认正确时**运行，根据 txt 重新生成 json |
| `test_tm_golden_parse.py` | pytest：解析 json 里的 `hex`，与同对象的 `result` 对比 |
| `test_fileplay_camera_recv_regression.py` | 相机 recv.bin → fileplay 索引/真实解析 |
| `test_fileplay_biu_can_recv_regression.py` | BIU CAN recv.txt → 多表类型索引/真实解析 |
| `test_canplay_archive_regression.py` | canplay：SQL 归档行 → open 计数 + raw_hex 真解析 |
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
python -m pytest tests/test_tm_golden_parse.py
```

`遥测数据.txt` 里每一条 hex 都必须出现在 json 的某个类型对象中。

公式算出的 `inf` / `nan` 在 json 里写成 `null`（标准 JSON 没有 Infinity）。
