"""相机 D8/D9：拆帧校验 + 真实慢遥/快遥样例字段。"""

from __future__ import annotations

import pytest

from module_payload.cfg.hex_text import hex_to_bytes
from module_payload.parsers.camera_sc_link41ep import (
    D8_DATA_LEN,
    D8_FRAME_MIN,
    D9_DATA_LEN,
    D9_FRAME_LEN,
    FRAME_HEADER,
    FRAME_TYPE_D8,
    FRAME_TYPE_D9,
    CameraScLink41epIngest,
    _calc_checksum,
)

# 地检抓包：慢遥 D8 / 快遥 D9（空白分隔 token）
REAL_D8_HEX = (
    'EB 90 D8 00 00 2D 34 8A AA AA 01 36 3C 7F 8D FF 00 10 66 9E 06 05 '
    '01 00 10 00 00 00 09 E7 02 58 01 4F 00 01 01 14 07 D2 0D 48 03 90 '
    '0A 6A 00 00 00 00 32 01 32 0F'
)
REAL_D9_HEX = 'EB D9 AC AD AA 01 FF FF FF FF 00 00 08 AD 00 07 D5 0C 4E EB'


def _field(parsed, fid: str) -> dict:
    return next(f for f in parsed.fields if f.get('id') == fid)


def _d8_frame(payload: bytes | None = None) -> bytes:
    data = payload if payload is not None else bytes(D8_DATA_LEN)
    data = data[:D8_DATA_LEN].ljust(D8_DATA_LEN, b'\x00')
    body = bytes(
        [
            FRAME_TYPE_D8,
            0x00,
            (D8_DATA_LEN >> 8) & 0xFF,
            D8_DATA_LEN & 0xFF,
            0x00,
            0x01,
        ]
    ) + data
    return FRAME_HEADER + body + bytes([_calc_checksum(body)])


def _d9_frame(seq: int = 1, data: bytes | None = None) -> bytes:
    payload = (data or bytes(16))[:16].ljust(16, b'\x00')
    mid = bytes([seq & 0xFF]) + payload
    return bytes([0xEB, FRAME_TYPE_D9]) + mid + bytes([_calc_checksum(mid)])


def test_extract_d8_sticky_and_noise() -> None:
    f1 = _d8_frame()
    f2 = _d8_frame(bytes([0x11]) * D8_DATA_LEN)
    blob = b'\x00\x11' + f1 + f2 + b'\xff'
    frames = CameraScLink41epIngest.extract_d8_frames(blob)
    assert len(frames) == 2
    assert all(len(f) == D8_FRAME_MIN for f in frames)
    assert frames[0][2] == FRAME_TYPE_D8


def test_extract_d8_skips_other_type() -> None:
    other = FRAME_HEADER + bytes([0xD0]) + b'\x00' * 20
    frames = CameraScLink41epIngest.extract_d8_frames(other + _d8_frame())
    assert len(frames) == 1


def test_extract_d9_checksum_filter() -> None:
    good = _d9_frame(seq=3)
    bad = bytearray(good)
    bad[-1] ^= 0xFF
    frames = CameraScLink41epIngest.extract_d9_frames(bytes(bad) + good)
    assert frames == [good]
    assert len(good) == D9_FRAME_LEN


def test_collect_prepared_ignores_noise() -> None:
    assert CameraScLink41epIngest._collect_prepared(bytes([0x11]) * 4096) == []


def test_collect_prepared_keeps_d8() -> None:
    frame = _d8_frame()
    got = CameraScLink41epIngest._collect_prepared(frame * 3)
    assert len(got) == 3
    assert all(p.table_key == 'D8' for p in got)


def test_collect_prepared_keeps_d9() -> None:
    frame = _d9_frame(seq=0xAC)
    got = CameraScLink41epIngest._collect_prepared(frame)
    assert len(got) == 1
    assert got[0].table_key == 'D9'
    assert len(got[0].payload) == D9_DATA_LEN


def test_real_d8_frame_structure_and_checksum() -> None:
    raw = hex_to_bytes(REAL_D8_HEX)
    assert len(raw) == D8_FRAME_MIN == 54
    assert raw[0:3] == FRAME_HEADER + bytes([FRAME_TYPE_D8])
    assert ((raw[4] << 8) | raw[5]) == D8_DATA_LEN
    assert _calc_checksum(raw[2:-1]) == raw[-1]
    assert CameraScLink41epIngest.extract_d8_frames(b'\x11' + raw + b'\xff') == [raw]


def test_real_d9_frame_structure_and_checksum() -> None:
    raw = hex_to_bytes(REAL_D9_HEX)
    assert len(raw) == D9_FRAME_LEN == 20
    assert raw[0:2] == bytes([0xEB, FRAME_TYPE_D9])
    assert raw[2] == 0xAC
    assert _calc_checksum(raw[2:19]) == raw[19]
    assert CameraScLink41epIngest.extract_d9_frames(b'\x00' + raw + b'\xff') == [raw]


def test_real_d8_parse_fields() -> None:
    parsed = CameraScLink41epIngest.parse_hex(REAL_D8_HEX)
    assert parsed.table_key == 'D8'
    assert parsed.frame_type == 'D8'
    assert parsed.size == 54
    assert parsed.data_len == D8_DATA_LEN
    assert len(parsed.fields) == 38
    assert _field(parsed, 'CAM001')['show'] == 'AA'
    assert _field(parsed, 'CAM002')['show'] == '正确'
    assert _field(parsed, 'CAM003')['show'] == '质心'
    assert _field(parsed, 'CAM004')['calc_val'] == pytest.approx(108.46875)
    assert _field(parsed, 'CAM005')['calc_val'] == pytest.approx(255.1015625)
    assert _field(parsed, 'CAM006')['value'] == 255
    assert _field(parsed, 'CAM009')['show'] == '有光斑'
    assert _field(parsed, 'CAM010')['calc_val'] == -30
    assert _field(parsed, 'CAM011')['show'] == '0605'
    assert _field(parsed, 'CAM013')['show'] == '2分区'
    assert _field(parsed, 'CAM014')['show'] == '1分区'
    assert _field(parsed, 'CAM015')['value'] == 9
    assert _field(parsed, 'CAM024')['value'] == 600
    assert _field(parsed, 'CAM025')['value'] == 335
    assert _field(parsed, 'CAM026')['show'] == '低增益'
    assert _field(parsed, 'CAM027')['show'] == '开启'
    assert _field(parsed, 'CAM028')['show'] == '自动'
    assert _field(parsed, 'CAM030')['calc_val'] == pytest.approx(20.02)
    assert _field(parsed, 'CAM031')['calc_val'] == pytest.approx(34.0)


def test_real_d9_parse_fields() -> None:
    parsed = CameraScLink41epIngest.parse_hex(REAL_D9_HEX)
    assert parsed.table_key == 'D9'
    assert parsed.size == 20
    assert parsed.data_len == D9_DATA_LEN
    assert parsed.raw_frame[2] == 0xAC
    assert len(parsed.fields) == 11
    assert _field(parsed, 'CAMF001')['show'] == 'AD'
    assert _field(parsed, 'CAMF002')['show'] == '正确'
    assert _field(parsed, 'CAMF003')['show'] == '质心'
    assert _field(parsed, 'CAMF004')['calc_val'] == pytest.approx(511.9921875)
    assert _field(parsed, 'CAMF005')['calc_val'] == pytest.approx(511.9921875)
    assert _field(parsed, 'CAMF008')['value'] == 2221
    assert _field(parsed, 'CAMF009')['show'] == '无光斑'
    assert _field(parsed, 'CAMF011')['show'] == '07D50C4E'


def test_real_d8_and_d9_in_one_stream() -> None:
    d8 = hex_to_bytes(REAL_D8_HEX)
    d9 = hex_to_bytes(REAL_D9_HEX)
    blob = b'\x00\x11' + d8 + b'\xff' + d9 + b'\x22'
    prepared = CameraScLink41epIngest._collect_prepared(blob)
    assert [p.table_key for p in prepared] == ['D8', 'D9']
    assert prepared[0].payload[:2] == bytes([0xAA, 0xAA])
    assert prepared[1].payload[:2] == bytes([0xAD, 0xAA])
    # parse_bytes 优先 D8（取最后一帧完整慢遥）
    parsed = CameraScLink41epIngest.parse_bytes(blob)
    assert parsed.table_key == 'D8'


def test_real_d8_bad_checksum_raises() -> None:
    raw = bytearray(hex_to_bytes(REAL_D8_HEX))
    raw[-1] ^= 0xFF
    with pytest.raises(ValueError, match='校验和错误'):
        CameraScLink41epIngest.parse_bytes(bytes(raw))


def test_real_d9_bad_checksum_skipped() -> None:
    raw = bytearray(hex_to_bytes(REAL_D9_HEX))
    raw[-1] ^= 0xFF
    assert CameraScLink41epIngest.extract_d9_frames(bytes(raw)) == []
    with pytest.raises(ValueError, match='校验和错误|未找到有效'):
        CameraScLink41epIngest.parse_bytes(bytes(raw))
