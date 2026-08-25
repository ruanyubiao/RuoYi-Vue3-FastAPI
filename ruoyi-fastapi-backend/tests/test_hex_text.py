"""HEX 文本：空白分隔 token，奇数位在末半字节前补 0（对齐前端 payloadRawData.js）。"""

from __future__ import annotations

import pytest

from module_payload.cfg.can_yc_frame import hex_to_bytes as can_yc_hex_to_bytes
from module_payload.cfg.hex_text import hex_to_bytes, normalize_hex_display
from module_payload.cfg.telecontrol_assembler import hex_to_bytes as tele_hex_to_bytes


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


def test_can_yc_and_telecontrol_share_token_rule() -> None:
    assert can_yc_hex_to_bytes('A B') == bytes([0x0A, 0x0B])
    assert tele_hex_to_bytes('A B') == bytes([0x0A, 0x0B])
    assert tele_hex_to_bytes('0xEB 90') == bytes([0xEB, 0x90])
    assert tele_hex_to_bytes('eb9') == bytes([0xEB, 0x09])
