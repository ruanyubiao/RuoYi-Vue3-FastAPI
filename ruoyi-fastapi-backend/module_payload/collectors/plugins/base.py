"""串口收流插件接口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SerialPluginContext:
    """插件访问串口与 Redis 的窄接口，避免直接依赖 SerialCollector 实现细节。"""

    device_id: str
    redis: Any
    config: dict[str, Any]
    is_running: Any  # () -> bool
    read_serial: Any  # (n: int | None) -> bytes
    write_serial: Any  # (data: bytes) -> None
    in_waiting: Any  # () -> int
    reset_input_buffer: Any  # () -> None
    push_io: Any  # (direction: str, data: bytes) -> None
    write_status: Any  # (state: str, message: str) -> None
    poll_control: Any = None  # () -> None，长任务中可打断


@dataclass
class TickResult:
    """插件每轮调度结果。"""

    # True：本轮由插件接管读写，采集器不再走默认 read→ingest
    owns_loop: bool = False


@dataclass
class FilterResult:
    """被动收数后的过滤结果。"""

    # 仍需交给会话 ingest（组装器/解释器）的数据；空表示不透传
    passthrough: bytes = b''
    # True：本插件已消费，后续不再透传（即使 passthrough 非空也以 consume 为准时用 passthrough）
    consume: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


class SerialStreamPlugin(Protocol):
    """串口流插件。

    - 主动型（如图像拉流）：tick() 返回 owns_loop=True，自行读写串口。
    - 被动型：tick() 不接管；在 filter_rx 中处理默认读到的数据，决定是否透传。
    """

    plugin_id: str

    def on_attach(self, ctx: SerialPluginContext) -> None: ...

    def on_detach(self) -> None: ...

    def handle_control(self, msg: dict[str, Any]) -> bool:
        """处理控制消息；返回 True 表示已消费。"""
        ...

    def tick(self, ctx: SerialPluginContext) -> TickResult: ...

    def filter_rx(self, ctx: SerialPluginContext, data: bytes) -> FilterResult: ...

    def reset_rx(self) -> None:
        """可选：硬件 RX 被丢弃时清空插件组帧缓存。"""
        ...
