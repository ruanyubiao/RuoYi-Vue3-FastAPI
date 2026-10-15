"""YJ216 RS422 遥控。

帧：EB90 | 指令码 | 有效数据长度 | 有效数据 | 16 位累加和。
长度为 0 时不带有效数据。校验和从指令码累加到有效数据。
"""

from __future__ import annotations

from typing import Any

from exceptions.exception import ServiceException
from module_payload.cfg.telecontrol_assembler import encode_component
from module_payload.constants import EB90_HEADER, checksum_u16
from module_payload.protocol.hooks import ProtocolBindings
from module_payload.protocol.yj216.rs422.tm import CMD_TO_TABLE

FRAME_HEADER = EB90_HEADER


def _command_byte(order: dict[str, Any], values: list[Any] | None) -> int:
    """取下拉指令码的第一个字节。"""
    components = order.get('component') or []
    if not components:
        raise ServiceException(message='指令没有组件')
    raw = values[0] if values else None
    encoded = encode_component(components[0], raw)
    if not encoded:
        raise ServiceException(message='指令码为空')
    return encoded[0]


def _payload(order: dict[str, Any], values: list[Any] | None) -> bytes:
    """指令码之后的组件编码为有效数据。没有后续组件则为空。"""
    components = order.get('component') or []
    vals = values or []
    data = bytearray()
    for index, comp in enumerate(components[1:], start=1):
        raw = vals[index] if index < len(vals) else None
        data.extend(encode_component(comp, raw))
    if len(data) > 0xFF:
        raise ServiceException(message=f'有效数据超过 255 字节: {len(data)}')
    return bytes(data)


def assemble(order: dict[str, Any], values: list[Any] | None = None, **_kwargs: Any) -> dict[str, Any]:
    """按表 2 组帧。有效数据来自指令码之后的组件；长度为 0 时不带数据字节。"""
    cmd = _command_byte(order, values)
    if cmd not in CMD_TO_TABLE:
        raise ServiceException(message=f'未知 RS422 指令码: 0x{cmd:02X}')
    data = _payload(order, values)
    body = bytes((cmd, len(data))) + data
    total = checksum_u16(body)
    frame = FRAME_HEADER + body + bytes((total >> 8, total & 0xFF))
    return {
        'hex': ' '.join(f'{b:02X}' for b in frame),
        'length': len(frame),
        'checksum': total,
        'tableKey': CMD_TO_TABLE[cmd],
        'tip': '',
        'lengthCorrected': False,
    }


BINDINGS = ProtocolBindings(assemble=assemble)
