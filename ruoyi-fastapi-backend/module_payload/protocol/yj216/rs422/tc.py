"""YJ216 RS422 遥控。

帧：EB90 | 指令类型码(u8) | 有效数据长度(u16 BE) | 有效数据 | 校验和(u16 BE)。
长度为 0 时不带有效数据。校验和从指令类型码累加到有效数据（含长度字段）。

支持两种配置：
1. 整帧 fixed：唯一组件已是 EB90 开头完整帧时，直接下发（如遥测数据请求 EB 90 FF 00 00 00 FF）；
2. 结构化：首组件为类型码，其后为有效数据，由本模块补长度与 sum16。
"""

from __future__ import annotations

from typing import Any

from exceptions.exception import ServiceException
from module_payload.cfg.telecontrol_assembler import encode_component
from module_payload.constants import EB90_HEADER, checksum_u16
from module_payload.protocol.hooks import ProtocolBindings

FRAME_HEADER = EB90_HEADER


def _command_byte(order: dict[str, Any], values: list[Any] | None) -> int:
    """取第一个组件编码出的指令类型码字节。"""
    components = order.get('component') or []
    if not components:
        raise ServiceException(message='指令没有组件')
    raw = values[0] if values else None
    encoded = encode_component(components[0], raw)
    if not encoded:
        raise ServiceException(message='指令类型码为空')
    return encoded[0]


def _payload(order: dict[str, Any], values: list[Any] | None) -> bytes:
    """指令类型码之后的组件编码为有效数据。没有后续组件则为空。"""
    components = order.get('component') or []
    vals = values or []
    data = bytearray()
    for index, comp in enumerate(components[1:], start=1):
        raw = vals[index] if index < len(vals) else None
        data.extend(encode_component(comp, raw))
    if len(data) > 0xFFFF:
        raise ServiceException(message=f'有效数据超过 65535 字节: {len(data)}')
    return bytes(data)


def _fixed_complete_frame(order: dict[str, Any], values: list[Any] | None) -> bytes | None:
    """唯一 fixed 组件且内容已是 EB90 完整帧时返回该帧，否则 None。"""
    components = order.get('component') or []
    if len(components) != 1:
        return None
    comp = components[0]
    if str(comp.get('componentType') or 'fixed').lower() != 'fixed':
        return None
    raw = values[0] if values else None
    frame = encode_component(comp, raw)
    if len(frame) >= 5 and frame.startswith(FRAME_HEADER):
        return frame
    return None


def assemble(order: dict[str, Any], values: list[Any] | None = None, **_kwargs: Any) -> dict[str, Any]:
    """组帧：整帧 fixed 直出；否则类型码 + u16BE 长度 + 数据 + sum16BE。"""
    fixed = _fixed_complete_frame(order, values)
    if fixed is not None:
        return {
            'hex': ' '.join(f'{b:02X}' for b in fixed),
            'length': len(fixed),
            'checksum': int.from_bytes(fixed[-2:], 'big') if len(fixed) >= 2 else 0,
            'tip': '',
            'lengthCorrected': False,
        }

    cmd = _command_byte(order, values)
    data = _payload(order, values)
    body = bytes((cmd,)) + len(data).to_bytes(2, 'big') + data
    total = checksum_u16(body)
    frame = FRAME_HEADER + body + total.to_bytes(2, 'big')
    out: dict[str, Any] = {
        'hex': ' '.join(f'{b:02X}' for b in frame),
        'length': len(frame),
        'checksum': total,
        'tip': '',
        'lengthCorrected': False,
    }
    return out


BINDINGS = ProtocolBindings(assemble=assemble)
