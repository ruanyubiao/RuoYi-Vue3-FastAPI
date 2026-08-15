"""wheel 安装布局：业务包应在 pgt.* 下，而不是 site-packages 顶层。"""

from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_pgt_packages_are_nested_under_pgt(monkeypatch):
    captured: dict = {}

    def fake_setup(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr('setuptools.setup', fake_setup)
    runpy.run_path(str(BACKEND_ROOT / 'setup.py'), run_name='pgt_setup_probe')
    names = captured.get('packages') or []
    package_dir = captured.get('package_dir') or {}
    assert package_dir.get('pgt') == '.'
    assert names[0] == 'pgt'
    assert 'pgt.module_payload' in names
    assert 'pgt.module_task' in names
    assert 'pgt.module_generator' in names
    assert 'pgt.module_admin' in names
    assert 'pgt.cli' in names
    assert 'pgt.config' in names
    assert 'module_payload' not in names
    assert 'cli' not in names
    assert all(n == 'pgt' or n.startswith('pgt.') for n in names)


def test_pyproject_entry_point_uses_pgt_cli():
    text = (BACKEND_ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    assert 'pgt.cli.main:main' in text
    assert 'ruoyi = "cli.main:main"' not in text
    assert 'package-dir' in text


def test_pgt_root_init_prepends_backend_dir():
    init_file = BACKEND_ROOT / '__init__.py'
    spec = importlib.util.spec_from_file_location('pgt_bootstrap_test', init_file)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    root = str(BACKEND_ROOT.resolve())
    assert root in sys.path
    assert (BACKEND_ROOT / 'module_payload').is_dir()
    assert (BACKEND_ROOT / 'module_task').is_dir()
