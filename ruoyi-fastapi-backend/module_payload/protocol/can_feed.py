"""CAN 收包拼帧：用 gpcan ProtocolParser 把 CAN 硬件帧拼成业务载荷。

协议名取目录表里的 ``gpcan_protocol``；本文件不含任何总线族的规则。
"""

from __future__ import annotations

import importlib
from typing import Any

from module_payload.protocol.base import AssembledPayload, BaseAssembler


def _make_parser(gpcan_protocol: str) -> Any:
    """按 gpcan 协议名建 ``ProtocolParser``。gpcan 没有这个协议时抛 ValueError，不退回其它协议。"""
    name = (gpcan_protocol or '').strip().lower()
    try:
        module = importlib.import_module(f'gpcan.protocol.{name}') if name else None
    except ImportError:
        module = None
    if module is None or not hasattr(module, 'ProtocolParser'):
        raise ValueError(f'未知 CAN 协议: {gpcan_protocol}')
    return module.ProtocolParser({})


class CanFeedAssembler(BaseAssembler):
    """CAN 专属：feed_frames(CanRecvObj[]) → 完整 payload。子类由 ``can_feed_class`` 按目录表生成。"""

    FAMILY = ''
    GPCAN_PROTOCOL = ''
    ASSEMBLER_ID = ''

    def __init__(self) -> None:
        """按 GPCAN_PROTOCOL 构造 gpcan ProtocolParser。"""
        self._parser = _make_parser(self.GPCAN_PROTOCOL)
        self._errors: list[str] = []  # feed_frames 失败时暂存

    def feed(self, chunk: bytes) -> list[AssembledPayload]:
        """非 CAN 帧路径（如模拟注入整包）：视为已组装载荷透传。"""
        if not chunk:
            return []
        return [
            AssembledPayload(
                data=bytes(chunk),
                meta={'assemblerId': self.ASSEMBLER_ID, 'canProtocol': self.FAMILY},
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
                        'canProtocol': self.FAMILY,
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
            self._parser = _make_parser(self.GPCAN_PROTOCOL)
        self._errors = []


def can_feed_class(family: str, assembler_id: str, gpcan_protocol: str) -> type[CanFeedAssembler]:
    """目录表一行 → 该总线的组装器类。"""
    return type(
        f'CanFeedAssembler_{family}',
        (CanFeedAssembler,),
        {
            '__doc__': f'{assembler_id}：gpcan {gpcan_protocol} 拼帧。',
            'FAMILY': family,
            'GPCAN_PROTOCOL': gpcan_protocol,
            'ASSEMBLER_ID': assembler_id,
        },
    )
