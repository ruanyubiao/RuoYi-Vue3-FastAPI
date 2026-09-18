"""相机图像落盘路径：年/月/日 目录、相对路径回读、越界拒绝。"""

from __future__ import annotations

from datetime import datetime

import pytest

from module_payload.store import image_store


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr('module_payload.store.image_store.image_root', lambda: tmp_path)
    return tmp_path


def test_image_root_is_logs_data_image() -> None:
    assert image_store.image_root().name == 'image'
    assert image_store.image_root().parent.name == 'logs_data'


def test_build_camera_rel_path_layout() -> None:
    when = datetime(2026, 8, 12, 9, 30, 58, 463000)
    rel = image_store.build_camera_rel_path('serial:COM1', when)
    assert rel == 'camera/2026/08/12/COM1_20260812_093058_463.png'


def test_build_camera_rel_path_sanitizes_device() -> None:
    when = datetime(2026, 8, 12, 9, 30, 58, 463000)
    assert image_store.build_camera_rel_path('udp:127.0.0.1:66', when).endswith('66_20260812_093058_463.png')
    assert 'unknown_' in image_store.build_camera_rel_path('', when)


def test_save_and_resolve_roundtrip(root) -> None:
    rel = 'camera/2026/08/12/COM1_1.png'
    saved = image_store.save_image(rel, b'\x89PNG')
    assert saved.read_bytes() == b'\x89PNG'
    assert saved == root / 'camera' / '2026' / '08' / '12' / 'COM1_1.png'
    assert image_store.resolve_image_path(rel) == saved
    assert image_store.resolve_image_path('camera\\2026\\08\\12\\COM1_1.png') == saved


def test_resolve_rejects_escape_and_missing(root) -> None:
    image_store.save_image('camera/a.png', b'x')
    assert image_store.resolve_image_path('') is None
    assert image_store.resolve_image_path('  ') is None
    assert image_store.resolve_image_path('../../etc/passwd') is None
    assert image_store.resolve_image_path('camera/../../x.png') is None
    assert image_store.resolve_image_path('camera/missing.png') is None
    assert image_store.resolve_image_path('camera') is None  # 目录不是文件


def test_save_image_creates_nested_dirs(root) -> None:
    image_store.save_image('camera/2026/12/31/x.png', b'y')
    assert (root / 'camera' / '2026' / '12' / '31' / 'x.png').is_file()
