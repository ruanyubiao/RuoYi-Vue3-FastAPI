"""数据组装器注册表：将拆分包还原为完整载荷，再交给解释器。

与硬件解耦；默认 passthrough。各组装器实现分文件维护。
CAN-BIU / CAN-XL 仅用于 CAN 连接。
"""

from __future__ import annotations

from module_payload.assemblers.base import AssembledPayload, BaseAssembler
from module_payload.assemblers.camera_image_d6 import CameraImageD6Assembler
from module_payload.assemblers.can_protocol import CanBiuAssembler, CanXlAssembler
from module_payload.assemblers.eng_tm_subpkt import EngTmSubpktAssembler
from module_payload.assemblers.passthrough import PassthroughAssembler
from module_payload.constants import (
    ASSEMBLER_CAMERA_IMAGE_D6,
    ASSEMBLER_CAN_BIU,
    ASSEMBLER_CAN_XL,
    ASSEMBLER_ENG_TM_SUBPKT,
    ASSEMBLER_PASSTHROUGH,
    CAN_ONLY_ASSEMBLERS,
    SRC_KIND_CAN,
)

__all__ = [
    'AssembledPayload',
    'BaseAssembler',
    'PassthroughAssembler',
    'EngTmSubpktAssembler',
    'CameraImageD6Assembler',
    'CanBiuAssembler',
    'CanXlAssembler',
    'normalize_assembler_id',
    'resolve_assembler_cls',
    'create_assembler',
    'list_assemblers',
    'validate_assembler_for_src',
]

_ASSEMBLER_TYPES: dict[str, type[BaseAssembler]] = {
    ASSEMBLER_PASSTHROUGH: PassthroughAssembler,
    '': PassthroughAssembler,
    ASSEMBLER_ENG_TM_SUBPKT: EngTmSubpktAssembler,
    ASSEMBLER_CAMERA_IMAGE_D6: CameraImageD6Assembler,
    ASSEMBLER_CAN_BIU: CanBiuAssembler,
    ASSEMBLER_CAN_XL: CanXlAssembler,
}


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
        raise ValueError('CAN 连接仅支持 透传 / CAN-BIU / CAN-XL')
    return aid


def list_assemblers(*, src_kind: str | None = None) -> list[dict[str, str]]:
    """列出组装器；src_kind=can 时返回透传+CAN-BIU/CAN-XL，其它连接排除 CAN 专属。"""
    can_passthrough = {
        'id': ASSEMBLER_PASSTHROUGH,
        'name': '透传',
        'desc': '不做协议组帧；CanProtocolClient 协议类型 NONE（便于 CAN 裸测）',
        'srcKind': 'can',
    }
    can_items = [
        can_passthrough,
        {
            'id': ASSEMBLER_CAN_BIU,
            'name': 'CAN-BIU',
            'desc': 'gpcan BIU 协议组帧（仅 CAN）',
            'srcKind': 'can',
        },
        {
            'id': ASSEMBLER_CAN_XL,
            'name': 'CAN-XL',
            'desc': 'gpcan XL 协议组帧（仅 CAN）',
            'srcKind': 'can',
        },
    ]
    general = [
        {
            'id': ASSEMBLER_PASSTHROUGH,
            'name': '透传（默认）',
            'desc': '每次收到的数据视为完整载荷',
        },
        {
            'id': ASSEMBLER_ENG_TM_SUBPKT,
            'name': '工程遥测子包(LVDS)',
            'desc': '0x1ACF 子包拼装；单绑定时内置定头定长定尾拆帧，demux 路径用 accept_frame',
        },
        {
            'id': ASSEMBLER_CAMERA_IMAGE_D6,
            'name': '相机图像(D6)',
            'desc': '接收完整 D6 应答帧按序号拼图（粘包拆帧由 camera_image 插件完成）',
        },
    ]
    kind = (src_kind or '').strip().lower()
    if kind == SRC_KIND_CAN:
        return can_items
    if kind:
        return general
    # 无筛选：全部（含 CAN 专属），供调试页等使用
    return general + [
        {
            'id': ASSEMBLER_CAN_BIU,
            'name': 'CAN-BIU',
            'desc': 'gpcan BIU 协议组帧（仅 CAN）',
            'srcKind': 'can',
        },
        {
            'id': ASSEMBLER_CAN_XL,
            'name': 'CAN-XL',
            'desc': 'gpcan XL 协议组帧（仅 CAN）',
            'srcKind': 'can',
        },
    ]
