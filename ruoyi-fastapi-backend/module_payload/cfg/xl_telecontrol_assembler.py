"""XL 总线遥控组帧。应用层与 BIU 相同：不足 8 字节补齐，复合帧补校验。"""

from __future__ import annotations

from typing import Any

from module_payload.cfg.telecontrol_assembler import calc_checksum, encode_component

BROADCAST_FRAME_TYPES = {0x30, 0x1A}  # 广播帧类型
COMPLEX_FRAME_TYPES = {0x0F, 0x1A}  # 复合帧（带长度+校验）
SINGLE_SEND_TYPES = {0x0A, 0x00, 0x30}  # 单帧发送类型


def _finalize_buffer(buf: bytes) -> tuple[bytes, int, bool]:
    """补/校复合帧校验和，并判断是否广播。"""
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


def assemble_xl_order(components: list[dict[str, Any]], values: list[Any] | None = None) -> dict[str, Any]:
    """按组件顺序拼 XL 总线指令。单板和 CPA 指向不走这里。"""
    values = values or []
    parts = bytearray()
    for i, comp in enumerate(components):
        val = values[i] if i < len(values) else None
        parts.extend(encode_component(comp, val))
    buf, frame_type, all_channel = _finalize_buffer(bytes(parts))
    return {
        'hex': ' '.join(f'{b:02X}' for b in buf),
        'frameType': frame_type,
        'allChannel': all_channel,
        'isBroadcast': frame_type in BROADCAST_FRAME_TYPES,
        'length': len(buf),
    }
