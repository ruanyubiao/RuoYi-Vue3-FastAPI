"""
采集进程基类骨架。

统一骨架：初始化 → 循环读取 → 就地解析 → 写 Redis → 监听并执行指令 → 心跳/状态上报。
采集进程为独立操作系统进程，通过 Redis 与主进程通信（见 doc/02-数据采集层设计.md）。

注意：本文件为 P0 阶段骨架，硬件相关库（gpcan / pyserial）均在子类内 **延迟导入**，
避免主进程在未安装这些库时导入失败。
"""

from __future__ import annotations

import abc
import time
from typing import Any


class BaseCollector(abc.ABC):
    """采集进程基类。子类实现 setup/read_and_parse/execute_command/teardown。"""

    def __init__(self, device_id: str, config: dict[str, Any]) -> None:
        self.device_id = device_id
        self.config = config
        self._running = False
        self._redis = None  # 由 run() 内建立(同步 redis 客户端)

    # ------------------------------------------------------------- 生命周期
    @abc.abstractmethod
    def setup(self) -> bool:
        """初始化设备。成功返回 True。"""

    @abc.abstractmethod
    def read_and_parse(self) -> None:
        """读取原始数据并就地解析，写入 Redis 实时数据/曲线。"""

    @abc.abstractmethod
    def execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        """执行一条下发指令，返回执行结果(JSON 可序列化)。"""

    @abc.abstractmethod
    def teardown(self) -> None:
        """关闭设备、释放资源。"""

    # ------------------------------------------------------------- 主循环
    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        """进程入口：建立 Redis 连接，执行骨架主循环。"""
        # TODO(P1): 建立同步 redis 客户端；读取 .env 配置
        if not self.setup():
            # TODO(P1): 写错误状态到 status_key(device_id) 并退出
            return
        self._running = True
        try:
            while self._running:
                self.read_and_parse()
                self._consume_commands()
                self._heartbeat()
                time.sleep(self.config.get('loop_interval_s', 0.01))
        finally:
            self.teardown()

    # ------------------------------------------------------------- 内部
    def _consume_commands(self) -> None:
        """从 Redis 指令队列取出指令并执行，回写结果与历史。"""
        # TODO(P1): BRPOP cmd_queue_key -> execute_command -> SET cmd_result_key / LPUSH history_key

    def _heartbeat(self) -> None:
        """更新心跳与状态。"""
        # TODO(P1): SET heartbeat_key=now EX ttl; 周期更新 status_key
