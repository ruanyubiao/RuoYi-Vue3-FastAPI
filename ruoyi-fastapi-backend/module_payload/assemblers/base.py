"""组装器公共类型与基类。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AssembledPayload:
    """组装完成的一条业务载荷。"""

    data: bytes
    meta: dict[str, Any] = field(default_factory=dict)


class BaseAssembler:
    """组装器接口：有状态，按设备实例持有。"""

    ASSEMBLER_ID = ''

    def feed(self, chunk: bytes) -> list[AssembledPayload]:
        raise NotImplementedError

    def reset(self) -> None:
        """丢弃未完成拼装状态。"""
