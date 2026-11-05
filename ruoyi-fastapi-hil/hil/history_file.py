# -*- coding: utf-8 -*-
"""历史文件数据/曲线 HIL：样本 zip 解压、表↔文件映射、样本契约。"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

from hil.config import HIL_ROOT

# 与前端 fileCurve/index.vue 的 CURVE_CHUNK 一致：滑块单位是块序号，不是帧号。
CURVE_CHUNK_FRAMES = 10000
# 曲线深测只跑这些表：文件名须带 YYYYMMDD_HHMMSS_mmm，帧数须跨过至少两块。
CURVE_SAMPLE_TABLES: tuple[str, ...] = ("D8V17",)
_RECV_STAMP_RE = re.compile(r"(\d{8})_(\d{6})_(\d{1,3})")
_OBSOLETE_SAMPLE_MARK = "__hil_sample"

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


def sample_name_prefix(family: str, local_key: str) -> str:
    """UI 下拉前缀：{FAMILY}-{localKey}-HIL。"""
    fam = (family or "").strip().upper()
    local = (local_key or "").strip().upper()
    return f"{fam}-{local}-HIL"


def recv_stamp_ok(filename: str) -> bool:
    """文件名含 YYYYMMDD_HHMMSS_mmm，供 fileplay 解析曲线 X 轴起点。"""
    return _RECV_STAMP_RE.search(Path(str(filename or "")).name) is not None


def sample_contract_issues(manifest: dict | None = None, *, zip_path: Path | None = None) -> list[str]:
    """样本契约：命名、≥min_frames、曲线时间戳与块序号、zip 成员。空列表表示通过。"""
    man = manifest if manifest is not None else load_manifest()
    issues: list[str] = []
    min_frames = int(man.get("min_frames") or 0)
    if min_frames < 1000:
        issues.append(f"manifest.min_frames={min_frames}，要求 >= 1000")
    tables = man.get("tables") or {}
    if not tables:
        issues.append("manifest.tables 为空")
    skipped = man.get("skipped") or {}
    dropdown = [str(k) for k in (man.get("dropdown_tables") or [])]
    if dropdown:
        missing = [k for k in dropdown if k not in tables and k not in skipped]
        if missing:
            issues.append(f"dropdown 既无样本也无 skip 原因: {missing}")
        for key, reason in skipped.items():
            if not str(reason or "").strip():
                issues.append(f"skipped[{key}] 原因为空")
    zf = None
    names: set[str] = set()
    zpath = zip_path if zip_path is not None else HISTORY_FILE_ZIP
    if zpath.is_file():
        zf = zipfile.ZipFile(zpath)
        names = {Path(n).name for n in zf.namelist()}
    else:
        issues.append(f"缺少样本包: {zpath}")
    try:
        for table, info in tables.items():
            if not isinstance(info, dict):
                issues.append(f"{table}: 条目不是对象")
                continue
            family = str(info.get("family") or "")
            local = str(info.get("localKey") or "")
            filename = str(info.get("file") or "")
            prefix = sample_name_prefix(family, local)
            if not filename.startswith(prefix):
                issues.append(f"{table}: 文件名 {filename!r} 不以 {prefix} 开头")
            if _OBSOLETE_SAMPLE_MARK in filename:
                issues.append(f"{table}: 仍使用旧命名 {filename}")
            frames = int(info.get("frame_count_sample") or 0)
            if frames < min_frames:
                issues.append(f"{table}: frame_count_sample={frames} < min_frames={min_frames}")
            if names and filename not in names:
                issues.append(f"{table}: zip 缺少 {filename}")
            if table in CURVE_SAMPLE_TABLES:
                if not recv_stamp_ok(filename):
                    issues.append(
                        f"{table}: 曲线样本文件名须含 YYYYMMDD_HHMMSS_mmm，当前 {filename}"
                    )
                if frames <= CURVE_CHUNK_FRAMES:
                    issues.append(
                        f"{table}: 曲线帧数 {frames} 未超过一块 "
                        f"({CURVE_CHUNK_FRAMES})，区间滑块没有后续 chunk"
                    )
    finally:
        if zf is not None:
            zf.close()
    return issues
