# -*- coding: utf-8 -*-
"""Backend packaging: wheel, dist/db SQL, PGT.zip mysql/sql sync.
Called by scripts/build_backend.bat and scripts/build_backend.sh.
Resolves repo root from this file location; no absolute machine paths.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Same DDL as service/update/db_patches_apply.bat
SV_DDL = (
    "create table if not exists schema_version ("
    "version varchar(32) not null primary key comment 'patch version from the file name, e.g. 0001', "
    "script varchar(255) not null comment 'patch file name', "
    "checksum char(64) not null comment 'SHA-256 of the patch file', "
    "type varchar(16) not null comment 'BASELINE: merged into the init SQL; SQL: applied by db_patches_apply', "
    "success tinyint not null comment '1 applied, 0 failed', "
    "installed_on datetime not null default current_timestamp comment 'when recorded'"
    ") engine=innodb default charset=utf8mb4 comment='applied db patches'"
)

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
BE = REPO_ROOT / "ruoyi-fastapi-backend"
OUT = REPO_ROOT / "dist"


def _venv_python() -> Path:
    if sys.platform == "win32":
        py = BE / "venv" / "Scripts" / "python.exe"
    else:
        py = BE / "venv" / "bin" / "python"
    if not py.is_file():
        raise SystemExit(
            f"ERROR: Cannot find {py}, please create venv in ruoyi-fastapi-backend first"
        )
    return py


def _read_version(version_py: Path) -> str:
    text = version_py.read_text(encoding="utf-8")
    m = re.search(r"appVersion\s*=\s*'([^']+)'", text)
    if not m:
        m = re.search(r'appVersion\s*=\s*"([^"]+)"', text)
    if not m:
        raise SystemExit("ERROR: Failed to read appVersion from version.py")
    return m.group(1)


def _ensure_build_module(py: Path) -> None:
    r = subprocess.run(
        [str(py), "-c", "import build"],
        cwd=str(BE),
        capture_output=True,
    )
    if r.returncode == 0:
        return
    print("build module not installed, installing to venv...")
    r2 = subprocess.run([str(py), "-m", "pip", "install", "build"], cwd=str(BE))
    if r2.returncode != 0:
        raise SystemExit("ERROR: pip install build failed")


def clean_backend_build() -> None:
    for name in ("build", ".eggs", "__pycache__"):
        p = BE / name
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    for egg in BE.glob("*.egg-info"):
        shutil.rmtree(egg, ignore_errors=True)
    cfg = BE / "config"
    for envf in cfg.glob(".env.*"):
        try:
            envf.unlink()
        except OSError:
            pass
    alembic_cfg = cfg / "alembic.ini"
    if alembic_cfg.exists():
        try:
            alembic_cfg.unlink()
        except OSError:
            pass


def _copy_config_into_package(py: Path) -> None:
    print("[Backend] Copying config to config package for wheel")
    cfg = BE / "config"
    cfg.mkdir(exist_ok=True)
    for envf in BE.glob(".env.*"):
        shutil.copy2(envf, cfg / envf.name)
    alembic_src = BE / "alembic.ini"
    if alembic_src.is_file():
        dest = cfg / "alembic.ini"
        shutil.copy2(alembic_src, dest)
        text = dest.read_text(encoding="utf-8")
        dest.write_text(
            text.replace("%(here)s/alembic", "%(here)s/../alembic"),
            encoding="utf-8",
        )


def _update_db_sql() -> None:
    # Import sibling helper; sys.path[0] is scripts/ when this file is executed
    import _build_update_db_sql as upd

    sql_src = BE / "sql" / "ruoyi-fastapi-my.sql"
    patch_src = BE / "sql" / "patches"
    db_out = OUT / "db"
    pgt_zip = OUT / "deploy" / "PGT.zip"

    if not sql_src.is_file():
        raise SystemExit(f"ERROR: {sql_src} not found")
    if not patch_src.is_dir():
        raise SystemExit(f"ERROR: {patch_src} not found")

    db_out.mkdir(parents=True, exist_ok=True)
    print(f"[Backend] Copying ruoyi-fastapi-my.sql and patches to {db_out}")
    shutil.copy2(sql_src, db_out / "ruoyi-fastapi-my.sql")

    patches_out = db_out / "patches"
    patches_out.mkdir(parents=True, exist_ok=True)
    for old in patches_out.glob("*.sql"):
        old.unlink()
    for src in patch_src.glob("*.sql"):
        shutil.copy2(src, patches_out / src.name)

    upd.generate_zz_schema_version(db_out, SV_DDL)
    if not pgt_zip.is_file():
        raise SystemExit(f"ERROR: {pgt_zip} not found")
    print(f"[Backend] Checking PGT/mysql/sql in {pgt_zip}")
    upd.update_pgt_zip(pgt_zip, db_out, sql_src)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build backend wheel and dist/db")
    parser.add_argument(
        "--nested",
        action="store_true",
        help="Called from top-level build; shells skip pause",
    )
    parser.parse_args(argv)  # accept --nested; pause is shell-side

    py = _venv_python()
    # Prefer running build steps with the same interpreter that owns the venv
    if Path(sys.executable).resolve() != py.resolve():
        # Re-exec under venv python so imports/build use venv
        cmd = [str(py), str(Path(__file__).resolve()), *sys.argv[1:]]
        return subprocess.call(cmd, cwd=str(BE))

    version_py = BE / "version.py"
    if not version_py.is_file():
        raise SystemExit("ERROR: Cannot find version.py")
    be_version = _read_version(version_py)
    print(f"[Backend] Version {be_version}")

    _ensure_build_module(py)
    OUT.mkdir(parents=True, exist_ok=True)
    clean_backend_build()
    _copy_config_into_package(py)

    print("[Backend] python -m build --wheel")
    r = subprocess.run(
        [str(py), "-m", "build", "--wheel", "--outdir", str(OUT)],
        cwd=str(BE),
    )
    if r.returncode != 0:
        clean_backend_build()
        raise SystemExit("ERROR: Backend wheel build failed")

    whl_dir = BE / "whl"
    if whl_dir.is_dir():
        for whl in whl_dir.glob("*.whl"):
            shutil.copy2(whl, OUT / whl.name)

    try:
        _update_db_sql()
    except SystemExit:
        clean_backend_build()
        raise
    except Exception as exc:
        clean_backend_build()
        print(f"ERROR: update_db_sql failed: {exc}", file=sys.stderr)
        return 1

    clean_backend_build()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
