"""地检平台版本：本地 backend + frontend vs 被测工控机。

- 本地 backend：ruoyi-fastapi-backend/version.py 的 appVersion（文本解析，不 exec）
- 本地 frontend：ruoyi-fastapi-frontend/version.js 的 appVersion（文本解析，不 import）
- 被测机：GET /payload/device/version → data.appVersion
三者须一致。
"""
from __future__ import annotations

import re
from pathlib import Path

from hil.config import BACKEND_ROOT, CONFIG, FRONTEND_ROOT

_BACKEND_VERSION_FILE = BACKEND_ROOT / 'version.py'
_FRONTEND_VERSION_FILE = FRONTEND_ROOT / 'version.js'
# 同时匹配 py: appVersion = 'x' 与 js: export const appVersion = 'x'
_APP_VERSION_RE = re.compile(
    r"(?m)^\s*(?:export\s+const\s+)?appVersion\s*=\s*['\"]([^'\"]+)['\"]"
)


def _parse_app_version(path: Path, label: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(f'本地{label}版本文件不存在: {path}')
    text = path.read_text(encoding='utf-8')
    m = _APP_VERSION_RE.search(text)
    if not m:
        raise ValueError(f'无法从 {path} 解析 appVersion=...')
    return m.group(1).strip()


def local_backend_version(path: Path | None = None) -> str:
    return _parse_app_version(path or _BACKEND_VERSION_FILE, ' backend')


def local_frontend_version(path: Path | None = None) -> str:
    return _parse_app_version(path or _FRONTEND_VERSION_FILE, ' frontend')


def local_app_version(path: Path | None = None) -> str:
    """兼容旧名：等同 local_backend_version。"""
    return local_backend_version(path)


def dut_app_version(api) -> str:
    data = api.version()
    if isinstance(data, dict):
        v = data.get('appVersion') or data.get('version')
    else:
        v = data
    if not v:
        raise RuntimeError(f'被测机 /payload/device/version 未返回 appVersion: {data!r}')
    return str(v).strip()


def record_versions(backend: str, frontend: str | None, dut: str | None) -> None:
    CONFIG.set_versions(backend, frontend, dut)


def versions_summary_line() -> str:
    b, f, d = CONFIG.version_backend, CONFIG.version_frontend, CONFIG.version_dut
    if not b and not f and d is None:
        return '版本 backend=- frontend=- 被测=-（本分组未核对）'
    if d is None:
        return f'版本 backend={b or "-"} frontend={f or "-"} 被测=-（未拉取）'
    ok = '一致' if b and f and b == f == d else '不一致'
    return f'版本 backend={b or "-"} frontend={f or "-"} 被测={d or "-"}（{ok}）'


def assert_local_matches_dut(api) -> tuple[str, str, str]:
    """比对 backend / frontend / 被测；不一致抛 AssertionError（含三边版本号）。"""
    backend = local_backend_version()
    frontend = local_frontend_version()
    dut = dut_app_version(api)
    record_versions(backend, frontend, dut)
    if not (backend == frontend == dut):
        raise AssertionError(
            f'版本不一致：本地 backend={backend}（{_BACKEND_VERSION_FILE}），'
            f'本地 frontend={frontend}（{_FRONTEND_VERSION_FILE}），'
            f'被测={dut}（GET /payload/device/version）。请先部署与仓库一致的正式包。'
        )
    return backend, frontend, dut
