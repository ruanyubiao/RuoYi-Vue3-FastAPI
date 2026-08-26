"""CAN 协议组装器：用 gpcan ProtocolParser 把 CAN 硬件帧拼成业务载荷。"""

from __future__ import annotations

from typing import Any

from module_payload.assemblers.base import AssembledPayload, BaseAssembler
from module_payload.constants import ASSEMBLER_CAN_BIU, ASSEMBLER_CAN_XL


def _make_parser(protocol: str):
    """protocol: biu | xl"""
    if protocol == 'xl':
        from gpcan.protocol.xl import ProtocolParser
    else:
        from gpcan.protocol.biu import ProtocolParser

    return ProtocolParser({})


class _CanProtocolAssembler(BaseAssembler):
    """CAN 专属：feed_frames(CanRecvObj[]) → 完整 payload。"""

    PROTOCOL_KEY = 'biu'
    ASSEMBLER_ID = ''

    def __init__(self) -> None:
        """按 PROTOCOL_KEY 构造 gpcan ProtocolParser。"""
        self._parser = _make_parser(self.PROTOCOL_KEY)
        self._errors: list[str] = []  # feed_frames 失败时暂存

    def feed(self, chunk: bytes) -> list[AssembledPayload]:
        """非 CAN 帧路径（如模拟注入整包）：视为已组装载荷透传。"""
        if not chunk:
            return []
        return [
            AssembledPayload(
                data=bytes(chunk),
                meta={'assemblerId': self.ASSEMBLER_ID, 'canProtocol': self.PROTOCOL_KEY},
            )
        ]

    def feed_frames(self, frames: list[Any]) -> list[AssembledPayload]:
        """喂入 CAN 硬件帧列表，取出 gpcan 拼好的业务载荷。"""
        if not frames:
            return []
        try:
            self._parser.feed(frames)
        except Exception as e:
            self._errors.append(f'{self.ASSEMBLER_ID} 组帧失败: {e}')
            return []
        out: list[AssembledPayload] = []
        while True:
            msg = self._parser.get_msg()
            if msg is None:
                break
            data = bytes(msg.payload or msg.data or b'')
            if not data:
                continue
            fields = dict(msg.fields or {})
            out.append(
                AssembledPayload(
                    data=data,
                    meta={
                        'assemblerId': self.ASSEMBLER_ID,
                        'canProtocol': self.PROTOCOL_KEY,
                        'unId': fields.get('un_id'),
                        'frameFlag': fields.get('n_frame_flag'),
                    },
                )
            )
        return out

    def take_errors(self) -> list[str]:
        """取出并清空组帧错误。"""
        errs = self._errors
        self._errors = []
        return errs

    def reset(self) -> None:
        """重置 gpcan 解析器状态；失败则重建。"""
        try:
            self._parser.reset()
        except Exception:
            self._parser = _make_parser(self.PROTOCOL_KEY)
        self._errors = []


class CanBiuAssembler(_CanProtocolAssembler):
    """BIU-CAN 协议组装器。"""

    ASSEMBLER_ID = ASSEMBLER_CAN_BIU
    PROTOCOL_KEY = 'biu'


class CanXlAssembler(_CanProtocolAssembler):
    """XL-CAN 协议组装器。"""

    ASSEMBLER_ID = ASSEMBLER_CAN_XL
    PROTOCOL_KEY = 'xl'
