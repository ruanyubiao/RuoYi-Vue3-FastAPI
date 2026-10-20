"""HEX 文本：空白分隔 token，奇数位在末半字节前补 0（对齐前端 payloadRawData.js）。"""

from __future__ import annotations

import pytest

from module_payload.cfg.hex_text import hex_to_bytes, normalize_hex_display, parse_hex_config_value
from module_payload.cfg.telecontrol_assembler import encode_component
from module_payload.demux.stream_demux import DemuxRoute


def test_whitespace_splits_tokens() -> None:
    assert hex_to_bytes('A B') == bytes([0x0A, 0x0B])
    assert hex_to_bytes('a b c') == bytes([0x0A, 0x0B, 0x0C])
    assert hex_to_bytes('ab c') == bytes([0xAB, 0x0C])
    assert hex_to_bytes('ab c de f') == bytes([0xAB, 0x0C, 0xDE, 0x0F])
    assert hex_to_bytes('ab c d') == bytes([0xAB, 0x0C, 0x0D])
    assert hex_to_bytes('aabbc') == bytes([0xAA, 0xBB, 0x0C])
    assert hex_to_bytes('aabbc d') == bytes([0xAA, 0xBB, 0x0C, 0x0D])
    assert hex_to_bytes('aabb c d') == bytes([0xAA, 0xBB, 0x0C, 0x0D])
    assert hex_to_bytes('aab ccd d eef 445') == bytes(
        [0xAA, 0x0B, 0xCC, 0x0D, 0x0D, 0xEE, 0x0F, 0x44, 0x05]
    )
    assert hex_to_bytes('11 23 4  44 ff dd ee d') == bytes(
        [0x11, 0x23, 0x04, 0x44, 0xFF, 0xDD, 0xEE, 0x0D]
    )


def test_empty_and_invalid() -> None:
    assert hex_to_bytes('') == b''
    assert hex_to_bytes('   ') == b''
    assert normalize_hex_display('A B') == '0A 0B'
    with pytest.raises(ValueError, match='非法'):
        hex_to_bytes('GG')
    with pytest.raises(ValueError, match='非法'):
        hex_to_bytes('0xEB 90')


def test_parse_hex_config_value_uses_token_rule() -> None:
    """demux 帧头不能把空格当可忽略字符，否则 A B 会变成 AB。"""
    assert parse_hex_config_value('A B') == bytes([0x0A, 0x0B])
    assert parse_hex_config_value('EB 90') == bytes([0xEB, 0x90])
    assert parse_hex_config_value('EB90') == bytes([0xEB, 0x90])
    assert parse_hex_config_value(bytes([0x1B, 0xCF])) == bytes([0x1B, 0xCF])
    with pytest.raises(ValueError, match='不能为空'):
        parse_hex_config_value('', field_name='header')
    with pytest.raises(ValueError, match='非法'):
        parse_hex_config_value('0x1BCF', field_name='header')


def test_demux_route_header_spaced_equals_compact() -> None:
    compact = DemuxRoute.from_dict(
        {
            'id': 'a',
            'framing': 'header_len',
            'header': 'EB90',
            'frameSize': 8,
            'assemblerId': 'passthrough',
        }
    )
    spaced = DemuxRoute.from_dict(
        {
            'id': 'b',
            'framing': 'header_len',
            'header': 'EB 90',
            'frameSize': 8,
            'assemblerId': 'passthrough',
        }
    )
    assert compact.header == spaced.header == bytes([0xEB, 0x90])
    split = DemuxRoute.from_dict(
        {
            'id': 'c',
            'framing': 'header_len',
            'header': 'E B',
            'frameSize': 8,
            'assemblerId': 'passthrough',
        }
    )
    assert split.header == bytes([0x0E, 0x0B])


def test_telecontrol_cfg_0x_prefix_only_when_encoding_components() -> None:
    """输入框 HEX 拒 0x；TeleControlCfg 的 defaultVal 仍带 0x，只在组帧时剥。"""
    with pytest.raises(ValueError, match='非法'):
        hex_to_bytes('0xEB90')
    raw = encode_component({'componentType': 'fixed', 'defaultVal': '0xEB90'})
    assert raw == bytes([0xEB, 0x90])
    assert hex_to_bytes('eb9') == bytes([0xEB, 0x09])


def test_pad_odd_and_normalize_empty_edges() -> None:
    from module_payload.cfg.hex_text import pad_odd_hex

    assert pad_odd_hex('') == ''
    assert normalize_hex_display('') == ''
    assert normalize_hex_display('GG') == ''
    with pytest.raises(ValueError, match='不能为空'):
        parse_hex_config_value(None, field_name='trailer')
    with pytest.raises(ValueError, match='不能为空'):
        parse_hex_config_value(b'', field_name='trailer')
