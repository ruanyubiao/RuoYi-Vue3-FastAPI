"""透传组装器：输入即完整载荷。"""

from __future__ import annotations

from module_payload.assemblers.base import AssembledPayload, BaseAssembler
from module_payload.constants import ASSEMBLER_PASSTHROUGH


class PassthroughAssembler(BaseAssembler):
    """不做组帧：每个 chunk 原样产出一条载荷。"""

    ASSEMBLER_ID = ASSEMBLER_PASSTHROUGH

    def feed(self, chunk: bytes) -> list[AssembledPayload]:
        """空缓冲忽略；非空则整段透传。"""
        if not chunk:
            return []
        return [AssembledPayload(data=chunk, meta={'assemblerId': self.ASSEMBLER_ID})]

    def reset(self) -> None:
        """无状态，无需清理。"""
        return
