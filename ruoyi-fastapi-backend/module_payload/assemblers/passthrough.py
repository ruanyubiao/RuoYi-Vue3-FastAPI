"""透传组装器：输入即完整载荷。"""

from __future__ import annotations

from module_payload.assemblers.base import AssembledPayload, BaseAssembler
from module_payload.constants import ASSEMBLER_PASSTHROUGH


class PassthroughAssembler(BaseAssembler):
    ASSEMBLER_ID = ASSEMBLER_PASSTHROUGH

    def feed(self, chunk: bytes) -> list[AssembledPayload]:
        if not chunk:
            return []
        return [AssembledPayload(data=chunk, meta={'assemblerId': self.ASSEMBLER_ID})]

    def reset(self) -> None:
        return
