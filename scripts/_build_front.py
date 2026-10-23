# -*- coding: utf-8 -*-
"""Frontend packaging: npm run build:prod, zip to dist/html_VERSION.zip.
Called by scripts/build_front.bat and scripts/build_front.sh.
Resolves repo root from this file location; no absolute machine paths.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
FE = REPO_ROOT / "ruoyi-fastapi-frontend"
OUT = REPO_ROOT / "dist"


def _read_version(version_js: Path) -> str:
    text = version_js.read_text(encoding="utf-8")
    m = re.search(r"appVersion\s*=\s*'([^']+)'", text)
    if not m:
        m = re.search(r'appVersion\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("ERROR: Failed to read appVersion from version.js")
    return m.group(1)


def _zip_dir(src_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(src_dir).as_posix())


def _run_npm_build() -> None:
    if sys.platform == "win32":
        npm = shutil.which("npm.cmd") or shutil.which("npm")
    else:
        npm = shutil.which("npm")
    if not npm:
        raise SystemExit("ERROR: npm not found on PATH")
    cmd = [npm, "run", "build:prod", "--", "--logLevel", "silent"]
    r = subprocess.run(cmd, cwd=str(FE))
    if r.returncode != 0:
        raise SystemExit("ERROR: Frontend build failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build frontend and package html zip")
    parser.add_argument(
        "--nested",
        action="store_true",
        help="Called from top-level build; shells skip pause",
    )
    parser.parse_args(argv)

    version_js = FE / "version.js"
    if not version_js.is_file():
        raise SystemExit("ERROR: Cannot find version.js")
    app_version = _read_version(version_js)
    print(f"[Frontend] Version {app_version}")
    print("[Frontend] npm run build:prod")
    _run_npm_build()

    index_html = FE / "dist" / "index.html"
    if not index_html.is_file():
        raise SystemExit("ERROR: dist/index.html not found after build")

    OUT.mkdir(parents=True, exist_ok=True)
    zip_name = f"html_{app_version}.zip"
    zip_path = OUT / zip_name
    print(f"[Frontend] Packaging {zip_name}")
    _zip_dir(FE / "dist", zip_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
