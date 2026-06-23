"""遥控指令组件组装（对齐 C++ TeleControlTableOrderWidget::getOrderData）。"""

from __future__ import annotations

import re
import struct
from typing import Any

BROADCAST_FRAME_TYPES = {0x30, 0x1A}
COMPLEX_FRAME_TYPES = {0x0F, 0x1A}
SINGLE_SEND_TYPES = {0x0A, 0x00, 0x30}


def _clean_hex(text: str) -> str:
    return re.sub(r'[^0-9A-Fa-f]', '', text or '')


def hex_to_bytes(text: str) -> bytes:
    s = _clean_hex(text)
    if not s:
        return b''
    if len(s) % 2:
        s = '0' + s
    return bytes.fromhex(s)


def encode_number(value: Any, data_type: str) -> bytes:
    dt = (data_type or 'INT16').upper()
    if value is None or value == '':
        value = 0
    if dt in ('INT8', 'BYTE'):
        return struct.pack('>b', int(value))
    if dt == 'UINT8':
        return struct.pack('>B', int(value) & 0xFF)
    if dt in ('INT16',):
        return struct.pack('>h', int(value))
    if dt in ('UINT16',):
        return struct.pack('>H', int(value) & 0xFFFF)
    if dt in ('INT24',):
        v = int(value)
        return v.to_bytes(3, byteorder='big', signed=True)
    if dt in ('UINT24',):
        v = int(value) & 0xFFFFFF
        return v.to_bytes(3, byteorder='big', signed=False)
    if dt in ('INT32',):
        return struct.pack('>i', int(value))
    if dt in ('UINT32',):
        return struct.pack('>I', int(value) & 0xFFFFFFFF)
    if dt == 'FLOAT':
        return struct.pack('>f', float(value))
    if dt == 'DOUBLE':
        return struct.pack('>d', float(value))
    return struct.pack('>h', int(value))


def encode_component(component: dict[str, Any], value: Any = None) -> bytes:
    ctype = (component.get('componentType') or 'fixed').lower()
    if ctype == 'fixed':
        return hex_to_bytes(component.get('defaultVal', ''))
    if ctype == 'number':
        return encode_number(value if value is not None else component.get('defaultVal', 0), component.get('dataType', ''))
    if ctype == 'select':
        raw = value if value is not None else component.get('defaultVal', '')
        if isinstance(raw, str) and not _clean_hex(raw):
            opts = component.get('options') or {}
            for k, label in opts.items():
                if label == raw or k == raw:
                    raw = k
                    break
        return hex_to_bytes(str(raw))
    if ctype == 'scientific':
        dt = (component.get('dataType') or 'DOUBLE').upper()
        val = float(value if value is not None else component.get('defaultVal', 0) or 0)
        return struct.pack('>f', val) if dt == 'FLOAT' else struct.pack('>d', val)
    if ctype == 'hex':
        width = len(_clean_hex(component.get('defaultVal', '')))
        raw = _clean_hex(str(value if value is not None else component.get('defaultVal', '')))
        if width and len(raw) < width:
            raw = raw.zfill(width)
        return hex_to_bytes(raw)
    return hex_to_bytes(str(value or ''))


def calc_checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def finalize_buffer(buf: bytes) -> tuple[bytes, int, bool]:
    if len(buf) < 8:
        raise ValueError('指令长度不足 8 字节')
    frame_type = buf[0] if len(buf) == 8 else buf[2]
    all_channel = frame_type in BROADCAST_FRAME_TYPES
    if frame_type in COMPLEX_FRAME_TYPES and len(buf) >= 4:
        data_len = (buf[0] << 8) | buf[1]
        if len(buf) == data_len + 2:
            buf = buf + bytes([calc_checksum(buf)])
        elif len(buf) == data_len + 3:
            expected = calc_checksum(buf[:-1])
            if expected != buf[-1]:
                raise ValueError('复合帧校验和错误')
    return buf, frame_type, all_channel


def assemble_order(components: list[dict[str, Any]], values: list[Any] | None = None) -> dict[str, Any]:
    values = values or []
    parts = bytearray()
    for i, comp in enumerate(components):
        val = values[i] if i < len(values) else None
        parts.extend(encode_component(comp, val))
    buf, frame_type, all_channel = finalize_buffer(bytes(parts))
    return {
        'hex': ' '.join(f'{b:02X}' for b in buf),
        'frameType': frame_type,
        'allChannel': all_channel,
        'isBroadcast': frame_type in BROADCAST_FRAME_TYPES,
        'length': len(buf),
    }


def is_broadcast_hex(hex_text: str) -> bool:
    try:
        buf = hex_to_bytes(hex_text)
        if len(buf) < 8:
            return False
        ft = buf[0] if len(buf) == 8 else buf[2]
        return ft in BROADCAST_FRAME_TYPES
    except Exception:
        return False
