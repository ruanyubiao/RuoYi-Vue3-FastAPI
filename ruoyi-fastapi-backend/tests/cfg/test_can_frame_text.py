"""CAN 帧文本解析（模拟页 CAN-* 组装器输入）。"""

from __future__ import annotations

import pytest

from module_payload.cfg.can_frame_text import parse_can_frame_text


def test_parse_can_frame_text_basic() -> None:
    frames = parse_can_frame_text(
        """
        # comment
        4FF  40 48 14 C0 00 00 C3 01
        0x4FF 01 00 BF 3A FF 40 0D 0D
        """
    )
    assert len(frames) == 2
    assert frames[0].un_id == 0x4FF
    assert bytes(frames[0].str_data) == bytes.fromhex('404814C00000C301')
    assert frames[1].un_id == 0x4FF
    assert frames[1].un_data_len == 8


def test_parse_can_frame_text_rejects_oversize() -> None:
    with pytest.raises(ValueError, match='超过 8 字节'):
        parse_can_frame_text('769  00 01 02 03 04 05 06 07 08')


def test_parse_can_frame_text_rejects_bad_line() -> None:
    with pytest.raises(ValueError, match='格式错误'):
        parse_can_frame_text('onlyid')
