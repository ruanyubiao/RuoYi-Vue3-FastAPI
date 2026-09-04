"""wheel 安装布局：业务包应在 pgt.* 下，而不是 site-packages 顶层。"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# 与 setup.py 中 _INCLUDE / _EXCLUDE 保持一致（测试侧只读断言，不执行 setup）。
_SETUP_INCLUDE_PREFIXES = (
    'cli',
    'common',
    'config',
    'exceptions',
    'middlewares',
    'module_admin',
    'module_generator',
    'module_payload',
    'module_task',
    'sub_applications',
    'utils',
    'alembic',
    'assets',
    'sql',
)
_SETUP_EXCLUDE_PREFIXES = ('test', 'tests', 'venv', 'logs', 'scripts', 'docs', 'whl')


def _top_level_dirs(root: Path) -> list[str]:
    names: list[str] = []
    for p in sorted(root.iterdir()):
        if not p.is_dir() or p.name.startswith('.'):
            continue
        if any(p.name == ex or p.name.startswith(ex) for ex in _SETUP_EXCLUDE_PREFIXES):
            continue
        if any(p.name == inc or p.name.startswith(inc) for inc in _SETUP_INCLUDE_PREFIXES):
            names.append(p.name)
    return names


def _setup_py_package_dir_and_prefix() -> tuple[dict[str, str], bool]:
    """解析 setup.py AST：package_dir 与 packages 是否统一加 pgt. 前缀。"""
    tree = ast.parse((BACKEND_ROOT / 'setup.py').read_text(encoding='utf-8'))
    package_dir: dict[str, str] = {}
    prefixes_packages = False
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not isinstance(call.func, ast.Name) or call.func.id != 'setup':
            continue
        for kw in call.keywords:
            if kw.arg == 'package_dir' and isinstance(kw.value, ast.Dict):
                for k, v in zip(kw.value.keys, kw.value.values, strict=True):
                    if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                        package_dir[str(k.value)] = str(v.value)
            if kw.arg == 'packages' and isinstance(kw.value, ast.Call):
                if isinstance(kw.value.func, ast.Name) and kw.value.func.id == 'pgt_packages':
                    prefixes_packages = True
    return package_dir, prefixes_packages


def test_pgt_packages_are_nested_under_pgt():
    """源码树 + setup.py 约定：安装名一律 pgt / pgt.*，禁止顶层业务包名。"""
    package_dir, prefixes = _setup_py_package_dir_and_prefix()
    assert package_dir.get('pgt') == '.'
    assert prefixes is True

    found = _top_level_dirs(BACKEND_ROOT)
    assert 'module_payload' in found
    assert 'module_task' in found
    assert 'module_generator' in found
    assert 'module_admin' in found
    assert 'cli' in found
    assert 'config' in found

    # 模拟 setup.pgt_packages() 的命名结果
    names = ['pgt'] + [f'pgt.{n}' for n in found]
    assert names[0] == 'pgt'
    assert 'pgt.module_payload' in names
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
