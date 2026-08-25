"""组装器校验：CAN 专属、字节透传、CAN ProtocolParser feed 字节路径。"""

from __future__ import annotations

import pytest

from module_payload.assemblers import (
    create_assembler,
    list_assemblers,
    validate_assembler_for_src,
)
from module_payload.assemblers.can_protocol import CanBiuAssembler, CanXlAssembler
from module_payload.constants import (
    ASSEMBLER_CAMERA_IMAGE_D6,
    ASSEMBLER_CAN_BIU,
    ASSEMBLER_CAN_XL,
    ASSEMBLER_ENG_TM_SUBPKT,
    ASSEMBLER_PASSTHROUGH,
    SRC_KIND_CAN,
)


def test_validate_assembler_for_src_matrix() -> None:
    assert validate_assembler_for_src(None, 'serial') == ASSEMBLER_PASSTHROUGH
    assert validate_assembler_for_src(ASSEMBLER_ENG_TM_SUBPKT, 'udp') == ASSEMBLER_ENG_TM_SUBPKT
    assert validate_assembler_for_src(ASSEMBLER_CAMERA_IMAGE_D6, 'serial') == ASSEMBLER_CAMERA_IMAGE_D6
    assert validate_assembler_for_src(ASSEMBLER_CAN_XL, SRC_KIND_CAN) == ASSEMBLER_CAN_XL
    with pytest.raises(ValueError, match='未知'):
        validate_assembler_for_src('ghost')
    with pytest.raises(ValueError, match='仅可用于 CAN'):
        validate_assembler_for_src(ASSEMBLER_CAN_BIU, 'udp')
    with pytest.raises(ValueError, match='仅支持'):
        validate_assembler_for_src(ASSEMBLER_CAMERA_IMAGE_D6, SRC_KIND_CAN)


def test_list_assemblers_filtered() -> None:
    can_ids = {a['id'] for a in list_assemblers(src_kind='can')}
    assert can_ids == {ASSEMBLER_PASSTHROUGH, ASSEMBLER_CAN_BIU, ASSEMBLER_CAN_XL}
    serial_ids = {a['id'] for a in list_assemblers(src_kind='serial')}
    assert ASSEMBLER_CAN_BIU not in serial_ids
    assert ASSEMBLER_ENG_TM_SUBPKT in serial_ids
    all_ids = {a['id'] for a in list_assemblers()}
    assert ASSEMBLER_CAN_XL in all_ids


def test_can_assembler_byte_feed_passthrough() -> None:
    for cls in (CanBiuAssembler, CanXlAssembler):
        asm = cls()
        assert asm.feed(b'') == []
        out = asm.feed(b'\x01\x02')
        assert len(out) == 1
        assert out[0].data == b'\x01\x02'
        assert out[0].meta['canProtocol'] in ('biu', 'xl')
        assert asm.feed_frames([]) == []
        asm.reset()
        assert asm.take_errors() == []


def test_create_unknown() -> None:
    with pytest.raises(ValueError, match='未知'):
        create_assembler('nope')
