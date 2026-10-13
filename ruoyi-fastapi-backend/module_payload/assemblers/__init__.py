"""数据组装器注册表：将拆分包还原为完整载荷，再交给解释器。

与硬件解耦；默认 passthrough。各组装器实现分文件维护。
CAN-BIU / CAN-XL 仅用于 CAN 连接。
"""

from __future__ import annotations

from module_payload.assemblers.base import AssembledPayload, BaseAssembler
from module_payload.assemblers.camera_image_d6 import CameraImageD6Assembler
from module_payload.assemblers.camera_image_d6_v17 import CameraImageD6V17Assembler
from module_payload.assemblers.can_protocol import CanBiuAssembler, CanXlAssembler, CanYj216Assembler
from module_payload.assemblers.eng_tm_subpkt import EngTmSubpktAssembler
from module_payload.assemblers.passthrough import PassthroughAssembler
from module_payload.constants import (
    ASSEMBLER_CAMERA_IMAGE_D6,
    ASSEMBLER_CAMERA_IMAGE_D6_V17,
    ASSEMBLER_CAN_BIU,
    ASSEMBLER_CAN_XL,
    ASSEMBLER_CAN_YJ216,
    ASSEMBLER_ENG_TM_SUBPKT,
    ASSEMBLER_PASSTHROUGH,
    CAN_ONLY_ASSEMBLERS,
    SRC_KIND_CAN,
)
from module_payload.protocol_catalog import can_only_assembler_message, list_assembler_items

__all__ = [
    'AssembledPayload',
    'BaseAssembler',
    'PassthroughAssembler',
    'EngTmSubpktAssembler',
    'CameraImageD6Assembler',
    'CameraImageD6V17Assembler',
    'CanBiuAssembler',
    'CanXlAssembler',
    'CanYj216Assembler',
    'normalize_assembler_id',
    'resolve_assembler_cls',
    'create_assembler',
    'list_assemblers',
    'validate_assembler_for_src',
    'CAMERA_IMAGE_ASSEMBLER_IDS',
]

_ASSEMBLER_TYPES: dict[str, type[BaseAssembler]] = {
    ASSEMBLER_PASSTHROUGH: PassthroughAssembler,
    '': PassthroughAssembler,
    ASSEMBLER_ENG_TM_SUBPKT: EngTmSubpktAssembler,
    ASSEMBLER_CAMERA_IMAGE_D6: CameraImageD6Assembler,
    ASSEMBLER_CAMERA_IMAGE_D6_V17: CameraImageD6V17Assembler,
    ASSEMBLER_CAN_BIU: CanBiuAssembler,
    ASSEMBLER_CAN_XL: CanXlAssembler,
    ASSEMBLER_CAN_YJ216: CanYj216Assembler,
}

# 相机 D6 拼图器 id 集合（由注册表派生，避免与插件/采集侧重复列举）
CAMERA_IMAGE_ASSEMBLER_IDS = frozenset(
    aid for aid in _ASSEMBLER_TYPES if aid.startswith('camera_image_d6')
)


def normalize_assembler_id(assembler_id: str | None) -> str:
    """空 id 归一成透传。"""
    aid = (assembler_id or '').strip()
    return aid or ASSEMBLER_PASSTHROUGH


def resolve_assembler_cls(assembler_id: str | None) -> type[BaseAssembler] | None:
    """按 id 取组装器类；未知返回 None。"""
    aid = normalize_assembler_id(assembler_id)
    return _ASSEMBLER_TYPES.get(aid)


def create_assembler(assembler_id: str | None = None) -> BaseAssembler:
    """实例化组装器；未知 id 抛 ValueError。"""
    cls = resolve_assembler_cls(assembler_id)
    if cls is None:
        raise ValueError(f'未知组装器: {assembler_id}')
    return cls()


def validate_assembler_for_src(assembler_id: str | None, src_kind: str | None = None) -> str:
    """校验组装器与连接类型是否匹配；返回归一化 id。"""
    aid = normalize_assembler_id(assembler_id)
    if resolve_assembler_cls(aid) is None:
        raise ValueError(f'未知组装器: {assembler_id}')
    kind = (src_kind or '').strip().lower()
    if aid in CAN_ONLY_ASSEMBLERS and kind and kind != SRC_KIND_CAN:
        raise ValueError(f'{aid} 仅可用于 CAN 连接')
    if kind == SRC_KIND_CAN and aid not in CAN_ONLY_ASSEMBLERS and aid != ASSEMBLER_PASSTHROUGH:
        raise ValueError(can_only_assembler_message())
    return aid


def list_assemblers(*, src_kind: str | None = None) -> list[dict[str, str]]:
    """列出组装器。can：透传加各总线族；其它连接只要非总线组装器。"""
    return list_assembler_items(src_kind)
