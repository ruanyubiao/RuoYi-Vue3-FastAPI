# 后端 tests

在 `ruoyi-fastapi-backend` 目录执行：

```text
python -m pytest tests
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
