# hil/repro_scripts — 专项复现 / 诊断脚本

## 约定

- **放这里**：为单一排查目的写的、非正式 pytest 套件的专项脚本（复现率统计、幽灵占用、一次性诊断等）。
- **不放这里**：正式 HIL 用例（仍在 `scenarios/`）、公共库（`hil/browser/`、`hil/ipc_api.py` 等）、`run_hil.bat` / `conftest` 驱动的回归入口。
- 新增同类脚本时：本目录新增 `.py`，在本 README 增加一小节「脚本名 + 测什么 + 一行命令」；文件头注释写清目的、约束、产物路径。
- 默认 **不** 纳入 `run_hil.bat all`；需显式 `python -m hil.repro_scripts.<模块名> ...`。

## 当前脚本

### `ghost_busy_repro.py` — can_xl 幽灵占用短窗口

**测什么**：网页开 XL CAN → 发长遥控（默认 D1651）→ 网页关 CAN 后**立刻**读 `busy_can`，再 `ensure_hardware_idle` 后再读。量化「关后立刻」vs「idle 后」的 `assembler=can_xl` 残留率。

**依赖**：与正式 HIL 相同（Playwright、DUT、`hil.local.json` CAN 映射、有头浏览器）。会真实占用采集机 CAN，勿并行抢同一机。

**命令**（工作目录为 `ruoyi-fastapi-hil` 根，`PYTHONPATH` 含根目录）：

```bat
set PYTHONPATH=%CD%
python -m hil.repro_scripts.ghost_busy_repro --rounds 40
python -m hil.repro_scripts.ghost_busy_repro --rounds 40 --order D1651
```

**产物**：`artifacts/can_xl_ghost_busy_<yyyyMMdd_HHmmss>/`（`REPRO.md`、`rounds.jsonl`、`meta.json`）。

更细背景与约束见该文件**文件开头模块 docstring**。
