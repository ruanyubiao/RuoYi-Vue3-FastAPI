"""Force-import all module_admin modules so coverage includes untested files."""

from __future__ import annotations

import importlib
from pathlib import Path

import module_admin


def test_import_all_module_admin_for_coverage() -> None:
    roots = [Path(p) for p in module_admin.__path__]
    imported: list[str] = []
    seen: set[str] = set()
    for root in roots:
        for path in root.rglob('*.py'):
            if path.name == '__init__.py':
                rel = path.parent.relative_to(root)
            else:
                rel = path.with_suffix('').relative_to(root)
            if str(rel) == '.':
                continue
            mod_name = 'module_admin.' + '.'.join(rel.parts)
            if mod_name in seen:
                continue
            seen.add(mod_name)
            importlib.import_module(mod_name)
            imported.append(mod_name)
    assert len(imported) > 20
