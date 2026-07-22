"""数据组装器注册表：将拆分包还原为完整载荷，再交给解释器。

与硬件解耦；默认 passthrough。各组装器实现分文件维护。
"""

from __future__ import annotations

from module_payload.assemblers.base import AssembledPayload, BaseAssembler
from module_payload.assemblers.eng_tm_subpkt import EngTmSubpktAssembler
from module_payload.assemblers.passthrough import PassthroughAssembler
from module_payload.constants import ASSEMBLER_ENG_TM_SUBPKT, ASSEMBLER_PASSTHROUGH

__all__ = [
    'AssembledPayload',
    'BaseAssembler',
    'PassthroughAssembler',
    'EngTmSubpktAssembler',
    'normalize_assembler_id',
    'resolve_assembler_cls',
    'create_assembler',
    'list_assemblers',
]

_ASSEMBLER_TYPES: dict[str, type[BaseAssembler]] = {
    ASSEMBLER_PASSTHROUGH: PassthroughAssembler,
    '': PassthroughAssembler,
    ASSEMBLER_ENG_TM_SUBPKT: EngTmSubpktAssembler,
}


def normalize_assembler_id(assembler_id: str | None) -> str:
    aid = (assembler_id or '').strip()
    return aid or ASSEMBLER_PASSTHROUGH


def resolve_assembler_cls(assembler_id: str | None) -> type[BaseAssembler] | None:
    aid = normalize_assembler_id(assembler_id)
    return _ASSEMBLER_TYPES.get(aid)


def create_assembler(assembler_id: str | None = None) -> BaseAssembler:
    cls = resolve_assembler_cls(assembler_id)
    if cls is None:
        raise ValueError(f'未知组装器: {assembler_id}')
    return cls()


def list_assemblers() -> list[dict[str, str]]:
    return [
        {
            'id': ASSEMBLER_PASSTHROUGH,
            'name': '透传（默认）',
            'desc': '每次收到的数据视为完整载荷',
        },
        {
            'id': ASSEMBLER_ENG_TM_SUBPKT,
            'name': '工程遥测子包(LVDS)',
            'desc': '按 0x1ACF 子包帧拼接有效数据（粘包按 1040 拆帧）',
        },
    ]
