"""相机图像落盘：``logs_data/image/camera/年/月/日/{端口}_{时间戳}.png``。

Redis 只存相对路径（正斜杠），图像本体在磁盘；接口按相对路径回读，
路径必须落在 ``logs_data/image`` 下，拒绝越界。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

CAMERA_DIR = 'camera'


def image_root() -> Path:
    """图像根目录：``logs_data/image``。"""
    from config.paths import get_logs_data_dir

    return get_logs_data_dir() / 'image'


def _safe_name(text: str) -> str:
    """设备名转文件名片段：``serial:COM1`` → ``COM1``。"""
    raw = str(text or '').strip()
    if ':' in raw:
        raw = raw.rsplit(':', 1)[-1]
    out = re.sub(r'[^0-9A-Za-z._\-]+', '_', raw)
    return out[:60] or 'unknown'


def build_camera_rel_path(device_id: str, when: datetime | None = None) -> str:
    """生成相对路径：``camera/2026/08/12/COM1_20260812_093058_463.png``。"""
    now = when or datetime.now()
    stamp = now.strftime('%Y%m%d_%H%M%S_%f')[:-3]  # 毫秒
    name = f'{_safe_name(device_id)}_{stamp}.png'
    return f'{CAMERA_DIR}/{now:%Y}/{now:%m}/{now:%d}/{name}'


def save_image(rel_path: str, blob: bytes) -> Path:
    """按相对路径写文件（自动建目录），返回绝对路径。"""
    target = image_root().joinpath(*str(rel_path).replace('\\', '/').split('/'))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)
    return target


def save_gray_png(
    device_id: str,
    width: int,
    height: int,
    pixels: bytes,
    *,
    compress_level: int = 1,
) -> str:
    """灰度像素落 PNG，返回相对路径；无 Pillow 时存裸灰度。"""
    need = int(width) * int(height)
    raw = bytes(pixels or b'')[:need]
    try:
        import io

        from PIL import Image

        img = Image.frombytes('L', (int(width), int(height)), raw)
        buf = io.BytesIO()
        img.save(buf, format='PNG', compress_level=compress_level)
        blob = buf.getvalue()
    except Exception:
        blob = raw
    rel_path = build_camera_rel_path(device_id)
    save_image(rel_path, blob)
    return rel_path


def resolve_image_path(rel_path: str) -> Path | None:
    """相对路径 → 绝对路径；越界、空、不存在均返回 None。"""
    raw = str(rel_path or '').strip().replace('\\', '/')
    if not raw:
        return None
    parts = [p for p in raw.split('/') if p not in ('', '.')]
    if any(p == '..' for p in parts) or not parts:
        return None
    root = image_root()
    target = root.joinpath(*parts)
    try:
        target.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    if not target.is_file():
        return None
    return target


__all__ = [
    'build_camera_rel_path',
    'image_root',
    'resolve_image_path',
    'save_gray_png',
    'save_image',
]
