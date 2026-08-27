"""采集/解释器依赖的 Redis 旁路契约；默认实现见同目录各 store 模块。

运行时不必注入实例，函数即满足这些 Protocol，单测可 Fake。
"""

from __future__ import annotations

from typing import Any, Protocol


class ErrorSink(Protocol):
    """流水线错误写入 Redis List + latest。"""

    def __call__(
        self,
        redis_client: Any,
        *,
        stage: str,
        message: str,
        device_id: str = '',
        assembler_id: str | None = None,
        parser_id: str | None = None,
        data_len: int | None = None,
    ) -> None: ...


class SessionReader(Protocol):
    """同步读设备会话（采集热路径只用 GET）。"""

    def get_sync(
        self, redis_client: Any, src_param: str, src_kind: str | None = None
    ) -> dict[str, Any] | None: ...


class ArchiveQueue(Protocol):
    """遥测归档 Redis 队列（不含 MySQL worker）。"""

    def enqueue_sync(self, redis_client: Any, event: dict[str, Any]) -> None: ...

    async def enqueue(self, redis: Any, event: dict[str, Any]) -> None: ...
