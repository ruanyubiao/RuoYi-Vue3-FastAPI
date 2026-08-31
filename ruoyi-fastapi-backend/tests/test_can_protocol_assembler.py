"""CAN 协议组装器 feed_frames 行为。"""

from __future__ import annotations

from unittest.mock import MagicMock

from module_payload.assemblers.can_protocol import CanBiuAssembler


class _FakeMsg:
    def __init__(self, payload: bytes, fields: dict | None = None) -> None:
        self.payload = payload
        self.data = payload
        self.fields = fields or {}


def test_feed_frames_empty() -> None:
    asm = CanBiuAssembler()
    assert asm.feed_frames([]) == []


def test_feed_frames_maps_parser_messages() -> None:
    asm = CanBiuAssembler()
    asm._parser = MagicMock()
    asm._parser.get_msg.side_effect = [
        _FakeMsg(b'\x01\x02', {'un_id': 1, 'n_frame_flag': 0}),
        None,
    ]
    out = asm.feed_frames([MagicMock()])
    assert len(out) == 1
    assert out[0].data == b'\x01\x02'
    assert out[0].meta['unId'] == 1
    assert out[0].meta['frameFlag'] == 0


def test_feed_frames_parser_error_recorded() -> None:
    asm = CanBiuAssembler()
    asm._parser = MagicMock()
    asm._parser.feed.side_effect = RuntimeError('boom')
    assert asm.feed_frames([MagicMock()]) == []
    assert asm.take_errors()
    assert asm.take_errors() == []


def test_feed_passthrough_bytes() -> None:
    asm = CanBiuAssembler()
    out = asm.feed(b'\xaa\xbb')
    assert len(out) == 1
    assert out[0].data == b'\xaa\xbb'
