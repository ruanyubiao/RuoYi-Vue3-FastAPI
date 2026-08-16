"""验证码字体路径：包根优先，不依赖 cwd。"""

from __future__ import annotations

from pathlib import Path

from module_admin.service.captcha_service import _captcha_font_path


def test_captcha_font_uses_package_root_not_cwd(tmp_path, monkeypatch):
    font_dir = tmp_path / 'pkg' / 'assets' / 'font'
    font_dir.mkdir(parents=True)
    packaged = font_dir / 'Arial.ttf'
    packaged.write_bytes(b'\x00')
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    monkeypatch.setattr('module_admin.service.captcha_service.get_package_root', lambda: tmp_path / 'pkg')
    monkeypatch.chdir(cwd)
    assert _captcha_font_path() == packaged


def test_captcha_font_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr('module_admin.service.captcha_service.get_package_root', lambda: tmp_path)
    monkeypatch.delenv('WINDIR', raising=False)
    monkeypatch.setattr('module_admin.service.captcha_service.os.name', 'posix', raising=False)
    assert _captcha_font_path() is None
