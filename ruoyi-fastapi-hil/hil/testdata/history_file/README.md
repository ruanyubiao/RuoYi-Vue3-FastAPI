# 历史文件回放 HIL 样本

- history_file_raw.zip：按遥测表挑选的 raw 片段（git 管理）
- manifest.json：表键 ↔ 文件名映射；skipped 为 raw 中找不到合格帧的表
- 运行时由 fixture **删旧 data/ → 解压 zip → 测完删 data/**

命名：{表键}__{source前缀}__hil_sample.{bin|txt}，与采集落盘 {source}_{serial|can|udp}_…_recv 对应。

重新生成：在设置 PYTHONPATH=ruoyi-fastapi-backend 后执行 prepare_history_file_data.py。

每表样本 index_file 帧数 >= 1000（不足则整文件重复拼接）；manifest.min_frames / copies / frame_count_sample 记录来源与倍数。
