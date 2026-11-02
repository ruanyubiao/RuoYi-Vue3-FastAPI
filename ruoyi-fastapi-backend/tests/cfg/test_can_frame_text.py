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


def test_parse_can_frame_text_short_or_padded_id_and_brackets() -> None:
    """ID 短写 / 8 位补零等价；数据可带或不带 []；空白数量不限。"""
    plain = parse_can_frame_text(
        """
        779  00 25 3A FF 03 02 01 11
        77A  96 50 19 1A 18 0A 14 1E
        """
    )
    bracketed = parse_can_frame_text(
        """
        00000779  [00 25 3A FF 03 02 01 11]
        0000077A\t\t[96 50 19 1A 18 0A 14 1E]
        0000077B[0B 16 21 2C 61 A8 64 6F]
        00000779     [  00   25  3A FF 03 02 01 11  ]
        """
    )
    assert len(plain) == 2
    assert len(bracketed) == 4
    assert plain[0].un_id == 0x779
    assert bracketed[0].un_id == 0x779
    assert bytes(plain[0].str_data) == bytes(bracketed[0].str_data) == bytes.fromhex(
        '00253AFF03020111'
    )
    assert plain[1].un_id == bracketed[1].un_id == 0x77A
    assert bytes(plain[1].str_data) == bytes(bracketed[1].str_data)
    assert bracketed[2].un_id == 0x77B
    assert bytes(bracketed[2].str_data) == bytes.fromhex('0B16212C61A8646F')
    assert bytes(bracketed[3].str_data) == bytes(bracketed[0].str_data)


def test_parse_can_frame_text_optional_timestamp_prefix() -> None:
    """采集日志时间前缀可选；去掉后与无时间写法等价。"""
    with_ts = parse_can_frame_text(
        """
        20261029101019 00000779  [00 25 3A FF 03 02 01 11]
        20261029101019 0000077A  [96 50 19 1A 18 0A 14 1E]
        20261029101019 0000077A  [28 32 3C 32 33 34 35 36]
        20261029101019 0000077A  [37 38 39 3A 11 11 00 14]
        20261029101019 0000077B  [0B 16 21 2C 61 A8 64 6F]
        """
    )
    no_ts = parse_can_frame_text(
        """
        00000779  [00 25 3A FF 03 02 01 11]
        0000077A  [96 50 19 1A 18 0A 14 1E]
        0000077A  [28 32 3C 32 33 34 35 36]
        0000077A  [37 38 39 3A 11 11 00 14]
        0000077B  [0B 16 21 2C 61 A8 64 6F]
        """
    )
    assert len(with_ts) == 5
    assert [(f.un_id, bytes(f.str_data)) for f in with_ts] == [
        (f.un_id, bytes(f.str_data)) for f in no_ts
    ]
    assert with_ts[0].un_id == 0x779
    assert with_ts[-1].un_id == 0x77B


def test_parse_can_frame_text_rejects_oversize() -> None:
    with pytest.raises(ValueError, match='超过 8 字节'):
        parse_can_frame_text('769  00 01 02 03 04 05 06 07 08')


def test_parse_can_frame_text_rejects_bad_line() -> None:
    with pytest.raises(ValueError, match='格式错误'):
        parse_can_frame_text('onlyid')
