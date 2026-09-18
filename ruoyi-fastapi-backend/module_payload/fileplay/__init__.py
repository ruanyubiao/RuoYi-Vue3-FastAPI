"""历史文件回放（fileplay）。

与实时遥测隔离：禁止 ``payload:tm:*``。历史文件数据 / 历史文件曲线各一个进程、一套 Redis：

    payload:fileplay:{history|curve}:meta      当前会话 JSON（在文件 Hash 外面）
    payload:fileplay:{history|curve}:worker    子进程心跳
    payload:fileplay:{history|curve}:ctrl      控制队列
    payload:fileplay:history:{hash}            帧 Hash，字段为序号
    payload:fileplay:curve:{hash}:{fieldId}    点列 Hash，字段为万点块序号

数据流：
    前端带 channel → API parse → FilePlayManager.instance(channel) LPUSH ctrl
    → 该频道 worker BRPOP → FilePlayEngine 拆帧 → 只写本频道 Hash / meta。
    切文件只 DEL 本频道旧 Hash，不能删另一频道正在用的曲线或表格数据。
"""
