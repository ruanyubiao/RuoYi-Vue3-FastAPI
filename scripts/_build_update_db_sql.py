# -*- coding: utf-8 -*-
"""Used by scripts/_build_backend.py for :update_db_sql.
Reads env DB_OUT, SV_DDL, PGT_ZIP, SQL_SRC when run standalone.
1) Writes DB_OUT/zz_schema_version.sql BASELINE rows, SHA-256 hex lower.
2) Syncs PGT/mysql/sql/*.sql inside PGT_ZIP when content changed.
Also importable: generate_zz_schema_version, update_pgt_zip.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

PATCH_NAME_RE = re.compile(r"^V(\d{4})__\w+\.sql$", re.ASCII)
SQL_NAMES = ("ruoyi-fastapi-my.sql", "zz_schema_version.sql")
ZIP_SQL_PREFIX = "PGT/mysql/sql/"


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"ERROR: env {name} is not set")
    return v


def _sha256_hex_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def _sha256_b64_stream(stream) -> str:
    h = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        h.update(chunk)
    return base64.b64encode(h.digest()).decode("ascii")


def _sha256_b64_file(path: Path) -> str:
    with path.open("rb") as f:
        return _sha256_b64_stream(f)


def generate_zz_schema_version(db_out: Path, sv_ddl: str) -> None:
    patches_dir = db_out / "patches"
    lines: list[str] = [
        r"-- auto-generated, do not edit by hand",
        "-- new database only: patches already merged into ruoyi-fastapi-my.sql are recorded as BASELINE",
        "set names utf8mb4;",
        sv_ddl + ";",
    ]
    seen: dict[str, str] = {}
    files = sorted(patches_dir.glob("*.sql"), key=lambda p: p.name)
    for f in files:
        m = PATCH_NAME_RE.match(f.name)
        if not m:
            raise SystemExit(
                f"bad patch file name {f.name} (must be V<4 digits>__<desc>.sql)"
            )
        ver = m.group(1)
        if ver in seen:
            raise SystemExit(
                f"duplicate patch version {ver}: {seen[ver]}, {f.name}"
            )
        seen[ver] = f.name
        digest = _sha256_hex_file(f)
        lines.append(
            "insert into schema_version(version, script, checksum, type, success) "
            f"values ('{ver}', '{f.name}', '{digest}', 'BASELINE', 1);"
        )
    out = db_out / "zz_schema_version.sql"
    out.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    print(f"[Backend] zz_schema_version.sql: {len(seen)} patch(es) recorded as BASELINE")


def _is_direct_sql_entry(name: str) -> bool:
    if not name.startswith(ZIP_SQL_PREFIX) or not name.endswith(".sql"):
        return False
    rest = name[len(ZIP_SQL_PREFIX) :]
    return bool(rest) and "/" not in rest


def update_pgt_zip(pgt_zip: Path, db_out: Path, sql_src: Path) -> None:
    with zipfile.ZipFile(pgt_zip, "r") as z:
        old = [n for n in z.namelist() if _is_direct_sql_entry(n)]
        same = len(old) == len(SQL_NAMES)
        if same:
            for name in SQL_NAMES:
                entry = ZIP_SQL_PREFIX + name
                try:
                    with z.open(entry) as ef:
                        zip_hash = _sha256_b64_stream(ef)
                except KeyError:
                    same = False
                    break
                file_hash = _sha256_b64_file(db_out / name)
                if zip_hash != file_hash:
                    same = False
                    break
    if same:
        print("[Backend] PGT/mysql/sql unchanged, PGT.zip left as is")
        return

    mtime = sql_src.stat().st_mtime
    dt = datetime.fromtimestamp(mtime)
    date_time = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)

    tmp = Path(str(pgt_zip) + ".tmp")
    if tmp.exists():
        tmp.unlink()
    try:
        with zipfile.ZipFile(pgt_zip, "r") as zin, zipfile.ZipFile(tmp, "w") as zout:
            for info in zin.infolist():
                if _is_direct_sql_entry(info.filename):
                    continue
                zout.writestr(info, zin.read(info.filename))
            for name in SQL_NAMES:
                zi = zipfile.ZipInfo(ZIP_SQL_PREFIX + name)
                zi.date_time = date_time
                zi.compress_type = zipfile.ZIP_DEFLATED
                zout.writestr(zi, (db_out / name).read_bytes())
        os.replace(tmp, pgt_zip)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
    print("[Backend] PGT/mysql/sql updated in PGT.zip")


def main() -> int:
    db_out = Path(_env("DB_OUT"))
    sv_ddl = _env("SV_DDL")
    pgt_zip = Path(_env("PGT_ZIP"))
    sql_src = Path(_env("SQL_SRC"))
    generate_zz_schema_version(db_out, sv_ddl)
    if not pgt_zip.is_file():
        raise SystemExit(f"ERROR: {pgt_zip} not found")
    print(f"[Backend] Checking PGT/mysql/sql in {pgt_zip}")
    update_pgt_zip(pgt_zip, db_out, sql_src)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
