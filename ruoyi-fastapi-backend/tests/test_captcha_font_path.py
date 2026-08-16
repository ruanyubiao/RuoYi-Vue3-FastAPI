"""验证码字体路径：包根优先，不依赖 cwd。关闭验证码时不生成图片。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from module_admin.service.captcha_service import CaptchaService, _captcha_font_path


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


@pytest.mark.asyncio
async def test_build_captcha_skips_image_when_disabled(monkeypatch):
    redis = AsyncMock()
    redis.get.side_effect = lambda key: 'false'
    generate = AsyncMock()
    monkeypatch.setattr(CaptchaService, 'create_captcha_image_service', generate)
    result = await CaptchaService.build_captcha_code(redis)
    generate.assert_not_called()
    redis.set.assert_not_called()
    assert result.captcha_enabled is False
    assert result.img == ''
    assert result.uuid == ''


@pytest.mark.asyncio
async def test_build_captcha_degrades_when_generation_fails(monkeypatch):
    redis = AsyncMock()
    redis.get.side_effect = lambda key: 'true'

    async def _boom():
        raise RuntimeError('font missing')

    monkeypatch.setattr(CaptchaService, 'create_captcha_image_service', _boom)
    result = await CaptchaService.build_captcha_code(redis)
    redis.set.assert_not_called()
    assert result.captcha_enabled is False
    assert result.img == ''

