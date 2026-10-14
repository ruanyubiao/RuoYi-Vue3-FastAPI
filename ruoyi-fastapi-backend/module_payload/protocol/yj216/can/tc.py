"""YJ216 遥控组帧与 CAN 发送。短指令原样；复帧指令自带固定长度和 SUM。"""

from __future__ import annotations

from typing import Any

from module_payload.cfg.telecontrol_assembler import encode_component
from module_payload.constants import checksum_u8


def _is_empty_value(value: Any) -> bool:
    """None / 空白串视为未填。"""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def append_sum(body: bytes) -> bytes:
    """变参指令末字节 SUM。长度已写在指令里，校验覆盖这些字节。"""
    return body + bytes([checksum_u8(body)])


def payload_frames(payload: bytes) -> list[bytes]:
    """复帧指令已含固定长度。按 8 字节切 CAN 数据域，不再另加长度。"""
    data = bytes(payload)
    if len(data) <= 8:
        return [data]
    return [data[i : i + 8] for i in range(0, len(data), 8)]


def assemble(order: dict[str, Any], values: list[Any] | None = None, **_kwargs: Any) -> dict[str, Any]:
    """应用数据。短指令保持原长；整条指令 check 为「是」时追加 SUM。不做 8 字节补齐。"""
    values = values or []
    parts = bytearray()
    for i, comp in enumerate(order.get('component') or []):
        val = values[i] if i < len(values) else None
        if _is_empty_value(val):
            val = comp.get('defaultVal')
        parts.extend(encode_component(comp, val))
    buf = bytes(parts)
    if str(order.get('check') or '').strip() == '是':
        buf = append_sum(buf)
    return {
        'hex': ' '.join(f'{b:02X}' for b in buf),
        'frameType': buf[0] if buf else 0,
        'allChannel': False,
        'isBroadcast': False,
        'length': len(buf),
    }


def node_addr(_requested: Any) -> int:
    """线缆目标地址固定为 gpcan ``Yj216NodeAddr.LCD_PAYLOAD``，忽略页面传来的地址。"""
    from gpcan.protocol.yj216.defs import Yj216NodeAddr

    return int(Yj216NodeAddr.LCD_PAYLOAD)


def build_can_command(builder: Any, data: bytes, *, broadcast: bool) -> Any:
    """组 CAN 帧。不超过 8 字节走 gpcan；更长的指令已含长度，只按 8 字节切。"""
    raw = bytes(data)
    if len(raw) <= 8:
        if broadcast:
            return builder.build_broadcast(raw)
        return builder.build_telecommand(raw)

    from gpcan.protocol.can_protocol_base import ProtocolBuildResult
    from gpcan.protocol.yj216.defs import Yj216FrameType
    from gpcan.protocol.yj216.packet import Yj216PacketReq

    class _Slice:
        def split(self, logical: bytes) -> list[bytes]:
            return payload_frames(logical)

    frame_type = int(Yj216FrameType.DATA_BROADCAST if broadcast else Yj216FrameType.COMMAND_P2P)
    req = Yj216PacketReq(
        raw,
        frame_type=frame_type,
        broadcast=broadcast,
        send_param=builder.send_param,
        cable_param=builder.cable_param,
    )
    return ProtocolBuildResult(data=raw, frames=req.build(segmenter=_Slice()))
