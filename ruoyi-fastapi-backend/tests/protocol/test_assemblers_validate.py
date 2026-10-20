"""组装器校验：CAN 专属、字节透传、CAN ProtocolParser feed 字节路径。"""

from __future__ import annotations

import pytest

from module_payload.protocol.registry import (
    create_assembler,
    list_assemblers,
    resolve_assembler_cls,
    validate_assembler_for_src,
)
from module_payload.constants import (
    ASSEMBLER_CAMERA_IMAGE_D6,
    ASSEMBLER_ENG_TM_SUBPKT,
    ASSEMBLER_PASSTHROUGH,
    SRC_KIND_CAN,
)
from module_payload.protocol.protocol_catalog import CAN_BUS_FAMILIES, bus_assembler_id

_BUS_ASSEMBLERS = {row.assembler_id for row in CAN_BUS_FAMILIES}


def test_validate_assembler_for_src_matrix() -> None:
    assert validate_assembler_for_src(None, 'serial') == ASSEMBLER_PASSTHROUGH
    assert validate_assembler_for_src(ASSEMBLER_ENG_TM_SUBPKT, 'udp') == ASSEMBLER_ENG_TM_SUBPKT
    assert validate_assembler_for_src(ASSEMBLER_CAMERA_IMAGE_D6, 'serial') == ASSEMBLER_CAMERA_IMAGE_D6
    assert validate_assembler_for_src(bus_assembler_id('xl'), SRC_KIND_CAN) == bus_assembler_id('xl')
    with pytest.raises(ValueError, match='未知'):
        validate_assembler_for_src('ghost')
    with pytest.raises(ValueError, match='仅可用于 CAN'):
        validate_assembler_for_src(bus_assembler_id('biu'), 'udp')
    with pytest.raises(ValueError, match='仅支持'):
        validate_assembler_for_src(ASSEMBLER_CAMERA_IMAGE_D6, SRC_KIND_CAN)


def test_list_assemblers_filtered() -> None:
    can_ids = {a['id'] for a in list_assemblers(src_kind='can')}
    assert can_ids == {ASSEMBLER_PASSTHROUGH} | _BUS_ASSEMBLERS
    serial_ids = {a['id'] for a in list_assemblers(src_kind='serial')}
    assert not _BUS_ASSEMBLERS & serial_ids
    assert ASSEMBLER_ENG_TM_SUBPKT in serial_ids
    all_ids = {a['id'] for a in list_assemblers()}
    assert _BUS_ASSEMBLERS <= all_ids


@pytest.mark.parametrize('row', CAN_BUS_FAMILIES, ids=lambda r: r.family)
def test_can_assembler_byte_feed_passthrough(row) -> None:
    asm = resolve_assembler_cls(row.assembler_id)()
    assert asm.ASSEMBLER_ID == row.assembler_id
    assert asm.feed(b'') == []
    out = asm.feed(b'\x01\x02')
    assert len(out) == 1
    assert out[0].data == b'\x01\x02'
    assert out[0].meta['canProtocol'] == row.family
    assert asm.feed_frames([]) == []
    asm.reset()
    assert asm.take_errors() == []


def test_create_unknown() -> None:
    with pytest.raises(ValueError, match='未知'):
        create_assembler('nope')
