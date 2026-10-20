"""BIU / XL 遥测内容校验。"""

from __future__ import annotations

import pytest

from module_payload.protocol.biu.can import tm as biu_tm
from module_payload.protocol.xl.can import tm as xl_tm

_CASES = [
    (biu_tm.verify_tm, biu_tm.TM_FRAME_TYPE, biu_tm.TM_SIZE_MAX, 'BIU 遥测'),
    (xl_tm.verify_tm, xl_tm.TM_FRAME_TYPE, xl_tm.TM_SIZE_MAX, 'XL 遥测'),
]


def _build(frame_type: int, data_type: int = 0xFF, payload: bytes = b'\x11\x22') -> bytes:
    body = bytes([frame_type, data_type & 0xFF]) + payload
    data_len = len(body)
    head = bytes([(data_len >> 8) & 0xFF, data_len & 0xFF]) + body
    return head + bytes([sum(head) & 0xFF])


@pytest.mark.parametrize('verify,frame_type,_limit,kind', _CASES)
def test_verify_ok_strips_padding(verify, frame_type, _limit, kind) -> None:
    raw = _build(frame_type, 0xFF, b'\xaa\xbb\xcc')
    ok, msg, frame = verify(raw + b'\x00\x00')
    assert ok is True
    assert msg == 'OK'
    assert frame[2] == frame_type
    assert frame[3] == 0xFF
    assert frame[4:-1] == b'\xaa\xbb\xcc'
    assert kind


@pytest.mark.parametrize('verify,frame_type,_limit,_kind', _CASES)
def test_verify_empty_short_checksum_and_type(verify, frame_type, _limit, _kind) -> None:
    ok, msg, frame = verify(b'')
    assert ok is False and frame == b'' and '为空' in msg
    ok, msg, _ = verify(b'\x00\x01\x3a')
    assert ok is False and '过短' in msg

    good = _build(frame_type)
    bad_chk = bytearray(good)
    bad_chk[-1] ^= 0xFF
    ok, msg, _ = verify(bytes(bad_chk))
    assert ok is False and '校验和' in msg

    bad_type = bytearray(good)
    bad_type[2] = 0x3B
    bad_type[-1] = sum(bad_type[:-1]) & 0xFF
    ok, msg, _ = verify(bytes(bad_type))
    assert ok is False and '帧类型' in msg


@pytest.mark.parametrize('verify,_frame_type,limit,kind', _CASES)
def test_verify_length_errors(verify, _frame_type, limit, kind) -> None:
    raw = bytes([0x00, 0x10, 0x3A, 0xFF, 0x00])
    ok, msg, _ = verify(raw)
    assert ok is False and '帧长不符' in msg and kind in msg

    data_len = limit
    head = bytes([(data_len >> 8) & 0xFF, data_len & 0xFF, 0x3A, 0xFF]) + bytes(data_len - 2)
    raw = head + bytes([0])
    ok, msg, _ = verify(raw)
    assert ok is False and '上限' in msg
