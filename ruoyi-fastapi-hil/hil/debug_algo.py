# -*- coding: utf-8 -*-
"""调试页纯前端算法的 Python 对照（对齐 frontend vendor/crc.js + utils/numconv.js）。"""
from __future__ import annotations

import struct
from typing import Any

CRC_MODELS: list[dict[str, Any]] = [
    {"id": "crc8-autosar", "name": "CRC-8/AUTOSAR", "width": 8, "poly": 0x2F, "init": 0xFF, "refin": False, "refout": False, "xorout": 0xFF, "check": 0xDF},
    {"id": "crc8-sae-j1850", "name": "CRC-8/SAE-J1850", "width": 8, "poly": 0x1D, "init": 0xFF, "refin": False, "refout": False, "xorout": 0xFF, "check": 0x4B},
    {"id": "crc8-maxim-dow", "name": "CRC-8/MAXIM-DOW", "width": 8, "poly": 0x31, "init": 0x00, "refin": True, "refout": True, "xorout": 0x00, "check": 0xA1},
    {"id": "crc8-rohc", "name": "CRC-8/ROHC", "width": 8, "poly": 0x07, "init": 0xFF, "refin": True, "refout": True, "xorout": 0x00, "check": 0xD0},
    {"id": "crc16-modbus", "name": "CRC-16/MODBUS", "width": 16, "poly": 0x8005, "init": 0xFFFF, "refin": True, "refout": True, "xorout": 0x0000, "check": 0x4B37},
    {"id": "crc16-ccitt-false", "name": "CRC-16/CCITT-FALSE", "width": 16, "poly": 0x1021, "init": 0xFFFF, "refin": False, "refout": False, "xorout": 0x0000, "check": 0x29B1},
    {"id": "crc16-xmodem", "name": "CRC-16/XMODEM", "width": 16, "poly": 0x1021, "init": 0x0000, "refin": False, "refout": False, "xorout": 0x0000, "check": 0x31C3},
    {"id": "crc16-arc", "name": "CRC-16/ARC", "width": 16, "poly": 0x8005, "init": 0x0000, "refin": True, "refout": True, "xorout": 0x0000, "check": 0xBB3D},
    {"id": "crc32-iso-hdlc", "name": "CRC-32/ISO-HDLC", "width": 32, "poly": 0x04C11DB7, "init": 0xFFFFFFFF, "refin": True, "refout": True, "xorout": 0xFFFFFFFF, "check": 0xCBF43926},
    {"id": "crc32-iscsi", "name": "CRC-32C", "width": 32, "poly": 0x1EDC6F41, "init": 0xFFFFFFFF, "refin": True, "refout": True, "xorout": 0xFFFFFFFF, "check": 0xE3069283},
    {"id": "crc32-mpeg2", "name": "CRC-32/MPEG-2", "width": 32, "poly": 0x04C11DB7, "init": 0xFFFFFFFF, "refin": False, "refout": False, "xorout": 0x00000000, "check": 0x0376E6E7},
    {"id": "crc32-bzip2", "name": "CRC-32/BZIP2", "width": 32, "poly": 0x04C11DB7, "init": 0xFFFFFFFF, "refin": False, "refout": False, "xorout": 0xFFFFFFFF, "check": 0xFC891918},
]

SUM_MODELS = [
    {"id": "sum8", "name": "SUM8", "width": 8, "kind": "plain"},
    {"id": "sum16", "name": "SUM16", "width": 16, "kind": "plain"},
    {"id": "sum32", "name": "SUM32", "width": 32, "kind": "plain"},
    {"id": "sum8-cpl", "name": "SUM8-CPL", "width": 8, "kind": "cpl"},
    {"id": "sum16-cpl", "name": "SUM16-CPL", "width": 16, "kind": "cpl"},
    {"id": "sum8-not", "name": "SUM8-NOT", "width": 8, "kind": "not"},
    {"id": "sum16-not", "name": "SUM16-NOT", "width": 16, "kind": "not"},
]


def _reflect(value: int, bits: int) -> int:
    out = 0
    for i in range(bits):
        if value & (1 << i):
            out |= 1 << (bits - 1 - i)
    return out


def _mask(width: int) -> int:
    return (1 << width) - 1


def compute_crc(model: dict[str, Any], data: bytes) -> int:
    width = int(model["width"])
    poly = int(model["poly"])
    init = int(model["init"])
    refin = bool(model["refin"])
    refout = bool(model["refout"])
    xorout = int(model["xorout"])
    mask = _mask(width)
    top = 1 << (width - 1)
    crc = init & mask
    for b0 in data:
        b = b0 & 0xFF
        if refin:
            b = _reflect(b, 8)
        crc ^= b << (width - 8)
        crc &= mask
        for _ in range(8):
            if crc & top:
                crc = ((crc << 1) ^ poly) & mask
            else:
                crc = (crc << 1) & mask
    if refout:
        crc = _reflect(crc, width)
    return (crc ^ xorout) & mask


def compute_sum(kind: str, width: int, data: bytes) -> int:
    s = sum(data) & _mask(width)
    if kind == "cpl":
        return (-s) & _mask(width)
    if kind == "not":
        return (~s) & _mask(width)
    return s


def compute_checksum(algo_id: str, data: bytes) -> int:
    for m in SUM_MODELS:
        if m["id"] == algo_id:
            return compute_sum(m["kind"], m["width"], data)
    for m in CRC_MODELS:
        if m["id"] == algo_id:
            return compute_crc(m, data)
    raise KeyError(algo_id)


def format_crc_value(value: int, width: int) -> dict[str, str]:
    n = value & 0xFFFFFFFF
    hex_len = width // 4
    hx = f"{n:0{hex_len}X}"
    bin_s = f"{n:0{width}b}"
    bin_grouped = " ".join(bin_s[i : i + 8] for i in range(0, len(bin_s), 8)).strip()
    return {"hex": hx, "dec": str(n), "oct": oct(n)[2:], "bin": bin_grouped}


def bytes_to_hex_spaced(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def number_to_hex(text: str, type_id: str) -> dict[str, str]:
    """对齐 numconv.numberToHex：返回 input/be/le。"""
    specs = {
        "int8": (1, True, "int"),
        "uint8": (1, False, "int"),
        "int16": (2, True, "int"),
        "uint16": (2, False, "int"),
        "int24": (3, True, "int"),
        "uint24": (3, False, "int"),
        "int32": (4, True, "int"),
        "uint32": (4, False, "int"),
        "int48": (6, True, "int"),
        "uint48": (6, False, "int"),
        "int56": (7, True, "int"),
        "uint56": (7, False, "int"),
        "int64": (8, True, "int"),
        "uint64": (8, False, "int"),
        "float": (4, False, "float"),
        "double": (8, False, "float"),
    }
    size, signed, kind = specs[type_id]
    raw = str(text).strip()
    if kind == "float":
        val = float(raw)
        be = struct.pack(">f" if size == 4 else ">d", val)
    else:
        bits = size * 8
        v = int(raw, 10)
        if signed:
            min_v = -(1 << (bits - 1))
            max_v = (1 << (bits - 1)) - 1
        else:
            min_v, max_v = 0, (1 << bits) - 1
        if v < min_v or v > max_v:
            raise ValueError(f"out of range {min_v}..{max_v}")
        u = v if v >= 0 else v + (1 << bits)
        be = u.to_bytes(size, "big", signed=False)
    le = be[::-1]
    return {"input": raw, "be": bytes_to_hex_spaced(be), "le": bytes_to_hex_spaced(le)}


def convert_base(value: str, from_base: int, to_base: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/"
    raw = str(value).replace(" ", "")
    if not raw:
        raise ValueError("empty")
    dec = 0
    for i, ch in enumerate(raw):
        idx = alphabet[:from_base].find(ch)
        if idx < 0 and from_base <= 36:
            idx = alphabet[:from_base].find(ch.lower())
        if idx < 0:
            raise ValueError(ch)
        power = len(raw) - 1 - i
        dec += idx * (from_base**power)
    if dec == 0:
        return "0"
    out = ""
    while dec > 0:
        out = alphabet[dec % to_base] + out
        dec //= to_base
    return out.upper() if to_base <= 36 else out


def verify_crc_check_vectors() -> None:
    data = b"123456789"
    for m in CRC_MODELS:
        got = compute_crc(m, data)
        assert got == int(m["check"]), (m["id"], hex(got), hex(m["check"]))
