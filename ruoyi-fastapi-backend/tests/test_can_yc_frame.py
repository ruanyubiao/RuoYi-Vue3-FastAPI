"""CAN 遥测复合帧校验 / 解析。"""

from __future__ import annotations

from module_payload.cfg.can_yc_frame import (
    CAN_YC_FRAME_TYPE_COMPLEX,
    hex_to_bytes,
    parse_can_yc_frame,
    verify_can_yc_frame,
)
from module_payload.error_text import checksum_mismatch, frame_len_mismatch, frame_len_over_limit


def _build(data_type: int = 0xFF, payload: bytes = b'\x11\x22') -> bytes:
    body = bytes([CAN_YC_FRAME_TYPE_COMPLEX, data_type & 0xFF]) + payload
    data_len = len(body)
    head = bytes([(data_len >> 8) & 0xFF, data_len & 0xFF]) + body
    chk = sum(head) & 0xFF
    return head + bytes([chk])


def test_hex_to_bytes_odd_nibble() -> None:
    assert hex_to_bytes('A B') == bytes([0xAB])
    assert hex_to_bytes('AB0')[-1:]  # odd → last nibble padded
    assert hex_to_bytes('') == b''


def test_verify_ok_and_parse() -> None:
    raw = _build(0xFF, b'\xaa\xbb\xcc')
    ok, msg, frame = verify_can_yc_frame(raw + b'\x00\x00')  # 尾部填充忽略
    assert ok is True
    assert msg == 'OK'
    parsed = parse_can_yc_frame(frame)
    assert parsed['dataType'] == 'FF'
    assert parsed['frameType'] == '3A'
    assert parsed['payload'] == b'\xaa\xbb\xcc'
    assert 'AA BB CC' in parsed['payloadHex']


def test_verify_empty_and_short() -> None:
    ok, msg, frame = verify_can_yc_frame(b'')
    assert ok is False and frame == b'' and '为空' in msg
    ok, msg, _ = verify_can_yc_frame(b'\x00\x01\x3a')
    assert ok is False and '过短' in msg


def test_verify_len_mismatch() -> None:
    raw = bytes([0x00, 0x10, 0x3A, 0xFF, 0x00])  # claims 16+3 but only 5 bytes
    ok, msg, _ = verify_can_yc_frame(raw)
    assert ok is False
    assert frame_len_mismatch('CAN 遥测', 0x10, 0x13, 5) in msg or '帧长不符' in msg


def test_verify_checksum_and_type() -> None:
    good = _build()
    bad_chk = bytearray(good)
    bad_chk[-1] ^= 0xFF
    ok, msg, _ = verify_can_yc_frame(bytes(bad_chk))
    assert ok is False
    assert '校验和' in msg

    bad_type = bytearray(good)
    bad_type[2] = 0x3B
    # 重算 checksum 让类型错误单独暴露
    body = bytes(bad_type[:-1])
    bad_type[-1] = sum(body) & 0xFF
    ok, msg, _ = verify_can_yc_frame(bytes(bad_type))
    assert ok is False
    assert '帧类型' in msg


def test_over_limit_message_helper() -> None:
    text = frame_len_over_limit('CAN 遥测', 600, 603, 512)
    assert '上限' in text and '512' in text
