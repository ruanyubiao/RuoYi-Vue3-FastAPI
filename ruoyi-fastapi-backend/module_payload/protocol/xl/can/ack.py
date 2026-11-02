"""XL CAN 应答：期望与关联键来自 gpcan 组帧结果，识别来自解析结果的 msg_kind。"""

from __future__ import annotations

from typing import Any

from module_payload.protocol.ack import ACK_OK, EXPECT_ALWAYS, EXPECT_NONE, EXPECT_ON_ERROR, MSG_ACK_OK, AckHit, AckPolicy


def _hex(data: bytes) -> str:
    return ' '.join(f'{b:02X}' for b in data)


class XlCanAckPolicy(AckPolicy):
    """遥控、单播系统指令、间接指令：gpcan ``expect_ack`` / ``corr_id``。"""

    def describe_send(self, cmd: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, str]:
        _ = context
        expect = str(cmd.get('expect_ack') or EXPECT_NONE).strip()
        corr = str(cmd.get('corr_id') or '').strip()
        if expect not in (EXPECT_ALWAYS, EXPECT_ON_ERROR) or not corr:
            return {'expectAck': EXPECT_NONE, 'corrId': ''}
        return {'expectAck': expect, 'corrId': corr}

    def classify_rx(self, frame: Any) -> AckHit | None:
        if isinstance(frame, (bytes, bytearray)):
            return None
        packet_param = getattr(frame, 'packet_param', None) or {}
        if not isinstance(packet_param, dict):
            return None
        kind = str(packet_param.get('msg_kind') or '')
        if not kind.endswith('_ack'):
            return None
        data = bytes(getattr(frame, 'data', None) or b'')
        if kind == 'indirect_ack':
            nid = data[0] if data else 0
            corr = f'ind:{nid:02x}'
        else:
            apid = int(packet_param.get('apid') or 0) & 0xFFFF
            sec = int(packet_param.get('sec_header') or 0) & 0xFF
            corr = f'{apid:04x}:{sec:02x}'
        ok = str(packet_param.get('ack_status') or '') == ACK_OK
        return AckHit(
            corr_id=corr,
            status=ACK_OK if ok else 'error',
            message=MSG_ACK_OK if ok else '应答失败',
            hex_text=_hex(data),
        )
