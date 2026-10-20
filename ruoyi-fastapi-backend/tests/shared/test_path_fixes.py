"""跨平台路径修复的回归测试（Linux / macOS / Windows 均应通过；Windows 行为与原逻辑一致）。"""

from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from config import paths as cfg_paths
from exceptions.exception import ServiceException
from module_admin.service import server_service
from module_admin.service.common_service import CommonService
from module_payload.cfg.telecontrol_cfg import cfg_id_from_filename
from module_payload.fileplay.detect import parse_recv_file_start_ms
from module_payload.protocol.protocol_catalog import bus_family_by_telemetry_cfg, family_from_cfg_name
from module_payload.service.payload_fileplay_service import _safe_filename
from utils.path_util import has_parent_ref, is_absolute_any, is_within, windows_basename
from utils.upload_util import UploadUtil


# ---------- utils.path_util ----------
@pytest.mark.parametrize(
    ('raw', 'want'),
    [
        (r'C:\dir\a.bin', 'a.bin'),
        (r'\\host\share\x\b.txt', 'b.txt'),
        ('plain.txt', 'plain.txt'),
        ('', ''),
        (r'..\..\evil.json', 'evil.json'),
    ],
)
def test_windows_basename(raw: str, want: str) -> None:
    assert windows_basename(raw) == want


def test_has_parent_ref_and_absolute() -> None:
    assert has_parent_ref('a/../b')
    assert has_parent_ref(r'a\..\b')
    assert not has_parent_ref('a/..b/c')
    assert is_absolute_any('/etc/passwd')
    assert is_absolute_any(r'C:\Windows')
    assert is_absolute_any(r'\\host\share')
    assert not is_absolute_any('sub/a.txt')


def test_is_within(tmp_path: Path) -> None:
    (tmp_path / 'a').mkdir()
    assert is_within(tmp_path, tmp_path / 'a' / 'x')
    assert not is_within(tmp_path / 'a', tmp_path / 'b')


# ---------- 原有修复：文件回放文件名（增量兼容，原 Path(...).name 仍在） ----------
@pytest.mark.parametrize(
    ('raw', 'want'),
    [(r'C:\tmp\a_recv.txt', 'a_recv.txt'), ('/tmp/b.bin', 'b.bin'), ('c.bin', 'c.bin'), (r'd:\x\..\e.bin', 'e.bin')],
)
def test_fileplay_safe_filename_backslash(raw: str, want: str) -> None:
    assert _safe_filename(raw) == want


@pytest.mark.parametrize('bad', ['', '.', '..', 'C:\\dir\\..', '/'])
def test_fileplay_safe_filename_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        _safe_filename(bad)


# ---------- 原有修复：磁盘信息（Windows 仍用 device，其他平台用挂载点） ----------
def test_disk_usage_target_windows_keeps_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_service, 'os', SimpleNamespace(name='nt'))
    part = SimpleNamespace(device='C:\\', mountpoint='C:\\')
    assert server_service._disk_usage_target(part) == 'C:\\'


def test_disk_usage_target_posix_uses_mountpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_service, 'os', SimpleNamespace(name='posix'))
    assert server_service._disk_usage_target(SimpleNamespace(device='/dev/sda1', mountpoint='/')) == '/'
    assert server_service._disk_usage_target(SimpleNamespace(device='/dev/x', mountpoint='')) == '/dev/x'


# ---------- 原有修复：Click 补全（原 None 分支保留） ----------
def test_powershell_completion_both_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    from click import shell_completion

    from cli.completion import shells

    registry = dict(shell_completion._available_shells)
    try:
        shell_completion._available_shells.pop(shells.PowerShellComplete.name, None)
        shells.ensure_custom_completion_classes_registered()  # 原分支：未注册 → 注册
        assert shell_completion.get_completion_class('powershell') is shells.PowerShellComplete

        class _ClickBuiltin(shell_completion.ShellComplete):
            name = 'powershell'

        shell_completion._available_shells['powershell'] = _ClickBuiltin
        shells.ensure_custom_completion_classes_registered()  # 新分支：被 Click 自带类占用 → 覆盖
        assert shell_completion.get_completion_class('powershell') is shells.PowerShellComplete
    finally:
        shell_completion._available_shells.clear()
        shell_completion._available_shells.update(registry)


# ---------- 新修复：通用上传 / 下载 ----------
class _FakeUpload:
    def __init__(self, filename: str, data: bytes = b'abc') -> None:
        self.filename = filename
        self._buf = io.BytesIO(data)

    async def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)


@pytest.fixture
def upload_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    from config.env import UploadConfig

    up, down = tmp_path / 'up', tmp_path / 'down'
    up.mkdir()
    down.mkdir()
    monkeypatch.setattr(UploadConfig, 'UPLOAD_PATH', str(up))
    monkeypatch.setattr(UploadConfig, 'DOWNLOAD_PATH', str(down))
    return up, down


@pytest.mark.parametrize('client_name', [r'C:\Users\me\Pictures\photo.png', '../../photo.png', 'photo.png'])
def test_upload_strips_client_directories(upload_dirs: tuple[Path, Path], client_name: str) -> None:
    up, _ = upload_dirs
    request = SimpleNamespace(base_url='http://h/')
    res = asyncio.run(CommonService.upload_service(request, _FakeUpload(client_name)))
    new_name = res.result.new_file_name
    assert new_name.startswith('photo_') and new_name.endswith('.png')
    assert '\\' not in new_name and '/' not in new_name
    written = list(up.rglob('*.png'))
    assert len(written) == 1 and is_within(up, written[0])


def test_upload_extension_case_insensitive() -> None:
    assert UploadUtil.check_file_extension(_FakeUpload('A.PNG'))
    assert UploadUtil.check_file_extension(_FakeUpload('b.png'))
    assert not UploadUtil.check_file_extension(_FakeUpload('c.EXE'))


def test_download_rejects_absolute_paths(upload_dirs: tuple[Path, Path]) -> None:
    _, down = upload_dirs
    (down / 'ok.txt').write_text('x')
    res = asyncio.run(CommonService.download_services(SimpleNamespace(add_task=lambda *a: None), 'ok.txt', False))
    assert res.is_success
    for bad in ['/etc/passwd', r'C:\Windows\win.ini', r'\\host\share\a.txt', '../x.txt']:
        with pytest.raises(ServiceException):
            asyncio.run(CommonService.download_services(SimpleNamespace(add_task=lambda *a: None), bad, False))


def test_download_resource_rejects_parent_dirs(upload_dirs: tuple[Path, Path]) -> None:
    from config.env import UploadConfig

    up, _ = upload_dirs
    name = f'a_20260101120000{UploadConfig.UPLOAD_MACHINE}001.png'
    (up / 'upload').mkdir()
    (up / 'upload' / name).write_bytes(b'x')
    ok = asyncio.run(CommonService.download_resource_services(f'{UploadConfig.UPLOAD_PREFIX}/upload/{name}'))
    assert ok.is_success
    for bad in [f'{UploadConfig.UPLOAD_PREFIX}/../upload/{name}', f'{UploadConfig.UPLOAD_PREFIX}/x\\..\\..\\{name}']:
        with pytest.raises(ServiceException):
            asyncio.run(CommonService.download_resource_services(bad))


# ---------- 新修复：配置 / 协议 / 回放文件名 ----------
def test_cfg_id_from_windows_path_and_case() -> None:
    assert cfg_id_from_filename('XL-RKDJ-TeleControlCfg.json') == 'xl-rkdj-tc'
    assert cfg_id_from_filename(r'D:\cfg\XL-RKDJ-TeleControlCfg.json') == 'xl-rkdj-tc'
    assert cfg_id_from_filename('xl-rkdj-telecontrolcfg.json') == 'xl-rkdj-tc'


def test_protocol_catalog_windows_paths() -> None:
    assert family_from_cfg_name(r'C:\cfg\XL-Camera-TeleMetryCfg.json') == 'xl'
    row = bus_family_by_telemetry_cfg('XL-TeleMetryCfg.json')
    if row is not None:
        assert bus_family_by_telemetry_cfg('D:\\cfg\\' + row.telemetry_cfg) == row


def test_recv_file_start_ms_windows_path() -> None:
    posix = parse_recv_file_start_ms('/raw/COM1_20260101_120000_123_recv.bin')
    assert posix > 0
    assert parse_recv_file_start_ms(r'D:\raw\COM1_20260101_120000_123_recv.bin') == posix
    assert parse_recv_file_start_ms(r'D:\20250101_000000_1\COM1_recv.bin') == 0  # 目录里的时间戳不应被误用


def test_config_paths_basename_windows() -> None:
    assert cfg_paths._safe_cfg_name(r'..\..\evil.json') == 'evil.json'
    assert cfg_paths.resolve_data_file(r'C:\x\golden.bin') == cfg_paths.get_packaged_data_dir() / 'golden.bin'
    assert cfg_paths.resolve_data_file('golden.bin').parent == cfg_paths.get_packaged_data_dir()


def test_payload_config_loader_windows_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from module_payload.cfg import payload_config_loader as loader_mod

    seen: list[str] = []

    def fake_read(name: str) -> dict:
        seen.append(name)
        return {'ok': 1}

    monkeypatch.setattr('config.paths.read_config_json', fake_read)
    assert loader_mod.PayloadConfigLoader._load_json(Path(r'E:\cfg\XL-TeleMetryCfg.json')) == {'ok': 1}
    assert seen == ['XL-TeleMetryCfg.json']
    assert os.sep not in seen[0]
