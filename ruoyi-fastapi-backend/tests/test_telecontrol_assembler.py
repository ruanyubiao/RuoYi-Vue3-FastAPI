"""遥控组件编码：公式在组帧时计算，values 存的是控件原值。"""

from __future__ import annotations

import struct

import pytest

from module_payload.cfg.telecontrol_assembler import (
    apply_component_formula,
    assemble_order,
    calc_checksum,
    encode_component,
    encode_number,
    hex_to_bytes,
    is_broadcast_hex,
)


def test_hex_to_bytes_strips_0x_and_spaces() -> None:
    assert hex_to_bytes('0xEB 90') == bytes([0xEB, 0x90])
    assert hex_to_bytes('eb9') == bytes([0x0E, 0xB9])
    assert hex_to_bytes('') == b''


def test_encode_number_all_widths() -> None:
    assert encode_number(-1, 'INT8') == struct.pack('>b', -1)
    assert encode_number(255, 'UINT8') == b'\xff'
    assert encode_number(-2, 'INT16') == struct.pack('>h', -2)
    assert encode_number(0xABCD, 'UINT16') == b'\xab\xcd'
    assert encode_number(-1, 'INT24') == b'\xff\xff\xff'
    assert encode_number(0x010203, 'UINT24') == b'\x01\x02\x03'
    assert encode_number(-3, 'INT32') == struct.pack('>i', -3)
    assert encode_number(0xAABBCCDD, 'UINT32') == b'\xaa\xbb\xcc\xdd'
    assert encode_number(1.5, 'FLOAT') == struct.pack('>f', 1.5)
    assert encode_number(2.5, 'DOUBLE') == struct.pack('>d', 2.5)
    assert encode_number(None, 'INT16') == struct.pack('>h', 0)


def test_formula_uses_ui_value_as_d() -> None:
    """序列/界面存 1.5，组帧时才 D*100000 → 150000。"""
    assert apply_component_formula(1.5, '') == 1.5
    assert apply_component_formula(1.5, '   ') == 1.5
    out = apply_component_formula(1.5, 'D*100000')
    assert int(out) == 150000


def test_formula_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match='不是数值'):
        apply_component_formula('abc', 'D+1')


def test_number_component_applies_formula_before_pack() -> None:
    comp = {'componentType': 'number', 'dataType': 'INT32', 'formula': 'D*100000'}
    raw = encode_component(comp, 1.5)
    assert raw == struct.pack('>i', 150000)


def test_select_maps_label_to_option_key() -> None:
    comp = {
        'componentType': 'select',
        'defaultVal': '0xAA',
        'options': {'0xAA': '方位', '0xBB': '俯仰'},
    }
    assert encode_component(comp, '方位') == bytes([0xAA])
    assert encode_component(comp, '0xBB') == bytes([0xBB])
    assert encode_component(comp, None) == b'\x00'


def test_hex_component_zfill_to_default_width() -> None:
    comp = {'componentType': 'hex', 'defaultVal': '0000'}
    assert encode_component(comp, 'AB') == bytes([0x00, 0xAB])


def test_scientific_float_and_double() -> None:
    fcomp = {'componentType': 'scientific', 'dataType': 'FLOAT'}
    dcomp = {'componentType': 'scientific', 'dataType': 'DOUBLE'}
    assert encode_component(fcomp, 1.0) == struct.pack('>f', 1.0)
    assert encode_component(dcomp, 1.0) == struct.pack('>d', 1.0)


def test_fixed_ignores_value() -> None:
    comp = {'componentType': 'fixed', 'defaultVal': '0xEB90'}
    assert encode_component(comp, 'ignored') == bytes([0xEB, 0x90])


def test_assemble_order_8byte_single_and_broadcast() -> None:
    comps = [
        {'componentType': 'fixed', 'defaultVal': '30'},
        {'componentType': 'fixed', 'defaultVal': '00'},
        {'componentType': 'fixed', 'defaultVal': '00'},
        {'componentType': 'fixed', 'defaultVal': '00'},
        {'componentType': 'fixed', 'defaultVal': '00'},
        {'componentType': 'fixed', 'defaultVal': '00'},
        {'componentType': 'fixed', 'defaultVal': '00'},
        {'componentType': 'fixed', 'defaultVal': '00'},
    ]
    result = assemble_order(comps, [])
    assert result['length'] == 8
    assert result['frameType'] == 0x30
    assert result['isBroadcast'] is True
    assert result['allChannel'] is True
    assert is_broadcast_hex(result['hex']) is True


def test_is_broadcast_hex_short_or_garbage() -> None:
    assert is_broadcast_hex('') is False
    assert is_broadcast_hex('AA BB') is False
    assert is_broadcast_hex('not-hex') is False


def test_complex_frame_appends_checksum() -> None:
    # 长度>8 时 frameType 取 buf[2]；len == dataLen+2 时补校验和
    data_len = 7  # type + 6 body
    buf_no_chk = bytes([(data_len >> 8) & 0xFF, data_len & 0xFF, 0x0F, 1, 2, 3, 4, 5, 6])
    comps = [{'componentType': 'fixed', 'defaultVal': buf_no_chk.hex()}]
    result = assemble_order(comps, [])
    raw = bytes.fromhex(result['hex'].replace(' ', ''))
    assert len(raw) == 10
    assert raw[-1] == calc_checksum(buf_no_chk)
    assert result['frameType'] == 0x0F
