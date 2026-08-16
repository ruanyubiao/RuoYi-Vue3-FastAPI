"""配置外部覆盖层：不拷贝、相同则删、包更新则改名为 .datetime.bak。"""

from __future__ import annotations

from pathlib import Path

from config import paths as cfg_paths


def _patch_dirs(monkeypatch, packaged: Path, external: Path) -> None:
    monkeypatch.setattr(cfg_paths, 'get_packaged_config_dir', lambda: packaged)
    monkeypatch.setattr(cfg_paths, 'get_external_config_dir', lambda: external)


def test_resolve_prefers_external(tmp_path, monkeypatch):
    packaged = tmp_path / 'pkg'
    external = tmp_path / 'ext'
    packaged.mkdir()
    external.mkdir()
    (packaged / 'a.json').write_text('{"datetime":"2026-01-01 00:00:00","v":1}', encoding='utf-8')
    (external / 'a.json').write_text('{"datetime":"2026-02-02 00:00:00","v":2}', encoding='utf-8')
    _patch_dirs(monkeypatch, packaged, external)
    path = cfg_paths.resolve_config_file('a.json')
    assert path == external / 'a.json'
    assert '"v":2' in path.read_text(encoding='utf-8')


def test_resolve_falls_back_to_packaged(tmp_path, monkeypatch):
    packaged = tmp_path / 'pkg'
    external = tmp_path / 'ext'
    packaged.mkdir()
    (packaged / 'a.json').write_text('{"datetime":"2026-01-01 00:00:00","v":1}', encoding='utf-8')
    _patch_dirs(monkeypatch, packaged, external)
    path = cfg_paths.resolve_config_file('a.json')
    assert path == packaged / 'a.json'
    assert not (external / 'a.json').exists()


def test_identical_external_deleted(tmp_path, monkeypatch):
    packaged = tmp_path / 'pkg'
    external = tmp_path / 'ext'
    packaged.mkdir()
    external.mkdir()
    body = '{"datetime":"2026-01-01 00:00:00","v":1}\n'
    (packaged / 'a.json').write_text(body, encoding='utf-8')
    (external / 'a.json').write_text(body, encoding='utf-8')
    _patch_dirs(monkeypatch, packaged, external)
    cfg_paths.reconcile_external_configs()
    assert not (external / 'a.json').exists()
    assert (packaged / 'a.json').is_file()


def test_older_external_renamed_bak(tmp_path, monkeypatch):
    packaged = tmp_path / 'pkg'
    external = tmp_path / 'ext'
    packaged.mkdir()
    external.mkdir()
    (packaged / 'aa.json').write_text('{"datetime":"2026-08-15 12:00:00","v":2}', encoding='utf-8')
    (external / 'aa.json').write_text('{"datetime":"2025-05-06 12:11:12","v":1}', encoding='utf-8')
    _patch_dirs(monkeypatch, packaged, external)
    cfg_paths.reconcile_external_configs()
    assert not (external / 'aa.json').exists()
    bak = external / 'aa.json.20250506121112.bak'
    assert bak.is_file()
    assert '"v":1' in bak.read_text(encoding='utf-8')
    assert cfg_paths.resolve_config_file('aa.json') == packaged / 'aa.json'


def test_newer_external_kept(tmp_path, monkeypatch):
    packaged = tmp_path / 'pkg'
    external = tmp_path / 'ext'
    packaged.mkdir()
    external.mkdir()
    (packaged / 'a.json').write_text('{"datetime":"2025-01-01 00:00:00","v":1}', encoding='utf-8')
    (external / 'a.json').write_text('{"datetime":"2026-08-15 12:00:00","v":9}', encoding='utf-8')
    _patch_dirs(monkeypatch, packaged, external)
    cfg_paths.reconcile_external_configs()
    assert (external / 'a.json').is_file()
    assert cfg_paths.resolve_config_file('a.json') == external / 'a.json'


def test_list_same_name_uses_external(tmp_path, monkeypatch):
    packaged = tmp_path / 'pkg'
    external = tmp_path / 'ext'
    packaged.mkdir()
    external.mkdir()
    (packaged / 'a.json').write_text('{"datetime":"2026-01-01 00:00:00","v":1}', encoding='utf-8')
    (external / 'a.json').write_text('{"datetime":"2026-02-02 00:00:00","v":2}', encoding='utf-8')
    (packaged / 'b.json').write_text('{"datetime":"2026-01-01 00:00:00","v":3}', encoding='utf-8')
    _patch_dirs(monkeypatch, packaged, external)
    rows = {r['name']: r for r in cfg_paths.list_config_file_info()}
    assert set(rows) == {'a.json', 'b.json'}
    assert rows['a.json']['layer'] == 'external'
    assert rows['b.json']['layer'] == 'packaged'
    assert cfg_paths.read_config_json('a.json')['v'] == 2
    assert cfg_paths.read_config_json('b.json')['v'] == 3


def test_save_writes_external_only(tmp_path, monkeypatch):
    packaged = tmp_path / 'pkg'
    external = tmp_path / 'ext'
    packaged.mkdir()
    (packaged / 'a.json').write_text('{"datetime":"2026-01-01 00:00:00","v":1}', encoding='utf-8')
    _patch_dirs(monkeypatch, packaged, external)
    cfg_paths.save_config_text('a.json', '{"datetime":"2026-08-15 00:00:00","v":9}\n')
    assert (packaged / 'a.json').read_text(encoding='utf-8').find('"v":1') >= 0
    assert cfg_paths.resolve_config_file('a.json') == external / 'a.json'
    assert cfg_paths.read_config_json('a.json')['v'] == 9


def test_no_copy_when_external_missing(tmp_path, monkeypatch):
    packaged = tmp_path / 'pkg'
    external = tmp_path / 'ext'
    packaged.mkdir()
    (packaged / 'a.json').write_text('{"datetime":"2026-01-01 00:00:00"}', encoding='utf-8')
    _patch_dirs(monkeypatch, packaged, external)
    cfg_paths.reconcile_external_configs()
    assert not external.exists() or not any(external.glob('*.json'))


def test_wheel_install_does_not_write_logs_into_site_packages(tmp_path, monkeypatch):
    pkg = tmp_path / 'Python' / 'Lib' / 'site-packages' / 'pgt'
    pkg.mkdir(parents=True)
    (pkg / '.env.dev').write_text('', encoding='utf-8')
    (pkg / 'pyproject.toml').write_text('', encoding='utf-8')
    data_home = tmp_path / 'AppData' / 'Local'
    monkeypatch.setattr(cfg_paths, 'get_package_root', lambda: pkg)
    monkeypatch.delenv('PGT_DATA_DIR', raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(data_home))
    monkeypatch.setattr(cfg_paths.os, 'name', 'nt')
    assert cfg_paths.is_installed_package(pkg) is True
    assert cfg_paths.is_source_checkout(pkg) is False
    data_dir = cfg_paths.get_runtime_data_dir()
    assert data_dir == (data_home / 'pgt').resolve()
    logs = cfg_paths.get_logs_dir()
    assert logs.is_relative_to(data_dir)
    assert 'site-packages' not in logs.parts


def test_source_checkout_still_writes_next_to_code(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg_paths, 'get_package_root', lambda: tmp_path)
    monkeypatch.delenv('PGT_DATA_DIR', raising=False)
    assert cfg_paths.is_installed_package(tmp_path) is False
    assert cfg_paths.get_runtime_data_dir() == tmp_path.resolve()
