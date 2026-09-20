"""历史文件回放（fileplay）。

与实时遥测隔离：禁止 ``payload:tm:*``。历史文件数据 / 历史文件曲线按 pathHash 隔离：

    payload:play:file:{history|curve}:{hash}:meta     该文件会话 JSON
    payload:play:file:{history|curve}:{hash}:worker   该文件子进程心跳
    payload:play:file:{history|curve}:{hash}:ctrl     该文件控制队列
    payload:play:file:{history|curve}:{hash}:touch    最后访问 unix 秒
    payload:play:file:{history|curve}:{hash}:data     history=帧 Hash；curve=万帧压缩块 Hash

数据流：
    前端带 channel → API parse → FilePlayManager 按 hash 最多 5 个子进程 LPUSH ctrl
    → 该文件 worker BRPOP → FilePlayEngine 拆帧 → 只写本 hash。
    完成后进程退出；1 小时无访问由 janitor 清 Redis。
"""
