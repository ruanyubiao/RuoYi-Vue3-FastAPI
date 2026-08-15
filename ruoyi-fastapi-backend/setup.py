"""setuptools 包装：把后端目录安装为 site-packages/pgt/，避免顶层污染。"""

from __future__ import annotations

from pathlib import Path

from setuptools import find_namespace_packages, setup

_HERE = Path(__file__).resolve().parent
_INCLUDE = [
    'cli*',
    'common*',
    'config*',
    'exceptions*',
    'middlewares*',
    'module_admin*',
    'module_generator*',
    'module_payload*',
    'module_task*',
    'sub_applications*',
    'utils*',
    'alembic*',
    'assets*',
    'sql*',
]
_EXCLUDE = ['test*', 'tests*', 'venv*', 'logs*', 'scripts*', 'docs*', 'whl*']


def pgt_packages() -> list[str]:
    found = find_namespace_packages(where=str(_HERE), include=_INCLUDE, exclude=_EXCLUDE)
    return ['pgt'] + [f'pgt.{name}' for name in found]


setup(
    packages=pgt_packages(),
    package_dir={'pgt': '.'},
)
