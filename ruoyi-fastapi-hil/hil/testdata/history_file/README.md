# 历史文件回放 HIL 样本

- `history_file_raw.zip`：各遥测下拉表对应的 raw/sim/generated 样本（git 可跟踪）
- `manifest.json`：表 key → 文件名映射；`skipped` 为无法产出合格帧的表
- 运行时：fixture **删除 data/ → 解压 zip → 用完再删 data/**

## 命名规则

样本基名与界面遥测下拉前缀一致：

```text
{FAMILY}-{localKey}-HIL.{bin|txt}
```

- `FAMILY`：`merge_telemetry_pages` 的 `family` 大写（`xl`→`XL`，`biu`→`BIU`，`yj216`→`YJ216`）
- `localKey`：同页配置本地表键（如 `RKDJ`、`FF`、`LCWP20`）
- 扩展名：CAN 表优先 `.txt`（hex），其余 `.bin`
- 示例：`XL-RKDJ-HIL.bin`、`BIU-FF-HIL.txt`、`YJ216-LCWP20-HIL.bin`
- **不再**使用 `{TABLE}__{source_prefix}__hil_sample`；来源信息只写在 manifest 的 `source` / `source_prefix` / `source_rel` 等字段
- 曲线深测样本（当前 `D8V17`）在此前缀后追加 `_YYYYMMDD_HHMMSS_mmm`，例如 `XL-D8V17-HIL_20260917_172122_191.bin`，供 fileplay 解析 X 轴起点
- 曲线区间滑块按 10000 帧一块；该样本帧数必须大于一块，滑块才有后续 chunk 序号
- 生成的 RS422 字段若枚举里有「正常」，造数时用该码值（见 `prepare_history_file_data.py`）。已入库的 zip 要等下次在有 raw 日志的机器上重跑脚本才会换成新字节

## 重新生成

在仓库根或本目录，保证能 import 后端包，例如：

```powershell
$env:PYTHONPATH = "E:\plat\PayloadGroundTest\ruoyi-fastapi-backend"
python E:\plat\PayloadGroundTest\ruoyi-fastapi-hil\hil\testdata\history_file\prepare_history_file_data.py
```

每表经 `index_file` 帧数 >= 1000（不足则整文件重复拼接）；`manifest.min_frames` / `copies` / `frame_count_sample` 记录来源与倍率。

表 key（`RKDJ`、`BIU:FF` 等）保持不变，仅改样本文件名。
