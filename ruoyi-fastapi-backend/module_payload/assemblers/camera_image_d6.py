"""SC-LINK41EP v1.6 图像下传应答组装器（0xD6，266 字节/帧）。"""

from __future__ import annotations

from module_payload.assemblers.camera_image_d6_common import (
    DATA_CHUNK_SIZE,
    FRAME_HEADER,
    FRAME_SIZE,
    FRAME_TYPE,
    RESOLUTION_MAP,
    CameraImageD6AssemblerBase,
    _PIXEL_TO_WH,
    build_request_frame,
    calc_checksum,
    classify_frame_id,
    frame_id_encode,
    frame_id_is_first,
    frame_id_is_last,
    frame_id_is_mid,
    frame_id_is_valid,
    parse_response_frame_v16,
    plan_d6_image_requests,
    resolve_wh_v16,
)
from module_payload.constants import ASSEMBLER_CAMERA_IMAGE_D6

# 兼容旧 import 名
parse_response_frame = parse_response_frame_v16
resolve_wh = resolve_wh_v16


class CameraImageD6Assembler(CameraImageD6AssemblerBase):
    """接收完整 D6 应答帧，按序号拼完整灰度图（v1.6 固定 256B 数据区）。"""

    ASSEMBLER_ID = ASSEMBLER_CAMERA_IMAGE_D6

    @property
    def _log_prefix(self) -> str:
        return 'assembler:camera_image_d6'

    def _parse_response(self, raw: bytes) -> tuple[int, int, int, bytes] | None:
        return parse_response_frame_v16(raw)

    def _parse_failure_message(self) -> str:
        return 'D6 应答帧校验失败或格式错误'

    def _finish_pixels(self, pixels: bytearray) -> tuple[bytes, int, int] | None:
        width, height = resolve_wh_v16(len(pixels), self._resolution_hint)
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
        if width <= 0:
            self._drop(f'无法推断分辨率 pixels={len(pixels)}')
            return None
        return bytes(pixels), width, height
