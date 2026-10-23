# -*- coding: utf-8 -*-
"""D6 camera image protocol helpers (copied/adapted from backend camera_image_serial_sim).

No GUI deps. Used by CameraImageSim to answer IPC image-serial pull requests.
v16: response length field fixed 0x0101, data always 256 bytes.
v17: length field L means valid bytes = L+1 (1..256).
"""
from __future__ import annotations

import math

import numpy as np

FRAME_HEADER = bytes([0xEB, 0x90])
FRAME_TYPE = 0xD6
REQ_SIZE = 10
RESP_SIZE = 266
DATA_CHUNK = 256
REQ_LEN = 0x0001
RESP_LEN = 0x0101

_FRAME_ID_BIT_FIRST = 2
_FRAME_ID_BIT_MID = 1
_FRAME_ID_BIT_LAST = 0


def frame_id_is_first(frame_id: int) -> bool:
    return bool((int(frame_id) >> _FRAME_ID_BIT_FIRST) & 1)


def frame_id_is_last(frame_id: int) -> bool:
    return bool((int(frame_id) >> _FRAME_ID_BIT_LAST) & 1)


def frame_id_is_mid(frame_id: int) -> bool:
    return bool((int(frame_id) >> _FRAME_ID_BIT_MID) & 1)


def classify_frame_id(frame_id: int) -> str:
    fid = int(frame_id) & 0xFF
    if frame_id_is_first(fid):
        return "first"
    if frame_id_is_last(fid):
        return "last"
    if frame_id_is_mid(fid):
        return "mid"
    return "unknown"


def frame_id_is_valid(frame_id: int) -> bool:
    return classify_frame_id(frame_id) != "unknown"


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def take_row_major_chunk(arr: np.ndarray, start: int, count: int = DATA_CHUNK) -> bytes:
    out = np.zeros(count, dtype=np.uint8)
    if arr is None or arr.ndim != 2 or arr.size == 0 or start < 0:
        return out.tobytes()
    flat = np.ascontiguousarray(arr, dtype=np.uint8).ravel()
    if start >= flat.size:
        return out.tobytes()
    n = min(count, flat.size - start)
    out[:n] = flat[start : start + n]
    return out.tobytes()


def parse_request(buf: bytes) -> tuple[int, int, int] | None:
    if len(buf) < REQ_SIZE:
        return None
    if buf[0:2] != FRAME_HEADER or buf[2] != FRAME_TYPE:
        return None
    frame_id = buf[3]
    if not frame_id_is_valid(frame_id):
        return None
    length = (buf[4] << 8) | buf[5]
    if length != REQ_LEN:
        return None
    seq = (buf[6] << 8) | buf[7]
    image_no = buf[8]
    if checksum(buf[2:9]) != buf[9]:
        return None
    return frame_id, seq, image_no


def build_response(frame_id: int, seq: int, image_no: int, chunk: bytes) -> bytes:
    if len(chunk) < DATA_CHUNK:
        chunk = chunk + bytes(DATA_CHUNK - len(chunk))
    elif len(chunk) > DATA_CHUNK:
        chunk = chunk[:DATA_CHUNK]
    body = bytes(
        [
            FRAME_TYPE,
            frame_id & 0xFF,
            (RESP_LEN >> 8) & 0xFF,
            RESP_LEN & 0xFF,
            (seq >> 8) & 0xFF,
            seq & 0xFF,
            image_no & 0xFF,
        ]
    ) + chunk
    return FRAME_HEADER + body + bytes([checksum(body)])


def build_response_v17(frame_id: int, seq: int, image_no: int, chunk: bytes) -> bytes:
    valid = len(chunk)
    if valid < 1 or valid > DATA_CHUNK:
        raise ValueError(f"v17 chunk valid length must be 1..{DATA_CHUNK}")
    padded = chunk + bytes(DATA_CHUNK - valid)
    l = (valid - 1) & 0xFFFF
    body = bytes(
        [
            FRAME_TYPE,
            frame_id & 0xFF,
            (l >> 8) & 0xFF,
            l & 0xFF,
            (seq >> 8) & 0xFF,
            seq & 0xFF,
            image_no & 0xFF,
        ]
    ) + padded
    return FRAME_HEADER + body + bytes([checksum(body)])


def infer_n_from_last_seq(seq: int) -> int | None:
    if seq < 0:
        return None
    already = seq * DATA_CHUNK
    max_pixels = (seq + 1) * DATA_CHUNK
    n_max = math.isqrt(max_pixels)
    found: int | None = None
    for n in range(1, n_max + 1):
        area = n * n
        if area > already and (area - already) <= DATA_CHUNK:
            found = n
    return found


def find_valid_request_offset(data: bytes) -> int:
    search = 0
    while True:
        idx = data.find(FRAME_HEADER, search)
        if idx < 0 or idx + REQ_SIZE > len(data):
            return -1
        if parse_request(data[idx : idx + REQ_SIZE]) is not None:
            return idx
        search = idx + 1


def consume_rx(buf: bytearray) -> list[tuple]:
    events: list[tuple] = []
    while buf:
        req_off = find_valid_request_offset(bytes(buf))
        if req_off == 0:
            raw = bytes(buf[:REQ_SIZE])
            parsed = parse_request(raw)
            del buf[:REQ_SIZE]
            events.append(("ok", parsed, raw))
            continue
        if req_off > 0:
            if len(buf) >= RESP_SIZE and buf[0:3] == bytes([FRAME_HEADER[0], FRAME_HEADER[1], FRAME_TYPE]):
                del buf[:RESP_SIZE]
                continue
            del buf[:req_off]
            continue
        if len(buf) >= RESP_SIZE and buf[0:3] == bytes([FRAME_HEADER[0], FRAME_HEADER[1], FRAME_TYPE]):
            del buf[:RESP_SIZE]
            continue
        try:
            eb = buf.index(0xEB)
        except ValueError:
            buf.clear()
            return events
        if eb > 0:
            del buf[:eb]
            continue
        if len(buf) < 3:
            return events
        if buf[1] != 0x90 or buf[2] != FRAME_TYPE:
            del buf[0]
            continue
        if len(buf) < 6:
            return events
        length = (buf[4] << 8) | buf[5]
        if length == REQ_LEN:
            if len(buf) < REQ_SIZE:
                return events
            del buf[0]
            continue
        if len(buf) < RESP_SIZE:
            return events
        del buf[0]
    return events


def make_test_image(side: int, seed: int = 42) -> np.ndarray:
    """Deterministic grayscale square: gradient + black block (for pixel compare)."""
    if side <= 0 or side % 8 != 0:
        raise ValueError(f"side must be positive multiple of 8, got {side}")
    rng = np.random.default_rng(seed + side)
    arr = rng.integers(180, 256, size=(side, side), dtype=np.uint8)
    n = max(8, min(side // 4, 40))
    x = (seed * 7 + side) % max(1, side - n)
    y = (seed * 13 + side) % max(1, side - n)
    arr[y : y + n, x : x + n] = 0
    # stamp side into corner for debug
    arr[0, 0] = side & 0xFF
    arr[0, 1] = (side >> 8) & 0xFF
    return np.ascontiguousarray(arr, dtype=np.uint8)


def resolution_label(side: int, board: str) -> str:
    if board == "camera-v17":
        return str(int(side))
    return f"{int(side)}\u00d7{int(side)}"
