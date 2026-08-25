"""相机 D8/D9 拆帧校验（不依赖 TeleMetry 字段解析）。"""

from __future__ import annotations

from module_payload.parsers.camera_sc_link41ep import (
    D8_DATA_LEN,
    D8_FRAME_MIN,
    D9_FRAME_LEN,
    FRAME_HEADER,
    FRAME_TYPE_D8,
    FRAME_TYPE_D9,
    CameraScLink41epIngest,
    _calc_checksum,
)


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
