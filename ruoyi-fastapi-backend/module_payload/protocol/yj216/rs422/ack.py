"""YJ216 RS422：遥测请求错了才回短帧，对了则沉默。"""

from __future__ import annotations

from typing import Any

from module_payload.protocol.ack import ACK_ERROR, EXPECT_NONE, EXPECT_ON_ERROR, AckHit, AckPolicy

# 遥测数据请求：EB90 | FF | 长度 0 | sum16
_TM_REQ_TYPE = 0xFF
RS422_TM_REQ_CORR = 'rs422:tm_req'
MSG_NO_ENG_TM = '没有工程遥测数据'

_HEADER = bytes((0xEB, 0x90))
_TM_TYPE = 0xAA


def _frame_bytes(frame: Any) -> bytes | None:
    if isinstance(frame, (bytes, bytearray)):
        return bytes(frame)
    return None


class Yj216Rs422AckPolicy(AckPolicy):
    """只对遥测请求（类型码 ``0xFF``）声明 ``on_error``。"""

    def describe_send(self, cmd: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, str]:
        _ = context
        from module_payload.cfg.hex_text import hex_to_bytes

        try:
            raw = hex_to_bytes(str(cmd.get('hex') or ''))
        except Exception:
            return {'expectAck': EXPECT_NONE, 'corrId': ''}
        if len(raw) >= 3 and raw[:2] == _HEADER and raw[2] == _TM_REQ_TYPE:
            return {'expectAck': EXPECT_ON_ERROR, 'corrId': RS422_TM_REQ_CORR}
        return {'expectAck': EXPECT_NONE, 'corrId': ''}

    def classify_rx(self, frame: Any) -> AckHit | None:
        """数据区只有 ``0x00`` 的 AA 帧是错误应答，不进遥测。"""
        raw = _frame_bytes(frame)
        if raw is None or len(raw) < 8 or raw[:2] != _HEADER or raw[2] != _TM_TYPE:
            return None
        length = int.from_bytes(raw[3:5], 'big')
        if length != 1 or len(raw) != 8:
            return None
        if raw[5:6] != b'\x00':
            return None
        return AckHit(
            corr_id=RS422_TM_REQ_CORR,
            status=ACK_ERROR,
            message=MSG_NO_ENG_TM,
            hex_text=' '.join(f'{b:02X}' for b in raw),
        )
