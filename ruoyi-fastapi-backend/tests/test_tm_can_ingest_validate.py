"""CAN 遥测解释器：校验失败在 TeleMetry 解析之前抛出。"""

from __future__ import annotations

import pytest

from module_payload.parsers.biu_can_tm import BiuCanTmIngest
from module_payload.parsers.xl_can_tm import XlCanTmIngest


def test_biu_prepare_rejects_short() -> None:
    with pytest.raises(ValueError, match='过短|为空'):
        BiuCanTmIngest.prepare_bytes(b'\x00\x01')


def test_xl_prepare_rejects_bad_type() -> None:
    # 合法长度但类型不是 0x3A
    raw = bytes([0x00, 0x02, 0x00, 0xFF, 0x01])
    chk = sum(raw[:-1]) & 0xFF
    raw = raw[:-1] + bytes([chk])
    with pytest.raises(ValueError, match='帧类型|过短|校验'):
        XlCanTmIngest.prepare_bytes(raw)


def test_parse_hex_bad() -> None:
    with pytest.raises(ValueError):
        BiuCanTmIngest.parse_hex('GG')
