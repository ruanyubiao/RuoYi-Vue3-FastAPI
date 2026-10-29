# -*- coding: utf-8 -*-
"""Build history_file samples for every telemetry dropdown table.

Priority per table:
  1) logs_data/raw (source=raw)
  2) tm_golden_cases / tests/data simulate fixtures (source=sim)
  3) protocol-shaped synthetic frames (source=generated)
Skip only when fileplay unsupported or synthesis fails.

Sample basename matches UI dropdown prefix style:
  {FAMILY}-{localKey}-HIL.{bin|txt}
  e.g. XL-RKDJ-HIL.bin, BIU-FF-HIL.txt, YJ216-LCWP20-HIL.bin
FAMILY/localKey come from PayloadConfigLoader.merge_telemetry_pages
(same source as the frontend telemetry dropdown).
"""
from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

BACKEND = Path(r"E:\plat\PayloadGroundTest\ruoyi-fastapi-backend")
sys.path.insert(0, str(BACKEND))

from module_payload.cfg.payload_config_loader import PayloadConfigLoader  # noqa: E402
from module_payload.constants import checksum_u16  # noqa: E402
from module_payload.fileplay.detect import index_file  # noqa: E402
from module_payload.fileplay.registry import resolve_fileplay  # noqa: E402

RAW_ROOT = BACKEND / "logs_data" / "raw"
GOLDEN_PATH = BACKEND / "assets" / "data" / "tm_golden_cases.json"
TESTS_DATA = BACKEND / "tests" / "data"
OUT_ROOT = Path(r"E:\plat\PayloadGroundTest\ruoyi-fastapi-hil\hil\testdata\history_file")
DATA_DIR = OUT_ROOT / "data"
ZIP_PATH = OUT_ROOT / "history_file_raw.zip"
MANIFEST_PATH = OUT_ROOT / "manifest.json"

TARGET_BYTES = 100 * 1024
MID_LO, MID_HI = 50 * 1024, 100 * 1024
MIN_FRAMES = 1000
MAX_COPIES = 2000

# Optional raw globs (best-effort); tables without a glob still try sim/generated.
TABLE_GLOBS: dict[str, list[str]] = {
    "BIU:FF": ["biu_*recv.txt", "can_0_0_0_*recv.txt"],
    "XL:FF": ["xl_*recv.txt", "*xl_can*recv*"],
    "YJ216:FF": ["yj216_*recv.txt"],
    "D8": ["camera_ctrl_serial_*recv.bin"],
    "D8V17": ["camera_ctrl_v17_*recv.bin", "xl-camera-v17_*recv.bin"],
    "D9": ["camera_image_serial_*recv.bin"],
    "D9V17": ["camera_image_v17_*recv.bin"],
    "CPAZX": ["cpazx_*recv.bin", "xl-cpazx_*recv.bin"],
    "ZK": ["zk_*recv.bin"],
    "RKDJ": ["*rkdj*recv*"],
    "DJ": ["*udp*recv*", "*dj*recv*", "*xl_udp*recv*"],
    "LCWP20": ["*rs422*recv*", "*yj216*serial*recv*"],
}

# Extra sim fixtures under tests/data (filename -> table)
TESTS_DATA_MAP: dict[str, str] = {
    "biu_can_a_can_0_0_0_20260907_recv.txt": "BIU:FF",
    "camera_ctrl_serial_COM4_20260814_170250_078_recv.bin": "D8",
}


# Exact raw pins (preferred over TABLE_GLOBS). Survives full regenerate.
# target_bytes: keep first N bytes (frame index verified without force_estimate).
RAW_PINS: dict[str, dict] = {
    "D8V17": {
        "rel": "20260917/camera_ctrl_v17_serial_COM3_20260917_172122_191_recv.bin",
        "target_bytes": 3 * 1024 * 1024,  # 3 MiB as requested for curve deep
        "expand": False,  # 3MB already >> min_frames
        # Keep XL-D8V17-HIL prefix; append recv stamp so DUT parse_recv_file_start_ms yields X-axis.
        "file": "XL-D8V17-HIL_20260917_172122_191.bin",
    },
}


def try_raw_pin(table: str, family: str, local_key: str) -> dict | None:
    pin = RAW_PINS.get(table)
    if not pin:
        return None
    src = RAW_ROOT / str(pin["rel"])
    if not src.is_file():
        print(f"PIN MISS {table}: {src}")
        return None
    target = int(pin.get("target_bytes") or TARGET_BYTES)
    raw = src.read_bytes()
    cut = min(len(raw), target) if target > 0 else len(raw)
    ext = src.suffix.lower() or ".bin"
    name = str(pin.get("file") or "").strip() or hil_filename(family, local_key, ext)
    dest = DATA_DIR / name
    last_err = "pin truncate failed"
    for try_cut in (cut, int(cut * 0.98), int(cut * 0.95), int(cut * 0.9)):
        if try_cut <= 0:
            continue
        dest.write_bytes(raw[:try_cut])
        ok, n, err = has_frames(dest, table)
        if not ok:
            last_err = err or "no frames"
            continue
        copies = 1
        if pin.get("expand", True):
            ok3, n3, copies = expand_to_min_frames(dest, table)
            if not ok3 or n3 < MIN_FRAMES:
                last_err = f"expand short frames={n3} copies={copies}"
                dest.unlink(missing_ok=True)
                continue
            n = n3
        elif n < MIN_FRAMES:
            last_err = f"pin short frames={n} (<{MIN_FRAMES}) without expand"
            dest.unlink(missing_ok=True)
            continue
        return {
            "table": table,
            "file": name,
            "family": family,
            "localKey": local_key,
            "kind": "hex" if ext == ".txt" else "bin",
            "source": "raw",
            "source_prefix": source_prefix_from_name(src.name),
            "source_name": src.name,
            "source_rel": str(src.relative_to(RAW_ROOT)).replace("\\", "/"),
            "bytes": dest.stat().st_size,
            "source_bytes": src.stat().st_size,
            "frame_count_sample": n,
            "copies": copies,
            "base_bytes": try_cut,
            "truncated": try_cut < src.stat().st_size,
            "generated": False,
            "pinned": True,
            "pin_target_bytes": target,
        }
    print(f"PIN FAIL {table}: {last_err}")
    return None



def table_safe(table: str) -> str:
    """Filesystem-safe fragment for synthetic source_name only (not sample basename)."""
    return table.replace(":", "_").replace("/", "_")


def source_prefix_from_name(name: str) -> str:
    for token in ("_serial_", "_can_", "_udp_"):
        i = name.lower().find(token)
        if i > 0:
            return name[:i]
    stem = Path(name).stem
    return stem.split("_recv")[0] if "_recv" in stem else stem[:40]


def hil_filename(family: str, local_key: str, ext: str) -> str:
    """UI-aligned sample basename: {FAMILY}-{localKey}-HIL.{bin|txt}."""
    fam = (family or "").strip().upper()
    local = (local_key or "").strip().upper()
    if not fam or not local:
        raise ValueError(f"missing family/localKey for hil sample: family={family!r} localKey={local_key!r}")
    e = ext if ext.startswith(".") else f".{ext}"
    return f"{fam}-{local}-HIL{e}"


def has_frames(path: Path, table: str) -> tuple[bool, int, str]:
    force = path.stat().st_size > 5 * 1024 * 1024
    idx = index_file(path, table, force_estimate=force)
    ok = idx.frame_count > 0 and not idx.error
    return ok, int(idx.frame_count or 0), idx.error or ""


def expand_to_min_frames(
    dest: Path, table: str, *, min_frames: int = MIN_FRAMES, max_copies: int = MAX_COPIES
) -> tuple[bool, int, int]:
    """Whole-file concatenate copies until index_file reports >= min_frames (~10x when base~100)."""
    ok, n, _err = has_frames(dest, table)
    if not ok:
        return False, 0, 1
    if n >= min_frames:
        return True, n, 1
    base = dest.read_bytes()
    if not base:
        return False, 0, 1
    per = max(n, 1)
    need = (min_frames + per - 1) // per
    copies = min(max(need, 2), max_copies)
    dest.write_bytes(base * copies)
    ok, n, _err = has_frames(dest, table)
    if not ok:
        return False, 0, copies
    # If still short (non-linear index), grow up to max_copies
    while n < min_frames and copies < max_copies:
        copies = min(copies + max(1, (min_frames - n + per - 1) // per), max_copies)
        dest.write_bytes(base * copies)
        ok, n, _err = has_frames(dest, table)
        if not ok:
            return False, 0, copies
    return (n >= min_frames), n, copies


def collect_candidates(globs: list[str]) -> list[Path]:
    files: list[Path] = []
    for g in globs:
        files.extend(RAW_ROOT.rglob(g))
    out = []
    for p in files:
        if not p.is_file() or p.stat().st_size <= 0:
            continue
        if "_send" in p.name.lower():
            continue
        out.append(p)
    return sorted(set(out), key=lambda p: p.stat().st_size)


def ordered_try(files: list[Path]) -> list[Path]:
    mid = [p for p in files if MID_LO <= p.stat().st_size <= MID_HI]
    big = sorted([p for p in files if p.stat().st_size > MID_HI], key=lambda p: p.stat().st_size)
    small = sorted(
        [p for p in files if p.stat().st_size < MID_LO],
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    return mid + big[:20] + small[:10]


def truncate_base(src: Path, dest: Path, table: str) -> tuple[bool, int, int]:
    raw = src.read_bytes()
    size = len(raw)
    if size <= TARGET_BYTES:
        dest.write_bytes(raw)
        ok, n, _ = has_frames(dest, table)
        return ok, n, size
    for cut in (TARGET_BYTES, int(TARGET_BYTES * 1.5), int(TARGET_BYTES * 2), min(size, 256 * 1024)):
        dest.write_bytes(raw[:cut])
        ok, n, _ = has_frames(dest, table)
        if ok:
            return ok, n, cut
    return False, 0, TARGET_BYTES


def load_golden_by_table() -> dict[str, list[tuple[str, bytes]]]:
    """table_key -> [(golden_id, raw_bytes), ...] preferring larger multi-frame samples first."""
    if not GOLDEN_PATH.is_file():
        return {}
    raw = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    out: dict[str, list[tuple[str, bytes]]] = {}
    for gid, obj in raw.items():
        if not isinstance(obj, dict):
            continue
        result = obj.get("result") if isinstance(obj.get("result"), dict) else {}
        table = str(result.get("table_key") or "").strip()
        hx = str(obj.get("hex") or "").replace(" ", "").replace("\n", "")
        if not table or not hx:
            continue
        try:
            blob = bytes.fromhex(hx)
        except ValueError:
            continue
        out.setdefault(table, []).append((gid, blob))
    # prefer multi-frame (larger) first
    for table, items in out.items():
        items.sort(key=lambda it: len(it[1]), reverse=True)
    return out


def preferred_ext(table: str) -> str:
    """CAN bus tables: .txt hex; others: .bin."""
    spec = resolve_fileplay(table)
    if spec and getattr(spec, "kind", None) == "can":
        return ".txt"
    return ".bin"


def write_bytes_sample(dest: Path, blob: bytes, *, as_txt: bool) -> None:
    if as_txt:
        # one hex line per physical frame blob (assembled TM frame)
        line = " ".join(f"{b:02X}" for b in blob)
        dest.write_text(line + "\n", encoding="utf-8")
    else:
        dest.write_bytes(blob)


def try_raw(table: str, family: str, local_key: str) -> dict | None:
    globs = TABLE_GLOBS.get(table) or []
    if not globs:
        return None
    last_err = "no raw candidates"
    for src in ordered_try(collect_candidates(globs)):
        ok, n, err = has_frames(src, table)
        last_err = err or last_err
        if not ok:
            continue
        ext = src.suffix.lower() or ".bin"
        name = hil_filename(family, local_key, ext)
        dest = DATA_DIR / name
        ok2, _n2, used = truncate_base(src, dest, table)
        if not ok2:
            dest.unlink(missing_ok=True)
            last_err = f"truncate lost frames (src_frames={n})"
            continue
        ok3, n3, copies = expand_to_min_frames(dest, table)
        if not ok3 or n3 < MIN_FRAMES:
            dest.unlink(missing_ok=True)
            last_err = f"expand short frames={n3} copies={copies}"
            continue
        return {
            "table": table,
            "file": name,
            "family": family,
            "localKey": local_key,
            "kind": "hex" if ext == ".txt" else "bin",
            "source": "raw",
            "source_prefix": source_prefix_from_name(src.name),
            "source_name": src.name,
            "source_rel": str(src.relative_to(RAW_ROOT)).replace("\\", "/"),
            "bytes": dest.stat().st_size,
            "source_bytes": src.stat().st_size,
            "frame_count_sample": n3,
            "copies": copies,
            "base_bytes": used,
            "truncated": used < src.stat().st_size,
            "generated": False,
        }
    return None


def try_sim(table: str, family: str, local_key: str, golden_map: dict[str, list[tuple[str, bytes]]]) -> dict | None:
    # 1) golden cases
    for gid, blob in golden_map.get(table) or []:
        ext = preferred_ext(table)
        name = hil_filename(family, local_key, ext)
        dest = DATA_DIR / name
        write_bytes_sample(dest, blob, as_txt=(ext == ".txt"))
        ok, n, err = has_frames(dest, table)
        if not ok:
            dest.unlink(missing_ok=True)
            continue
        ok3, n3, copies = expand_to_min_frames(dest, table)
        if not ok3 or n3 < MIN_FRAMES:
            dest.unlink(missing_ok=True)
            continue
        return {
            "table": table,
            "file": name,
            "family": family,
            "localKey": local_key,
            "kind": "hex" if ext == ".txt" else "bin",
            "source": "sim",
            "source_prefix": f"sim_{gid}",
            "source_name": gid,
            "source_rel": f"assets/data/tm_golden_cases.json#{gid}",
            "bytes": dest.stat().st_size,
            "source_bytes": len(blob),
            "frame_count_sample": n3,
            "copies": copies,
            "base_bytes": dest.stat().st_size // max(copies, 1),
            "truncated": False,
            "generated": False,
        }
    # 2) tests/data fixtures
    for fname, mapped in TESTS_DATA_MAP.items():
        if mapped != table:
            continue
        src = TESTS_DATA / fname
        if not src.is_file():
            continue
        ext = src.suffix.lower() or ".bin"
        name = hil_filename(family, local_key, ext)
        dest = DATA_DIR / name
        ok2, _n2, used = truncate_base(src, dest, table)
        if not ok2:
            dest.unlink(missing_ok=True)
            continue
        ok3, n3, copies = expand_to_min_frames(dest, table)
        if not ok3 or n3 < MIN_FRAMES:
            dest.unlink(missing_ok=True)
            continue
        return {
            "table": table,
            "file": name,
            "family": family,
            "localKey": local_key,
            "kind": "hex" if ext == ".txt" else "bin",
            "source": "sim",
            "source_prefix": f"testdata_{source_prefix_from_name(fname)}",
            "source_name": fname,
            "source_rel": f"tests/data/{fname}",
            "bytes": dest.stat().st_size,
            "source_bytes": src.stat().st_size,
            "frame_count_sample": n3,
            "copies": copies,
            "base_bytes": used,
            "truncated": used < src.stat().st_size,
            "generated": False,
        }
    return None


def _rs422_span(table: str) -> int | None:
    from module_payload.protocol.yj216.rs422.tm import _table_spans

    return _table_spans().get(table)


def make_rs422_blob(table: str, n_frames: int = MIN_FRAMES) -> bytes | None:
    from module_payload.protocol.yj216.rs422.tm import DATA_TYPE, FRAME_HEADER

    span = _rs422_span(table)
    if span is None:
        return None
    chunks: list[bytes] = []
    for seq in range(n_frames):
        field = bytes([(seq + i) % 256 for i in range(span)])
        data = bytes([seq & 0xFF]) + field
        frame = (
            FRAME_HEADER
            + bytes([DATA_TYPE])
            + len(data).to_bytes(2, "big")
            + data
            + checksum_u16(data).to_bytes(2, "big")
        )
        chunks.append(frame)
    return b"".join(chunks)


def try_generated(table: str, family: str, local_key: str) -> dict | None:
    spec = resolve_fileplay(table)
    if spec is None:
        return None
    kind = getattr(spec, "kind", "") or ""
    blob: bytes | None = None
    if kind == "rs422":
        blob = make_rs422_blob(table, MIN_FRAMES)
    else:
        # No generic synthesizer for can/board/camera yet — those should come from sim/raw.
        return None
    if not blob:
        return None
    ext = ".bin"
    name = hil_filename(family, local_key, ext)
    dest = DATA_DIR / name
    dest.write_bytes(blob)
    ok, n, err = has_frames(dest, table)
    if not ok or n < MIN_FRAMES:
        # try expand if somehow short
        ok3, n3, copies = expand_to_min_frames(dest, table)
        if not ok3 or n3 < MIN_FRAMES:
            dest.unlink(missing_ok=True)
            return None
        n = n3
        copies_used = copies
    else:
        copies_used = 1
    return {
        "table": table,
        "file": name,
        "family": family,
        "localKey": local_key,
        "kind": "bin",
        "source": "generated",
        "source_prefix": "generated",
        "source_name": f"synth_{table_safe(table)}",
        "source_rel": f"generated/{kind}/{table}",
        "bytes": dest.stat().st_size,
        "source_bytes": len(blob),
        "frame_count_sample": n,
        "copies": copies_used,
        "base_bytes": dest.stat().st_size // max(copies_used, 1),
        "truncated": False,
        "generated": True,
    }


def all_dropdown_pages() -> list[dict]:
    """Pages from merge_telemetry_pages: key / family / localKey (UI dropdown source)."""
    pages = PayloadConfigLoader.merge_telemetry_pages(reload=True)
    out: list[dict] = []
    seen: set[str] = set()
    for p in pages:
        k = (p.get("key") or "").strip()
        if not k or k in seen:
            continue
        fam = (p.get("family") or "").strip()
        local = (p.get("localKey") or "").strip()
        if not fam or not local:
            continue
        seen.add(k)
        out.append({"key": k, "family": fam, "localKey": local})
    return out


def main() -> None:
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    DATA_DIR.mkdir(parents=True)

    tables_out: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    golden_map = load_golden_by_table()
    pages = all_dropdown_pages()
    dropdown = [p["key"] for p in pages]
    print(f"dropdown tables: {len(dropdown)}")

    for page in pages:
        table = page["key"]
        family = page["family"]
        local_key = page["localKey"]
        info = try_raw_pin(table, family, local_key)
        if info is None:
            info = try_raw(table, family, local_key)
        if info is None:
            info = try_sim(table, family, local_key, golden_map)
        if info is None:
            info = try_generated(table, family, local_key)
        if info is None:
            spec = resolve_fileplay(table)
            if spec is None:
                skipped[table] = "fileplay unsupported (no FilePlaySpec)"
            else:
                skipped[table] = "no raw/sim/generated sample with >=100 frames"
            print(f"SKIP {table}: {skipped[table]}")
            continue
        tables_out[table] = info
        print(
            f"OK {table} source={info['source']} file={info['file']} "
            f"frames={info['frame_count_sample']} copies={info['copies']}"
        )

    manifest = {
        "version": 4,
        "zip": ZIP_PATH.name,
        "data_dir": "data",
        "min_frames": MIN_FRAMES,
        "dropdown_tables": dropdown,
        "naming": "{FAMILY}-{localKey}-HIL.{bin|txt}",
        "naming_note": "FAMILY=uppercase page.family (xl->XL); localKey from merge_telemetry_pages; matches UI telemetryOptionLabel prefix",
        "source_priority": ["raw", "sim", "generated"],
        "raw_root_hint": "ruoyi-fastapi-backend/logs_data/raw/...",
        "sim_hint": "assets/data/tm_golden_cases.json + tests/data",
        "tables": tables_out,
        "skipped": skipped,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA_DIR / "manifest.json").write_text(MANIFEST_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(DATA_DIR.iterdir()):
            if p.is_file():
                zf.write(p, arcname=p.name)
    print("ZIP", ZIP_PATH, "files", sum(1 for p in DATA_DIR.iterdir() if p.is_file()))
    shutil.rmtree(DATA_DIR)
    print("done tables", list(tables_out), "skipped", list(skipped))


if __name__ == "__main__":
    main()
