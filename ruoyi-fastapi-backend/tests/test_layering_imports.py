"""H4 分层守门：parsers/collectors 不得 import service，避免循环依赖回潮。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'module_payload'
_SKIP_DIRS = {'__pycache__'}


def _py_files(rel: str) -> list[Path]:
    base = ROOT / rel
    out: list[Path] = []
    for p in base.rglob('*.py'):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        out.append(p)
    return out


def _banned_hits(paths: list[Path], needle: str) -> list[str]:
    hits: list[str] = []
    for p in paths:
        text = p.read_text(encoding='utf-8')
        if needle in text:
            hits.append(str(p.relative_to(ROOT)).replace('\\', '/'))
    return hits


def test_parsers_do_not_import_service() -> None:
    hits = _banned_hits(_py_files('parsers'), 'module_payload.service')
    assert hits == [], f'parsers 不得 import service: {hits}'


def test_collectors_do_not_import_service() -> None:
    hits = _banned_hits(_py_files('collectors'), 'module_payload.service')
    assert hits == [], f'collectors 不得 import service: {hits}'


def test_parsers_do_not_import_collectors_redis_sync() -> None:
    hits = _banned_hits(_py_files('parsers'), 'collectors.redis_sync')
    assert hits == [], f'parsers 不得依赖 collectors.redis_sync: {hits}'


def test_pipeline_does_not_import_service() -> None:
    text = (ROOT / 'pipeline.py').read_text(encoding='utf-8')
    assert 'module_payload.service' not in text



def _production_py() -> list[Path]:
    out: list[Path] = []
    for p in ROOT.rglob('*.py'):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        out.append(p)
    return out


def test_no_inline_eb90_header_or_u8_checksum() -> None:
    """EB90 头与 8 位校验只定义在 constants；16 位工程帧校验不在此禁。"""
    import re

    header_pat = re.compile(r'FRAME_HEADER\s*=\s*bytes\(\[\s*0xEB')
    checksum_pat = re.compile(r'sum\([^)]*\)\s*&\s*0xFF\b')
    hits: list[str] = []
    for p in _production_py():
        rel = str(p.relative_to(ROOT)).replace('\\', '/')
        if rel == 'constants.py':
            continue
        text = p.read_text(encoding='utf-8')
        if header_pat.search(text):
            hits.append(f'{rel}: FRAME_HEADER = bytes([0xEB')
        if checksum_pat.search(text):
            hits.append(f'{rel}: sum(...) & 0xFF')
    assert hits == [], f'协议常量应引用 constants: {hits}'

