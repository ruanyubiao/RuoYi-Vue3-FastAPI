"""
采集进程生命周期管理器骨架。

由主进程持有，负责采集子进程的启动、停止、健康检查与回收：
- CAN：按「卡」聚合 + 通道引用计数（同卡多通道共用进程，全部关闭才回收）；
- 串口/网络：打开开进程，关闭关进程。

实现要点见 doc/02-数据采集层设计.md。本文件为 P0 阶段骨架。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProcessEntry:
    """进程注册表项。"""

    device_id: str
    process: Any = None  # multiprocessing.Process
    opened_channels: set[int] = field(default_factory=set)  # 仅 CAN 使用
    status: str = 'stopped'


class CollectorProcessManager:
    """采集进程管理器（单例，由主进程使用）。"""

    _instance: 'CollectorProcessManager | None' = None

    def __init__(self) -> None:
        self._registry: dict[str, ProcessEntry] = {}

    @classmethod
    def instance(cls) -> 'CollectorProcessManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # --------------------------------------------------------------- CAN
    def open_can_channel(self, vendor: int, dev_index: int, can_index: int, config: dict[str, Any]) -> str:
        """打开 CAN 通道：卡进程已存在则追加通道，否则新建进程。返回 device_id。"""
        # TODO(P1): 按 can_card_id 聚合；不存在则 spawn CanCollector.run；存在则向其追加通道
        raise NotImplementedError('open_can_channel 待 P1 实现')

    def close_can_channel(self, vendor: int, dev_index: int, can_index: int) -> None:
        """关闭 CAN 通道：卡上全部通道关闭后回收进程。"""
        # TODO(P1): 引用计数；归零则终止并回收进程
        raise NotImplementedError('close_can_channel 待 P1 实现')

    # --------------------------------------------------------- 串口 / 网络
    def start(self, device_id: str, collector_type: str, config: dict[str, Any]) -> None:
        """启动串口/网络采集进程。"""
        # TODO(P4/P5): spawn 对应 Collector.run
        raise NotImplementedError('start 待后续实现')

    def stop(self, device_id: str) -> None:
        """停止并回收指定采集进程。"""
        # TODO: terminate + join + 清理注册表
        raise NotImplementedError('stop 待后续实现')

    # --------------------------------------------------------------- 监控
    def health_check(self) -> None:
        """基于 Redis 心跳检查进程存活，必要时重启。"""
        # TODO: 遍历注册表，心跳过期则重启
        ...

    def shutdown_all(self) -> None:
        """主进程退出时统一回收所有采集进程。"""
        for device_id in list(self._registry.keys()):
            try:
                self.stop(device_id)
            except NotImplementedError:
                pass
