"""传输层组帧工具（固定帧头/定长/定尾/长度字段/分隔符/转义等），不含载荷解析。

与 commfw.protocol.framing 对应关系：
- FixedLenFrameBuffer ← fixed_length
- FixedHeaderLenFrameBuffer ← header_length
- FixedHeaderLenFieldFrameBuffer ← length_field
- FixedHeaderTrailerFrameBuffer / FixedHeaderLenTrailerFrameBuffer ← header_tail
- DelimiterFrameBuffer ← delimiter
- EscapeFrameBuffer ← escape
- CobsFrameBuffer ← cobs
- SlipFrameBuffer ← slip
- IdentityFrameBuffer ← identity
"""

from module_payload.framing.cobs_frame import CobsFrameBuffer, cobs_decode, cobs_encode
from module_payload.framing.delimiter_frame import DelimiterFrameBuffer
from module_payload.framing.escape_frame import EscapeFrameBuffer
from module_payload.framing.fixed_header_len_field_frame import FixedHeaderLenFieldFrameBuffer
from module_payload.framing.fixed_header_len_frame import FixedHeaderLenFrameBuffer
from module_payload.framing.fixed_header_len_trailer_frame import FixedHeaderLenTrailerFrameBuffer
from module_payload.framing.fixed_header_trailer_frame import FixedHeaderTrailerFrameBuffer
from module_payload.framing.fixed_len_frame import FixedLenFrameBuffer
from module_payload.framing.identity_frame import IdentityFrameBuffer
from module_payload.framing.slip_frame import SlipFrameBuffer, slip_decode, slip_encode

__all__ = [
    'FixedLenFrameBuffer',
    'FixedHeaderLenFrameBuffer',
    'FixedHeaderLenFieldFrameBuffer',
    'FixedHeaderTrailerFrameBuffer',
    'FixedHeaderLenTrailerFrameBuffer',
    'DelimiterFrameBuffer',
    'EscapeFrameBuffer',
    'CobsFrameBuffer',
    'SlipFrameBuffer',
    'IdentityFrameBuffer',
    'cobs_encode',
    'cobs_decode',
    'slip_encode',
    'slip_decode',
]
