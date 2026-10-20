"""强制导入 .coveragerc 中所有 source 包下的模块，使覆盖率分母完整。

``module_payload`` / ``module_admin`` 等目录是命名空间包（无 ``__init__.py``），
coverage.py 只会统计被导入过的文件；从未被测试导入的文件（例如此前的
``module_payload/controller/*``）会悄悄从分母中消失，导致覆盖率虚高。
本用例逐个导入这些模块，既把它们计入统计，也顺带做“可导入性”冒烟检查。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# 与 .coveragerc [run] source 保持一致
SOURCE_ROOTS = (
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
)

# 作为独立脚本 / 子进程入口运行、导入即有副作用的模块
SKIP_SUFFIXES = ('__main__',)
MIN_MODULES = 250


def _iter_module_names(root: str) -> list[str]:
    base = BACKEND_ROOT / root
    names: list[str] = []
    for path in sorted(base.rglob('*.py')):
        if '__pycache__' in path.parts or 'templates' in path.parts:
            continue
        rel = path.relative_to(BACKEND_ROOT).with_suffix('')
        parts = list(rel.parts)
        if parts[-1] == '__init__':
            parts = parts[:-1]
        if parts[-1] in SKIP_SUFFIXES:
            continue
        names.append('.'.join(parts))
    return names


def _try_import(name: str) -> str:
    try:
        importlib.import_module(name)
    except Exception as exc:  # pragma: no cover - 只在失败时进入
        return f'{type(exc).__name__}: {exc}'
    return ''


ALL_MODULES = [m for r in SOURCE_ROOTS for m in _iter_module_names(r)]


def test_source_module_inventory_is_not_empty() -> None:
    assert len(ALL_MODULES) > MIN_MODULES
    assert 'module_payload.controller.payload_telemetry_controller' in ALL_MODULES


@pytest.mark.parametrize('root', SOURCE_ROOTS)
def test_every_source_module_imports(root: str) -> None:
    failures: dict[str, str] = {}
    imported = 0
    for name in _iter_module_names(root):
        err = _try_import(name)
        if err:
            failures[name] = err
        else:
            imported += 1
    assert not failures, f'{root} 下有模块无法导入: {failures}'
    assert imported > 0
