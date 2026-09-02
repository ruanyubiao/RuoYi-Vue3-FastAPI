"""SC-LINK41EP D6 图像下传：协议常量、帧解析与拼图状态机基类。

v1.6 / v1.7 共用帧头、帧标识按位判断与序号拼图逻辑；差异仅在应答解析与分辨率推断。
"""

from __future__ import annotations

import logging
import math
import sys
from abc import abstractmethod
from typing import Any

from module_payload.assemblers.base import AssembledPayload, BaseAssembler
from module_payload.constants import EB90_HEADER, checksum_u8

logger = logging.getLogger(__name__)

FRAME_HEADER = EB90_HEADER
FRAME_TYPE = 0xD6
FRAME_SIZE = 266
DATA_CHUNK_SIZE = 256

# 帧标识字节位：bit2 首帧 / bit0 尾帧 / bit1 中间帧；判断顺序 首→尾→中
_FRAME_ID_BIT_FIRST = 2
_FRAME_ID_BIT_MID = 1
_FRAME_ID_BIT_LAST = 0


def frame_id_encode(*, first: bool = False, mid: bool = False, last: bool = False) -> int:
    """组传图请求时的帧标识字节（按位写入）。"""
    fid = 0
    if first:
        fid |= 1 << _FRAME_ID_BIT_FIRST
    if mid:
        fid |= 1 << _FRAME_ID_BIT_MID
    if last:
        fid |= 1 << _FRAME_ID_BIT_LAST
    return fid & 0xFF


RESOLUTION_MAP = {
    '400×400': (400, 400),
    '400x400': (400, 400),
    '256×256': (256, 256),
    '256x256': (256, 256),
    '128×128': (128, 128),
    '128x128': (128, 128),
    '64×64': (64, 64),
    '64x64': (64, 64),
}

_PIXEL_TO_WH = {
    400 * 400: (400, 400),
    256 * 256: (256, 256),
    128 * 128: (128, 128),
    64 * 64: (64, 64),
}

calc_checksum = checksum_u8


def frame_id_is_first(frame_id: int) -> bool:
    """bit2=1 表示首帧。"""
    return bool((int(frame_id) >> _FRAME_ID_BIT_FIRST) & 1)


def frame_id_is_last(frame_id: int) -> bool:
    """bit0=1 表示尾帧。"""
    return bool((int(frame_id) >> _FRAME_ID_BIT_LAST) & 1)


def frame_id_is_mid(frame_id: int) -> bool:
    """bit1=1 表示中间帧。"""
    return bool((int(frame_id) >> _FRAME_ID_BIT_MID) & 1)


def classify_frame_id(frame_id: int) -> str:
    """按首帧→尾帧→中间帧归类；均无有效位则 unknown。"""
    fid = int(frame_id) & 0xFF
    if frame_id_is_first(fid):
        return 'first'
    if frame_id_is_last(fid):
        return 'last'
    if frame_id_is_mid(fid):
        return 'mid'
    return 'unknown'


def frame_id_is_valid(frame_id: int) -> bool:
    """至少一位有效。"""
    return classify_frame_id(frame_id) != 'unknown'


def plan_d6_image_requests(total_pixels: int) -> list[tuple[int, int]]:
    """按像素总数规划 D6 拉图请求序列，返回 [(frame_id, seq), ...]。

    整除时块数 = pixels//256（80×80 → 25 次）；有余数再向上取整。
    仅 1 包时同时置首位和尾位、seq=0（8×8 / 16×16）。
    多包：首帧 seq=0，中间帧 seq=1..N-2，尾帧 seq=N-1（最后一包必须带尾帧位）。
    """
    if total_pixels <= 0:
        return []
    full, rem = divmod(total_pixels, DATA_CHUNK_SIZE)
    chunks = full + (1 if rem else 0)
    if chunks == 1:
        return [(frame_id_encode(first=True, last=True), 0)]
    plan: list[tuple[int, int]] = [(frame_id_encode(first=True), 0)]
    for seq in range(1, chunks - 1):
        plan.append((frame_id_encode(mid=True), seq))
    plan.append((frame_id_encode(last=True), chunks - 1))
    return plan


def build_request_frame(frame_id: int, seq: int, image_no: int) -> bytes:
    """组一帧 D6 图像请求（不含粘包，调用方自行发送）。"""
    body = bytes(
        [
            FRAME_TYPE,
            frame_id & 0xFF,
            0x00,
            0x01,
            (seq >> 8) & 0xFF,
            seq & 0xFF,
            image_no & 0xFF,
        ]
    )
    return FRAME_HEADER + body + bytes([calc_checksum(body)])


def parse_response_frame_v16(data: bytes) -> tuple[int, int, int, bytes] | None:
    """v1.6：解析 266 字节应答，像素块固定 256 字节。"""
    if len(data) < FRAME_SIZE:
        return None
    if data[0:2] != FRAME_HEADER or data[2] != FRAME_TYPE:
        return None
    frame_id = data[3]
    seq = (data[6] << 8) | data[7]
    image_no = data[8]
    chunk = data[9:265]
    if calc_checksum(data[2:265]) != data[265]:
        return None
    return frame_id, seq, image_no, bytes(chunk)


def parse_valid_len_field(data: bytes) -> int | None:
    """v1.7：大端 2 字节 L → 有效像素字节数 L+1（1..256）。"""
    if len(data) < 6:
        return None
    l = ((data[4] & 0xFF) << 8) | (data[5] & 0xFF)
    valid = l + 1
    if valid < 1 or valid > 256:
        return None
    return valid


def parse_response_frame_v17(data: bytes) -> tuple[int, int, int, bytes] | None:
    """v1.7：解析 266 字节应答，按有效长度截取像素块。"""
    if len(data) < FRAME_SIZE:
        return None
    if data[0:2] != FRAME_HEADER or data[2] != FRAME_TYPE:
        return None
    if calc_checksum(data[2:265]) != data[265]:
        return None
    valid = parse_valid_len_field(data)
    if valid is None:
        return None
    frame_id = data[3]
    seq = (data[6] << 8) | data[7]
    image_no = data[8]
    chunk = data[9 : 9 + valid]
    return frame_id, seq, image_no, bytes(chunk)


def resolve_wh_v16(pixel_count: int, hint: str | None = None) -> tuple[int, int]:
    """v1.6：像素总数 → 宽高；hint 与数量一致才用，否则按已知分辨率表。"""
    if hint:
        wh = RESOLUTION_MAP.get(hint)
        if wh and wh[0] * wh[1] == pixel_count:
            return wh
    return _PIXEL_TO_WH.get(pixel_count, (0, 0))


def resolve_wh_v17(pixel_count: int, hint: str | None = None) -> tuple[int, int]:
    """v1.7：像素总数 → 正方形边长；hint 可为 n 或 n×n。"""
    if hint:
        s = str(hint).strip().replace('x', '×')
        if '×' in s:
            parts = s.split('×', 1)
            try:
                w, h = int(parts[0]), int(parts[1])
                if w == h and w * h == pixel_count:
                    return w, h
            except (TypeError, ValueError):
                pass
        else:
            try:
                n = int(s)
                if n > 0 and n * n == pixel_count:
                    return n, n
            except (TypeError, ValueError):
                pass
    n = math.isqrt(pixel_count)
    if n > 0 and n * n == pixel_count:
        return n, n
    return 0, 0


class CameraImageD6AssemblerBase(BaseAssembler):
    """D6 应答拼图状态机；子类提供帧解析与像素收束。"""

    def __init__(self, resolution: str | None = None) -> None:
        self._chunks: dict[int, bytes] = {}
        self._image_no: int | None = None
        self._last_seq: int = -1
        self._resolution_hint = resolution
        self._expected_final_seq: int | None = None
        self.last_errors: list[str] = []

    def set_expected_final_seq(self, seq: int | None) -> None:
        """规划中的最后一包序号；应答提前置尾帧位时须达到该序号才收束。"""
        self._expected_final_seq = int(seq) if seq is not None else None

    @property
    @abstractmethod
    def _log_prefix(self) -> str:
        """stderr / logger 前缀，如 assembler:camera_image_d6。"""

    @abstractmethod
    def _parse_response(self, raw: bytes) -> tuple[int, int, int, bytes] | None:
        """解析完整应答帧 → (frame_id, seq, image_no, chunk)。"""

    @abstractmethod
    def _parse_failure_message(self) -> str:
        """帧解析失败时的错误文案。"""

    @abstractmethod
    def _finish_pixels(self, pixels: bytearray) -> tuple[bytes, int, int] | None:
        """尾帧收齐后推断宽高并裁剪；失败时 _drop 并返回 None。"""

    def reset(self) -> None:
        self._clear_image()
        self._expected_final_seq = None
        self.last_errors.clear()

    def set_resolution(self, resolution: str | None) -> None:
        self._resolution_hint = resolution

    def _clear_image(self) -> None:
        self._chunks.clear()
        self._image_no = None
        self._last_seq = -1

    def _emit_warn(self, msg: str) -> None:
        logger.warning(msg)
        print(f'[{self._log_prefix}] {msg}', file=sys.stderr, flush=True)

    def _drop(self, reason: str) -> None:
        if self._chunks:
            msg = f'{reason}；丢弃未完成图像 frames={len(self._chunks)} lastSeq={self._last_seq}'
        else:
            msg = reason
        self.last_errors.append(msg)
        self._emit_warn(msg)
        self._clear_image()

    def take_errors(self) -> list[str]:
        errs = list(self.last_errors)
        self.last_errors.clear()
        return errs

    def feed(self, chunk: bytes) -> list[AssembledPayload]:
        done = self.accept_frame(chunk)
        return [done] if done is not None else []

    def accept_frame(self, raw: bytes) -> AssembledPayload | None:
        if not raw:
            return None
        parsed = self._parse_response(raw)
        if parsed is None:
            self.last_errors.append(self._parse_failure_message())
            self._emit_warn(self.last_errors[-1])
            return None
        frame_id, seq, image_no, data = parsed

        if self._image_no is None:
            if not frame_id_is_first(frame_id) and seq != 0:
                self._drop(f'非首帧开始: frameId=0x{frame_id:02X} seq={seq}')
                return None
            self._image_no = image_no
            self._last_seq = -1
        elif image_no != self._image_no:
            self._drop(f'图像序号变化 {self._image_no}->{image_no}')
            if frame_id_is_first(frame_id):
                self._image_no = image_no
                self._last_seq = -1
            else:
                return None

        expected = self._last_seq + 1
        if seq != expected:
            self._drop(f'序号不连续 expect={expected} got={seq}')
            if frame_id_is_first(frame_id) and seq == 0:
                self._image_no = image_no
                self._chunks[0] = data
                self._last_seq = 0
            return None

        self._chunks[seq] = data
        self._last_seq = seq

        if not frame_id_is_last(frame_id):
            return None
        if self._expected_final_seq is not None and seq < self._expected_final_seq:
            return None

        pixels = bytearray()
        for i in range(self._last_seq + 1):
            part = self._chunks.get(i)
            if part is None:
                self._drop(f'缺帧 seq={i}')
                return None
            pixels.extend(part)

        finished = self._finish_pixels(pixels)
        if finished is None:
            return None
        pixel_bytes, width, height = finished

        meta: dict[str, Any] = {
            'kind': 'image',
            'assemblerId': self.ASSEMBLER_ID,
            'width': width,
            'height': height,
            'imageNo': self._image_no,
            'frameCount': self._last_seq + 1,
            'format': 'raw',
        }
        payload = AssembledPayload(data=pixel_bytes, meta=meta)
        self._clear_image()
        return payload
