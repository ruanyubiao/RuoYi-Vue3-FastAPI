"""相机 D8/D9：拆帧校验 + 真实慢遥/快遥样例字段。"""

from __future__ import annotations

from pathlib import Path

import pytest

from module_payload.cfg.hex_text import hex_to_bytes
from module_payload.parsers.camera_sc_link41ep import (
    D8_DATA_LEN,
    D8_FRAME_MIN,
    D9_DATA_LEN,
    D9_EXTENDED_DATA_LEN,
    D9_FRAME_LEN,
    FRAME_HEADER,
    FRAME_TYPE_D8,
    FRAME_TYPE_D9,
    CameraScLink41epIngest,
    _TABLE_NAMES,
    _calc_checksum,
    reset_cam_tm_mgr,
)
from module_payload.parsers.tm_ingest_batch import flush_pending

# 地检抓包：慢遥 D8 / 快遥 D9（空白分隔 token）
REAL_D8_HEX = (
    'EB 90 D8 00 00 2D 34 8A AA AA 01 36 3C 7F 8D FF 00 10 66 9E 06 05 '
    '01 00 10 00 00 00 09 E7 02 58 01 4F 00 01 01 14 07 D2 0D 48 03 90 '
    '0A 6A 00 00 00 00 32 01 32 0F'
)
REAL_D9_HEX = 'EB D9 AC AD AA 01 FF FF FF FF 00 00 08 AD 00 07 D5 0C 4E EB'
# test/单板-相机-遥测D9.txt 前 30 行（seq 从 AE 起，mux=6，不从 0 对齐）
REAL_D9_CAPTURE_30 = (
    'EB D9 AE AD AA 01 4C A1 2F AE 37 00 05 F7 A7 01 00 00 01 AC',
    'EB D9 AF AD AA 01 4C A3 2F AE 38 00 05 E7 A7 00 00 00 00 9E',
    'EB D9 B0 AD AA 01 4C A3 2F AF 38 00 05 EA A7 03 00 02 E5 8D',
    'EB D9 B1 AD AA 01 4C A3 2F AE 38 00 05 E6 A7 00 00 00 03 A2',
    'EB D9 B2 AD AA 01 4C A3 2F AE 38 00 05 E4 A7 02 58 01 2D 26',
    'EB D9 B3 AD AA 01 4C A1 2F AF 37 00 05 FC A7 00 01 01 14 CB',
    'EB D9 B4 AD AA 01 4C A4 2F AF 38 00 05 E6 A7 07 C9 0C E4 64',
    'EB D9 B5 AD AA 01 4C A4 2F AE 38 00 05 E9 A7 03 90 0A 6A AE',
    'EB D9 B6 AD AA 01 4C A4 2F AF 38 00 05 E6 A7 01 00 00 01 A8',
    'EB D9 B7 AD AA 01 4C A3 2F AF 38 00 05 E8 A7 00 00 00 00 A8',
    'EB D9 B8 AD AA 01 4C A2 2F AE 37 00 05 FC A7 03 00 02 E5 A4',
    'EB D9 B9 AD AA 01 4C A3 2F AF 38 00 05 E9 A7 00 00 00 03 AE',
    'EB D9 BA AD AA 01 4C A3 2F AF 38 00 05 E6 A7 02 58 01 2D 31',
    'EB D9 BB AD AA 01 4C A4 2F AE 38 00 05 ED A7 00 01 01 14 C7',
    'EB D9 BC AD AA 01 4C A3 2F AF 38 00 05 E5 A7 07 C9 0C E4 6A',
    'EB D9 BD AD AA 01 4C A3 2F AF 38 00 05 EA A7 03 90 0A 6A B7',
    'EB D9 BE AD AA 01 4C A3 2F AE 38 00 05 E9 A7 01 00 00 01 B1',
    'EB D9 BF AD AA 01 4C A3 2F AF 38 00 05 E5 A7 00 00 00 00 AD',
    'EB D9 C0 AD AA 01 4C A3 2F AF 38 00 05 E6 A7 03 00 02 E5 99',
    'EB D9 C1 AD AA 01 4C A2 2F AF 37 00 05 FC A7 00 00 00 03 C7',
    'EB D9 C2 AD AA 01 4C A2 2F B0 37 00 05 FD A7 02 58 01 2D 4F',
    'EB D9 C3 AD AA 01 4C A3 2F AF 38 00 05 EA A7 00 01 01 14 CC',
    'EB D9 C4 AD AA 01 4C A3 2F AE 38 00 05 E1 A7 07 C9 0C E4 6D',
    'EB D9 C5 AD AA 01 4C A3 2F AF 38 00 05 E7 A7 03 90 0A 6A BC',
    'EB D9 C6 AD AA 01 4C A3 2F AF 38 00 05 E6 A7 01 00 00 01 B7',
    'EB D9 C7 AD AA 01 4C A2 2F AE 37 00 05 FC A7 00 00 00 00 C9',
    'EB D9 C8 AD AA 01 4C A3 2F AF 38 00 05 E1 A7 03 00 02 E5 9C',
    'EB D9 C9 AD AA 01 4C A1 2F B0 37 00 05 FA A7 00 00 00 03 CD',
    'EB D9 CA AD AA 01 4C A3 2F AF 38 00 05 E9 A7 02 58 01 2D 44',
    'EB D9 CB AD AA 01 4C A3 2F AE 38 00 05 E8 A7 00 01 01 14 D1',
)


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


def _d9_camf011_payload(camf011: bytes) -> bytes:
    payload = bytearray(16)
    payload[12:16] = camf011[:4].ljust(4, b'\x00')
    return bytes(payload)


def test_extract_d8_sticky_and_noise() -> None:
    f1 = _d8_frame()
    f2 = _d8_frame(bytes([0x11]) * D8_DATA_LEN)
    blob = b'\x00\x11' + f1 + f2 + b'\xff'
    frames = CameraScLink41epIngest.extract_d8_frames(blob)
    assert len(frames) == 2
    assert all(len(f) == D8_FRAME_MIN for f in frames)
    assert frames[0][2] == FRAME_TYPE_D8


def test_io_preview_frames_drops_prefix_keeps_d8() -> None:
    """粘包前缀噪声不能进 IO 预览，只留完整 D8。"""
    frame = hex_to_bytes(REAL_D8_HEX)
    blob = bytes.fromhex('01 07 00 00 00 13 24 E5') + frame + bytes.fromhex('01 07')
    frames = CameraScLink41epIngest.io_preview_frames(blob)
    assert frames[-1] == frame
    assert frames[-1].startswith(FRAME_HEADER + bytes([FRAME_TYPE_D8]))


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
    assert len(got[0].payload) == D9_EXTENDED_DATA_LEN
    assert got[0].payload[:D9_DATA_LEN] == frame[3:19]


def test_collect_prepared_d8_bad_checksum_raises() -> None:
    raw = bytearray(_d8_frame())
    raw[-1] ^= 0xFF
    with pytest.raises(ValueError, match='校验和错误'):
        CameraScLink41epIngest._collect_prepared(bytes(raw))


def test_reset_cam_tm_mgr_clears_table_name_cache() -> None:
    CameraScLink41epIngest._table_name('D8')
    assert 'D8' in _TABLE_NAMES
    CameraScLink41epIngest._collect_prepared(_d9_frame(seq=4), src_param='serial:COM3')
    reset_cam_tm_mgr()
    assert _TABLE_NAMES == {}
    from module_payload.parsers.camera_sc_link41ep import _d9_mux_cache

    assert _d9_mux_cache == {}


def test_ingest_bytes_sync_serial_does_not_archive() -> None:
    from unittest.mock import MagicMock

    redis = MagicMock()
    pipe = MagicMock()
    redis.pipeline.return_value = pipe
    pipe.zadd.return_value = pipe
    pipe.zremrangebyrank.return_value = pipe
    pipe.set.return_value = pipe
    pipe.execute.return_value = []
    blob = _d8_frame() * 4
    CameraScLink41epIngest.ingest_bytes_sync(redis, blob, src_param='serial:COM3')
    flush_pending(redis)
    assert redis.lpush.call_count == 0
    assert pipe.zadd.call_count > 0


def test_ingest_bytes_sync_noise_is_noop() -> None:
    from unittest.mock import MagicMock

    redis = MagicMock()
    assert CameraScLink41epIngest.ingest_bytes_sync(redis, bytes([0x11]) * 64, src_param='serial:COM3') is None
    redis.lpush.assert_not_called()


def test_ingest_bytes_sync_d8_bad_checksum_quiet() -> None:
    from unittest.mock import MagicMock

    redis = MagicMock()
    raw = bytearray(_d8_frame())
    raw[-1] ^= 0xFF
    assert CameraScLink41epIngest.ingest_bytes_sync(redis, bytes(raw), src_param='serial:COM3') is None


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
    reset_cam_tm_mgr()
    parsed = CameraScLink41epIngest.parse_hex(REAL_D9_HEX)
    assert parsed.table_key == 'D9'
    assert parsed.size == 20
    assert parsed.data_len == D9_EXTENDED_DATA_LEN
    assert parsed.raw_frame[2] == 0xAC
    assert len(parsed.fields) == 31
    assert _field(parsed, 'CAMF001')['show'] == 'AD'
    assert _field(parsed, 'CAMF002')['show'] == '正确'
    assert _field(parsed, 'CAMF003')['show'] == '质心'
    assert _field(parsed, 'CAMF004')['calc_val'] == pytest.approx(511.9921875)
    assert _field(parsed, 'CAMF005')['calc_val'] == pytest.approx(511.9921875)
    assert _field(parsed, 'CAMF008')['value'] == 2221
    assert _field(parsed, 'CAMF009')['show'] == '无光斑'
    assert _field(parsed, 'CAMF011')['show'] == '07D50C4E'
    # mux=4（AC & 7）：探测器/模组温度有值；其余扩展槽填 0
    assert _field(parsed, 'CAMF022')['calc_val'] == pytest.approx(20.05)
    assert _field(parsed, 'CAMF023')['calc_val'] == pytest.approx(31.50)
    assert _field(parsed, 'CAMF012')['value'] == 0
    assert _field(parsed, 'CAMF015')['value'] == 0
    assert _field(parsed, 'CAMF018')['value'] == 0
    assert _field(parsed, 'CAMF026')['value'] == 0
    assert _field(parsed, 'CAMF030')['value'] == 0


def test_real_d8_and_d9_in_one_stream() -> None:
    d8 = hex_to_bytes(REAL_D8_HEX)
    d9 = hex_to_bytes(REAL_D9_HEX)
    blob = b'\x00\x11' + d8 + b'\xff' + d9 + b'\x22'
    prepared = CameraScLink41epIngest._collect_prepared(blob)
    assert [p.table_key for p in prepared] == ['D8', 'D9']
    assert prepared[0].payload[:2] == bytes([0xAA, 0xAA])
    assert prepared[1].payload[:2] == bytes([0xAD, 0xAA])
    assert len(prepared[1].payload) == D9_EXTENDED_DATA_LEN
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


def _parse_d9(frame: bytes, src_param: str = 'serial:COM3'):
    prepared = CameraScLink41epIngest._collect_prepared(frame, src_param=src_param)
    assert len(prepared) == 1
    return CameraScLink41epIngest._to_parsed(prepared[0])


def test_d9_mux_batch_overrides_cache() -> None:
    reset_cam_tm_mgr()
    src = 'serial:COM3'
    old = _d9_frame(seq=4, data=_d9_camf011_payload(bytes([0xAA, 0xAA, 0xAA, 0xAA])))
    _parse_d9(old, src)
    new = _d9_frame(seq=4, data=_d9_camf011_payload(bytes([0x07, 0xD5, 0x0C, 0x4E])))
    parsed = _parse_d9(new, src)
    assert _field(parsed, 'CAMF011')['show'] == '07D50C4E'
    assert _field(parsed, 'CAMF022')['calc_val'] == pytest.approx(20.05)
    assert _field(parsed, 'CAMF023')['calc_val'] == pytest.approx(31.50)


def test_d9_mux_missing_slots_fill_zero_then_cache() -> None:
    reset_cam_tm_mgr()
    src = 'serial:COM3'
    mux4 = _d9_frame(seq=4, data=_d9_camf011_payload(bytes([0x07, 0xD5, 0x0C, 0x4E])))
    first = _parse_d9(mux4, src)
    assert _field(first, 'CAMF015')['value'] == 0
    mux0 = _d9_frame(seq=0, data=_d9_camf011_payload(bytes([0x0A, 0x12, 0x34, 0x0B])))
    second = _parse_d9(mux0, src)
    assert _field(second, 'CAMF012')['value'] == 10
    assert _field(second, 'CAMF013')['show'] == '1234'
    assert _field(second, 'CAMF014')['value'] == 11
    # mux4 来自缓存
    assert _field(second, 'CAMF022')['calc_val'] == pytest.approx(20.05)
    assert _field(second, 'CAMF011')['show'] == '0A12340B'


def test_d9_mux_eight_frames_accumulate_via_cache() -> None:
    reset_cam_tm_mgr()
    src = 'serial:COM3'
    slots = [
        bytes([0x0A, 0x12, 0x34, 0x0B]),
        bytes([0x00, 0x00, 0x00, 0x64]),
        bytes([0x02, 0x58, 0x01, 0x4F]),
        bytes([0x00, 0x01, 0x01, 0x14]),
        bytes([0x07, 0xD5, 0x0C, 0x4E]),
        bytes([0x03, 0x90, 0x0A, 0x6A]),
        bytes([0x05, 0x02, 0x01, 0x03]),
        bytes([0x00, 0x10, 0x00, 0x20]),
    ]
    parsed = None
    for mux, blob in enumerate(slots):
        parsed = _parse_d9(_d9_frame(seq=mux, data=_d9_camf011_payload(blob)), src)
        assert parsed is not None
        assert len(parsed.fields) == 31
    assert _field(parsed, 'CAMF012')['value'] == 10
    assert _field(parsed, 'CAMF015')['value'] == 100
    assert _field(parsed, 'CAMF016')['value'] == 600
    assert _field(parsed, 'CAMF018')['show'] == '低增益'
    assert _field(parsed, 'CAMF019')['show'] == '开启'
    assert _field(parsed, 'CAMF022')['calc_val'] == pytest.approx(20.05)
    assert _field(parsed, 'CAMF024')['value'] == 912
    assert _field(parsed, 'CAMF026')['value'] == 5
    assert _field(parsed, 'CAMF027')['show'] == '128×128'
    assert _field(parsed, 'CAMF029')['show'] == '64×64'
    assert _field(parsed, 'CAMF030')['value'] == 16
    assert _field(parsed, 'CAMF031')['value'] == 32


def test_d9_mux_eight_frames_in_one_blob() -> None:
    reset_cam_tm_mgr()
    slots = [bytes([i, i, i, i]) for i in range(8)]
    blob = b''.join(_d9_frame(seq=i, data=_d9_camf011_payload(slots[i])) for i in range(8))
    prepared = CameraScLink41epIngest._collect_prepared(blob, src_param='serial:COM3')
    assert len(prepared) == 8
    mux32 = b''.join(slots)
    for item in prepared:
        assert item.payload[16:] == mux32
    parsed = CameraScLink41epIngest._to_parsed(prepared[-1])
    assert _field(parsed, 'CAMF011')['show'] == '07070707'
    assert _field(parsed, 'CAMF012')['value'] == 0
    assert _field(parsed, 'CAMF015')['value'] == 0x01010101
    assert _field(parsed, 'CAMF030')['value'] == 0x0707
    assert _field(parsed, 'CAMF031')['value'] == 0x0707


def _assert_d9_capture_mux_fields(parsed) -> None:
    """前 30 行里 mux0–7 的 CAMF011 四字节稳定，两轮拼出的扩展字段应一致。"""
    assert _field(parsed, 'CAMF012')['value'] == 3
    assert _field(parsed, 'CAMF013')['show'] == '0002'
    assert _field(parsed, 'CAMF014')['value'] == 0xE5
    assert _field(parsed, 'CAMF015')['value'] == 3
    assert _field(parsed, 'CAMF016')['value'] == 600
    assert _field(parsed, 'CAMF017')['value'] == 301
    assert _field(parsed, 'CAMF018')['show'] == '低增益'
    assert _field(parsed, 'CAMF019')['show'] == '开启'
    assert _field(parsed, 'CAMF020')['show'] == '自动'
    assert _field(parsed, 'CAMF021')['value'] == 20
    assert _field(parsed, 'CAMF022')['calc_val'] == pytest.approx(19.93)
    assert _field(parsed, 'CAMF023')['calc_val'] == pytest.approx(33.00)
    assert _field(parsed, 'CAMF024')['value'] == 912
    assert _field(parsed, 'CAMF025')['value'] == 2666
    assert _field(parsed, 'CAMF026')['value'] == 1
    assert _field(parsed, 'CAMF027')['show'] == '400×400'
    assert _field(parsed, 'CAMF028')['show'] == '1分区'
    assert _field(parsed, 'CAMF029')['show'] == '256×256'
    assert _field(parsed, 'CAMF030')['value'] == 0
    assert _field(parsed, 'CAMF031')['value'] == 0


def test_d9_capture_two_rounds_midstream() -> None:
    """实采前 30 行：seq 从 AE（mux=6）起，分两轮各 15 帧 ingest。"""
    reset_cam_tm_mgr()
    frames = [hex_to_bytes(line) for line in REAL_D9_CAPTURE_30]
    assert len(frames) == 30
    assert all(len(fr) == D9_FRAME_LEN for fr in frames)
    assert all(fr[0:2] == bytes([0xEB, FRAME_TYPE_D9]) for fr in frames)
    muxes = [fr[2] & 7 for fr in frames]
    assert muxes[0] == 6
    assert muxes[:8] != list(range(8))
    assert CameraScLink41epIngest.extract_d9_frames(b''.join(frames)) == frames

    src = 'serial:COM3'
    round1 = CameraScLink41epIngest._collect_prepared(b''.join(frames[:15]), src_param=src)
    round2 = CameraScLink41epIngest._collect_prepared(b''.join(frames[15:]), src_param=src)
    assert len(round1) == 15
    assert len(round2) == 15
    assert all(len(p.payload) == D9_EXTENDED_DATA_LEN for p in round1 + round2)

    first = CameraScLink41epIngest._to_parsed(round1[0])
    last1 = CameraScLink41epIngest._to_parsed(round1[-1])
    last2 = CameraScLink41epIngest._to_parsed(round2[-1])
    assert len(first.fields) == len(last1.fields) == len(last2.fields) == 31

    # 首帧 mux=6：本帧 CAMF001–011 来自 AE，扩展槽由本批后续帧补齐
    assert first.raw_frame[2] == 0xAE
    assert _field(first, 'CAMF001')['show'] == 'AD'
    assert _field(first, 'CAMF002')['show'] == '正确'
    assert _field(first, 'CAMF003')['show'] == '质心'
    assert _field(first, 'CAMF004')['calc_val'] == pytest.approx(19617 / 128.0)
    assert _field(first, 'CAMF005')['calc_val'] == pytest.approx(12206 / 128.0)
    assert _field(first, 'CAMF006')['value'] == 55
    assert _field(first, 'CAMF008')['value'] == 0x05F7
    assert _field(first, 'CAMF009')['show'] == '有光斑'
    assert _field(first, 'CAMF010')['calc_val'] == -39
    assert _field(first, 'CAMF011')['show'] == '01000001'

    # 第 1 轮末帧 BC（mux=4）/ 第 2 轮末帧 CB（mux=3）
    assert last1.raw_frame[2] == 0xBC
    assert _field(last1, 'CAMF008')['value'] == 0x05E5
    assert _field(last1, 'CAMF011')['show'] == '07C90CE4'
    assert last2.raw_frame[2] == 0xCB
    assert _field(last2, 'CAMF008')['value'] == 0x05E8
    assert _field(last2, 'CAMF011')['show'] == '00010114'

    _assert_d9_capture_mux_fields(first)
    _assert_d9_capture_mux_fields(last1)
    _assert_d9_capture_mux_fields(last2)


_CAM_RECV_BIN = (
    Path(__file__).resolve().parents[1]
    / 'logs_data'
    / '20260824'
    / 'camera_ctrl_serial_COM3_20260824_145550_829_recv.bin'
)


@pytest.mark.skipif(not _CAM_RECV_BIN.is_file(), reason='缺少 COM3 实采 recv.bin')
def test_real_com3_recv_bin_keeps_every_d8_frame() -> None:
    raw = _CAM_RECV_BIN.read_bytes()
    d8 = CameraScLink41epIngest.extract_d8_frames(raw)
    d9 = CameraScLink41epIngest.extract_d9_frames(raw)
    prepared = CameraScLink41epIngest._collect_prepared(raw)
    assert len(d8) == 106790
    assert len(d9) == 0
    assert len(prepared) == len(d8)
    assert all(p.table_key == 'D8' for p in prepared)
    assert prepared[0].raw_frame == d8[0]
    assert prepared[-1].raw_frame == d8[-1]
    assert len(prepared[0].payload) == D8_DATA_LEN
