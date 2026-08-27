"""历史文件回放（fileplay）。

与实时遥测隔离：解析结果只写 ``payload:fileplay:{pathHash}``，禁止 ``payload:tm:*``。

字段解析与硬件采集同一套 ingest（如 XlBoardTmIngest.parse_bytes），
不另写拆帧/TeleMetryCfg 逻辑；差别只在入口与落库键。

数据流：
    前端选表 + 文件 → API parse → FilePlayManager 把命令 LPUSH 到 ``payload:fileplay:ctrl``
    → worker 子进程 BRPOP → FilePlayEngine 拆帧/解析第 1 帧 → Hash.meta + Hash.f:1
    → API 轮询 meta.status=ready 后把第 1 帧和 frameCount 返回前端。

大文件：默认先按「文件大小/首帧长」预估 frameCount 并立刻 ready，后台线程精确扫帧后
覆盖同一 meta，避免主进程空等 60s 超时。取尚未扫到的帧时前端提示稍后重试。
"""
