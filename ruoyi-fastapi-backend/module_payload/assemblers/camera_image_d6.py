"""SC-LINK41EP 图像下传应答组装器（0xD6，266 字节/帧）。

只做协议层：校验完整帧、按序号拼像素。不读串口、不处理粘包。
完整帧由采集插件经 FixedHeaderLenFrameBuffer 拆出后传入 feed()。
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from module_payload.assemblers.base import AssembledPayload, BaseAssembler
from module_payload.constants import ASSEMBLER_CAMERA_IMAGE_D6

logger = logging.getLogger(__name__)

FRAME_HEADER = bytes([0xEB, 0x90])
FRAME_TYPE = 0xD6
FRAME_ID_FIRST = 0x04
FRAME_ID_MID = 0x02
FRAME_ID_LAST = 0x01
FRAME_SIZE = 266
DATA_CHUNK_SIZE = 256

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


def calc_checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def build_request_frame(frame_id: int, seq: int, image_no: int) -> bytes:
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


def parse_response_frame(data: bytes) -> tuple[int, int, int, bytes] | None:
    """解析 266 字节应答：返回 (frame_id, seq, image_no, chunk) 或 None。"""
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


def resolve_wh(pixel_count: int, hint: str | None = None) -> tuple[int, int]:
    if hint:
        wh = RESOLUTION_MAP.get(hint)
        if wh and wh[0] * wh[1] == pixel_count:
            return wh
    return _PIXEL_TO_WH.get(pixel_count, (0, 0))


def _emit_warn(msg: str) -> None:
    logger.warning(msg)
    print(f'[assembler:camera_image_d6] {msg}', file=sys.stderr, flush=True)


class CameraImageD6Assembler(BaseAssembler):
    """接收完整 D6 应答帧，按序号拼完整灰度图。"""

    ASSEMBLER_ID = ASSEMBLER_CAMERA_IMAGE_D6

    def __init__(self, resolution: str | None = None) -> None:
        self._chunks: dict[int, bytes] = {}
        self._image_no: int | None = None
        self._last_seq: int = -1
        self._resolution_hint = resolution
        self.last_errors: list[str] = []

    def reset(self) -> None:
        self._clear_image()
        self.last_errors.clear()

    def set_resolution(self, resolution: str | None) -> None:
        self._resolution_hint = resolution

    def _clear_image(self) -> None:
        self._chunks.clear()
        self._image_no = None
        self._last_seq = -1

    def _drop(self, reason: str) -> None:
        if self._chunks:
            msg = f'{reason}；丢弃未完成图像 frames={len(self._chunks)} lastSeq={self._last_seq}'
        else:
            msg = reason
        self.last_errors.append(msg)
        _emit_warn(msg)
        self._clear_image()

    def take_errors(self) -> list[str]:
        errs = list(self.last_errors)
        self.last_errors.clear()
        return errs

    def feed(self, chunk: bytes) -> list[AssembledPayload]:
        """喂入一帧完整 D6 应答（266B）。粘包拆帧由插件完成。"""
        done = self.accept_frame(chunk)
        return [done] if done is not None else []

    def accept_frame(self, raw: bytes) -> AssembledPayload | None:
        """接受一帧完整应答；凑齐整图时返回 AssembledPayload，否则 None。"""
        if not raw:
            return None
        parsed = parse_response_frame(raw)
        if parsed is None:
            self.last_errors.append('D6 应答帧校验失败或格式错误')
            _emit_warn(self.last_errors[-1])
            return None
        frame_id, seq, image_no, data = parsed

        if self._image_no is None:
            if frame_id != FRAME_ID_FIRST and seq != 0:
                self._drop(f'非首帧开始: frameId=0x{frame_id:02X} seq={seq}')
                return None
            self._image_no = image_no
            self._last_seq = -1
        elif image_no != self._image_no:
            self._drop(f'图像序号变化 {self._image_no}->{image_no}')
            if frame_id == FRAME_ID_FIRST:
                self._image_no = image_no
                self._last_seq = -1
            else:
                return None

        expected = self._last_seq + 1
        if seq != expected:
            self._drop(f'序号不连续 expect={expected} got={seq}')
            if frame_id == FRAME_ID_FIRST and seq == 0:
                self._image_no = image_no
                self._chunks[0] = data
                self._last_seq = 0
            return None

        self._chunks[seq] = data
        self._last_seq = seq

        if frame_id != FRAME_ID_LAST:
            return None

        pixels = bytearray()
        for i in range(self._last_seq + 1):
            part = self._chunks.get(i)
            if part is None:
                self._drop(f'缺帧 seq={i}')
                return None
            pixels.extend(part)

        wh = resolve_wh(len(pixels), self._resolution_hint)
        width, height = wh
        if width <= 0:
            for n, size in sorted(_PIXEL_TO_WH.items(), reverse=True):
                if len(pixels) >= n:
                    width, height = size
                    pixels = pixels[:n]
                    break
        else:
            need = width * height
            if len(pixels) < need:
                self._drop(f'像素不足 {len(pixels)}<{need}')
                return None
            pixels = pixels[:need]

        meta: dict[str, Any] = {
            'kind': 'image',
            'assemblerId': self.ASSEMBLER_ID,
            'width': width,
            'height': height,
            'imageNo': self._image_no,
            'frameCount': self._last_seq + 1,
            'format': 'raw',
        }
        payload = AssembledPayload(data=bytes(pixels), meta=meta)
        self._clear_image()
        return payload
