"""SC-LINK41EP V1.7 图像下传应答组装器（0xD6，266 字节/帧）。

与 v1.6 差异：字节 4-5 为数据部分有效长度编码 L，有效字节数 = L + 1（1..256）。
"""

from __future__ import annotations

from module_payload.assemblers.camera_image_d6_common import (
    CameraImageD6AssemblerBase,
    parse_response_frame_v17,
    parse_valid_len_field,
    resolve_wh_v17,
)
from module_payload.constants import ASSEMBLER_CAMERA_IMAGE_D6_V17

__all__ = [
    'CameraImageD6V17Assembler',
    'parse_response_frame_v17',
    'parse_valid_len_field',
    'resolve_wh_v17',
]


class CameraImageD6V17Assembler(CameraImageD6AssemblerBase):
    """V1.7 D6 应答：按有效长度字段拼图。"""

    ASSEMBLER_ID = ASSEMBLER_CAMERA_IMAGE_D6_V17

    @property
    def _log_prefix(self) -> str:
        return 'assembler:camera_image_d6_v17'

    def _parse_response(self, raw: bytes) -> tuple[int, int, int, bytes] | None:
        return parse_response_frame_v17(raw)

    def _parse_failure_message(self) -> str:
        return (
            'D6 V1.7 应答帧校验失败、有效长度非法或格式错误'
            '（长度域若为 01 01，多半是 v1.6 相机，请改用 v1.6 界面）'
        )

    def _finish_pixels(self, pixels: bytearray) -> tuple[bytes, int, int] | None:
        width, height = resolve_wh_v17(len(pixels), self._resolution_hint)
        if width <= 0:
            self._drop(f'无法推断正方形边长 pixels={len(pixels)}')
            return None
        need = width * height
        if len(pixels) < need:
            self._drop(f'像素不足 {len(pixels)}<{need}')
            return None
        return bytes(pixels[:need]), width, height
