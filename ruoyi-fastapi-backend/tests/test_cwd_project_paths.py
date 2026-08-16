"""后端包根解析不依赖任意 cwd；模板与 .env.* 发现走包内路径。"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from cli.metadata.option_specs import ENVIRONMENT_OPTION_SERVICE
from cli.runtime.base import RUNTIME_ENVIRONMENT
from config.paths import get_package_root, resolve_dotenv_path
from utils.template_util import TemplateInitializer


def test_get_backend_dir_falls_back_to_package_root_when_cwd_is_unrelated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert Path(RUNTIME_ENVIRONMENT.get_backend_dir()).resolve() == get_package_root().resolve()


def test_get_backend_dir_uses_cwd_when_it_looks_like_backend(tmp_path, monkeypatch):
    (tmp_path / 'app.py').write_text('', encoding='utf-8')
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'env.py').write_text('', encoding='utf-8')
    (tmp_path / 'cli').mkdir()
    monkeypatch.chdir(tmp_path)
    assert Path(RUNTIME_ENVIRONMENT.get_backend_dir()).resolve() == tmp_path.resolve()


def test_discover_env_names_reads_config_dir(tmp_path):
    (tmp_path / 'config').mkdir()
    (tmp_path / '.env.localroot').write_text('', encoding='utf-8')
    (tmp_path / 'config' / '.env.wheeleny').write_text('', encoding='utf-8')
    names = ENVIRONMENT_OPTION_SERVICE.discover_env_names(tmp_path)
    assert 'localroot' in names
    assert 'wheeleny' in names
    assert 'dev' in names


def test_jinja_templates_live_under_package_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env = TemplateInitializer.init_jinja2()
    expected = get_package_root() / 'module_generator' / 'templates'
    assert Path(env.loader.searchpath[0]).resolve() == expected.resolve()
    assert expected.is_dir()


def test_resolve_dotenv_prefers_cwd_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.env.foo').write_text('A=1', encoding='utf-8')
    assert resolve_dotenv_path('foo').resolve() == (tmp_path / '.env.foo').resolve()


def test_resolve_dotenv_falls_back_to_packaged_config(tmp_path, monkeypatch):
    cwd = tmp_path / 'cwd'
    pkg = tmp_path / 'pkg'
    cwd.mkdir()
    (pkg / 'config').mkdir(parents=True)
    (pkg / 'config' / '.env.prod').write_text('X=1', encoding='utf-8')
    monkeypatch.chdir(cwd)
    monkeypatch.setattr('config.paths.get_package_root', lambda: pkg)
    assert resolve_dotenv_path('prod').resolve() == (pkg / 'config' / '.env.prod').resolve()
