"""遥控组件编码：公式在组帧时计算，values 存的是控件原值。"""

from __future__ import annotations

import struct

import pytest

from module_payload.cfg.hex_text import hex_to_bytes
from module_payload.protocol.biu.can.tc import assemble as assemble_biu
from module_payload.cfg.telecontrol_assembler import (
    apply_component_formula,
    calc_checksum,
    encode_component,
    encode_number,
    is_broadcast_hex,
)


def test_hex_to_bytes_follows_frontend_token_rule() -> None:
    """公开 HEX 解析与输入框一致：空白分段，不接受 0x。"""
    assert hex_to_bytes('A B') == bytes([0x0A, 0x0B])
    assert hex_to_bytes('eb9') == bytes([0xEB, 0x09])
    assert hex_to_bytes('') == b''
    with pytest.raises(ValueError, match='非法'):
        hex_to_bytes('0xEB 90')


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
    result = assemble_biu({'component': comps}, [])
    assert result['length'] == 8
    assert result['frameType'] == 0x30
    assert result['isBroadcast'] is True
    assert result['allChannel'] is True
    assert is_broadcast_hex(result['hex']) is True


def test_is_broadcast_hex_short_or_garbage() -> None:
    assert is_broadcast_hex('') is False
    assert is_broadcast_hex('AA BB') is False
    assert is_broadcast_hex('not-hex') is False


def _num_item(name: str) -> dict:
    return {
        'name': name,
        'component': [{'title': 'X', 'componentType': 'number', 'dataType': 'INT16'}],
    }


def test_checkboxgroup_mask_and_fixed_slots() -> None:
    """位图大端；选中写槽位，未选中整段为填充字节，尾部保持填充。"""
    comp = {
        'componentType': 'checkboxgroup',
        'dataType': 'INT16',
        'groupDataLength': 8,
        'groupDataDefaultByte': '0x6B',
        'group': [_num_item('A'), _num_item('B')],
    }
    raw = encode_component(comp, {'mask': 1, 'values': [[5], [9]]})
    assert raw[:2] == b'\x00\x01'
    assert raw[2:4] == b'\x00\x05'
    assert raw[4:] == b'\x6b' * 6
    assert len(raw) == 10


def test_checkboxgroup_dynamic_length_and_unsigned_mask() -> None:
    comp = {
        'componentType': 'checkboxgroup',
        'dataType': 'INT16',
        'groupDataLength': -1,
        'group': [_num_item('A'), _num_item('B'), _num_item('C')],
    }
    raw = encode_component(comp, {'mask': 7, 'values': [[1], [2], [3]]})
    assert raw == b'\x00\x07' + b'\x00\x01' + b'\x00\x02' + b'\x00\x03'
    bits = {
        'componentType': 'checkboxgroup',
        'dataType': 'UINT16',
        'groupDataLength': 0,
        'group': [],
    }
    assert encode_component(bits, {'mask': 0}) == b'\x00\x00'


def test_checkboxgroup_high_bits_and_overflow_fail() -> None:
    comp = {
        'componentType': 'checkboxgroup',
        'dataType': 'INT16',
        'groupDataLength': 2,
        'group': [_num_item('A'), _num_item('B')],
    }
    with pytest.raises(ValueError, match='无对应项'):
        encode_component(comp, {'mask': 4})
    with pytest.raises(ValueError, match='超过 groupDataLength'):
        encode_component(comp, {'mask': 1, 'values': [[1], [2]]})
    wide = {
        'componentType': 'checkboxgroup',
        'dataType': 'UINT8',
        'group': [_num_item(str(i)) for i in range(9)],
    }
    with pytest.raises(ValueError, match='超过位图位数'):
        encode_component(wide, {'mask': 0})


def test_checkboxgroup_default_fill_and_nested_rejected() -> None:
    comp = {
        'componentType': 'checkboxgroup',
        'dataType': 'UINT8',
        'groupDataLength': 2,
        'group': [_num_item('A')],
    }
    raw = encode_component(comp, None)
    assert raw == b'\x00' + b'\x00\x00'
    nested = {
        'componentType': 'checkboxgroup',
        'dataType': 'UINT8',
        'group': [{
            'name': '内层',
            'component': [{
                'componentType': 'checkboxgroup',
                'dataType': 'UINT8',
                'group': [],
            }],
        }],
    }
    with pytest.raises(ValueError, match='嵌套'):
        encode_component(nested, {'mask': 1})


@pytest.mark.parametrize(
    ('dtype', 'nbytes'),
    [
        ('INT40', 5),
        ('UINT40', 5),
        ('int48', 6),
        ('UINT48', 6),
        ('INT56', 7),
        ('UINT56', 7),
        ('INT64', 8),
        ('UINT64', 8),
    ],
)
def test_checkboxgroup_mask_width_40_to_64(dtype: str, nbytes: int) -> None:
    """INT40/48/56/64 与对应 UINT 按无符号字节数写位图。"""
    comp = {
        'componentType': 'checkboxgroup',
        'dataType': dtype,
        'groupDataLength': 0,
        'group': [],
    }
    assert encode_component(comp, {'mask': 0}) == b'\x00' * nbytes


def test_checkboxgroup_int64_mask_bit_string() -> None:
    """mask 为等宽 0/1 字符串，左边是高位，最右边是 group[0]。"""
    comp = {
        'componentType': 'checkboxgroup',
        'dataType': 'INT64',
        'groupDataLength': 0,
        'group': [
            {'component': [{'componentType': 'fixed', 'defaultVal': ''}]}
            for _ in range(61)
        ],
    }
    mask = (1 << 60) | 3
    raw = encode_component(comp, {'mask': f'{mask:064b}'})
    assert int.from_bytes(raw, 'big') == mask
    with pytest.raises(ValueError, match='位数'):
        encode_component(comp, {'mask': '0111'})


def test_checkboxgroup_int64_selected_bit0() -> None:
    comp = {
        'componentType': 'checkboxgroup',
        'dataType': 'INT64',
        'groupDataLength': -1,
        'group': [_num_item('A')],
    }
    raw = encode_component(comp, {'mask': 1, 'values': [[1]]})
    assert raw[:8] == b'\x00' * 7 + b'\x01'
    assert raw[8:] == b'\x00\x01'


def test_checkboxgroup_selected_bits_0_1_9_11() -> None:
    comp = {
        'componentType': 'checkboxgroup',
        'dataType': 'INT16',
        'groupDataLength': -1,
        'groupDataDefaultByte': '00',
        'group': [_num_item(str(i)) for i in range(12)],
    }
    raw = encode_component(comp, {'mask': 0x0A03})
    assert raw[:2] == b'\x0A\x03'
    assert len(raw) == 2 + 12 * 2


def test_d1501_checkboxgroup_sample() -> None:
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / 'assets' / 'config' / 'XL-TeleControlCfg.json'
    order = json.loads(path.read_text(encoding='utf-8'))['order']['D1501']
    comp = order['component'][2]
    quiet = encode_component(comp, {'mask': 0, 'values': []})
    assert quiet[:2] == b'\x00\x00'
    assert len(quiet) == 514
    assert quiet[2:] == b'\x6b' * 512
    chosen = encode_component(comp, {'mask': 1, 'values': [[None, None, 1, None, 2]]})
    assert chosen[:2] == b'\x00\x01'
    assert chosen[2:16] == bytes.fromhex('000C0F9288070000000100000002')
    assert chosen[16:30] == b'\x6b' * 14


def test_complex_frame_appends_checksum() -> None:
    # 长度>8 时 frameType 取 buf[2]；len == dataLen+2 时补校验和
    data_len = 7  # type + 6 body
    buf_no_chk = bytes([(data_len >> 8) & 0xFF, data_len & 0xFF, 0x0F, 1, 2, 3, 4, 5, 6])
    comps = [{'componentType': 'fixed', 'defaultVal': buf_no_chk.hex()}]
    result = assemble_biu({'component': comps}, [])
    raw = bytes.fromhex(result['hex'].replace(' ', ''))
    assert len(raw) == 10
    assert raw[-1] == calc_checksum(buf_no_chk)
    assert result['frameType'] == 0x0F
