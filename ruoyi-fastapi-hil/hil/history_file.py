# -*- coding: utf-8 -*-
"""历史文件数据/曲线 HIL：样本 zip 解压、表↔文件映射。"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from hil.config import HIL_ROOT

HISTORY_FILE_ROOT = HIL_ROOT / "hil" / "testdata" / "history_file"
HISTORY_FILE_ZIP = HISTORY_FILE_ROOT / "history_file_raw.zip"
HISTORY_FILE_DATA = HISTORY_FILE_ROOT / "data"
HISTORY_FILE_MANIFEST = HISTORY_FILE_ROOT / "manifest.json"

# Fallback if manifest missing dropdown_tables (pre-v3). Prefer load_history_file_tables().
_HISTORY_FILE_TABLES_FALLBACK: tuple[str, ...] = (
    "BIU:FF",
    "BIU:FD",
    "BIU:FB",
    "BIU:F9",
    "BIU:F7",
    "BIU:FE",
    "BIU:FC",
    "BIU:7E9B",
    "BIU:7E9D",
    "BIU:7E9F",
    "XL:FF",
    "XL:7E9B",
    "RKDJ",
    "ZK",
    "DJ",
    "CPAZX",
    "D8",
    "D9",
    "D8V17",
    "D9V17",
    "YJ216:FF",
    "LCWP20",
    "LCWP30",
    "LCWP40",
    "LCWP50",
    "LCWP60",
    "LCOS",
    "UPHI",
)


def load_manifest() -> dict:
    return json.loads(HISTORY_FILE_MANIFEST.read_text(encoding="utf-8"))


def load_history_file_tables() -> tuple[str, ...]:
    """All telemetry dropdown keys (manifest.dropdown_tables or fallback)."""
    try:
        man = load_manifest()
    except Exception:  # noqa: BLE001
        return _HISTORY_FILE_TABLES_FALLBACK
    keys = man.get("dropdown_tables") or list((man.get("tables") or {}).keys()) or []
    out = tuple(str(k) for k in keys if str(k).strip())
    return out or _HISTORY_FILE_TABLES_FALLBACK


# Parametrize target: full dropdown list from last prepare run.
HISTORY_FILE_TABLES: tuple[str, ...] = load_history_file_tables()


def ensure_history_file_data(*, force: bool = False) -> tuple[Path, dict]:
    """删旧解压目录 → 解压 zip → 返回 (data_dir, manifest)。"""
    if force and HISTORY_FILE_DATA.exists():
        shutil.rmtree(HISTORY_FILE_DATA, ignore_errors=True)
    if HISTORY_FILE_DATA.exists() and any(HISTORY_FILE_DATA.iterdir()):
        return HISTORY_FILE_DATA, load_manifest()
    if HISTORY_FILE_DATA.exists():
        shutil.rmtree(HISTORY_FILE_DATA, ignore_errors=True)
    HISTORY_FILE_DATA.mkdir(parents=True, exist_ok=True)
    if not HISTORY_FILE_ZIP.is_file():
        raise FileNotFoundError(f"缺少样本包: {HISTORY_FILE_ZIP}")
    with zipfile.ZipFile(HISTORY_FILE_ZIP) as zf:
        zf.extractall(HISTORY_FILE_DATA)
    return HISTORY_FILE_DATA, load_manifest()


def cleanup_history_file_data() -> None:
    if HISTORY_FILE_DATA.exists():
        shutil.rmtree(HISTORY_FILE_DATA, ignore_errors=True)


def sample_path_for(table: str, data_dir: Path | None = None, manifest: dict | None = None) -> Path | None:
    """表键 → 解压后的样本绝对路径；无样本返回 None。"""
    man = manifest or load_manifest()
    info = (man.get("tables") or {}).get(table)
    if not info:
        return None
    base = data_dir or HISTORY_FILE_DATA
    p = base / info["file"]
    return p if p.is_file() else None


def skip_reason(table: str, manifest: dict | None = None) -> str | None:
    man = manifest or load_manifest()
    if table in (man.get("tables") or {}):
        return None
    return (man.get("skipped") or {}).get(table) or f"manifest 无该表样本: {table}"


def overwrite_probe_table(manifest: dict | None = None) -> str | None:
    """Pick one table that has a sample, for the single re-upload/overwrite case."""
    man = manifest or load_manifest()
    tables = man.get("tables") or {}
    for preferred in ("BIU:FF", "YJ216:FF", "D8", "D8V17", "CPAZX", "RKDJ"):
        if preferred in tables:
            return preferred
    return next(iter(tables), None)
