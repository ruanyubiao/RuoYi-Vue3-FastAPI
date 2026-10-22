# -*- coding: utf-8 -*-
"""本地 SQL ↔ DUT information_schema 对照工具。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
SQL_MY = REPO / "ruoyi-fastapi-backend" / "sql" / "ruoyi-fastapi-my.sql"
SQL_PATCHES = REPO / "ruoyi-fastapi-backend" / "sql" / "patches"


def parse_sql_tables(sql_text: str) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for m in re.finditer(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)[`\"]?\s*\((.*?)\)\s*ENGINE",
        sql_text,
        re.I | re.S,
    ):
        name, body = m.group(1), m.group(2)
        cols: list[str] = []
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line:
                continue
            up = line.upper()
            if up.startswith(("PRIMARY", "KEY", "UNIQUE", "CONSTRAINT", "INDEX", "FOREIGN", "FULLTEXT", "SPATIAL")):
                continue
            cm = re.match(r"[`\"]?(\w+)[`\"]?\s+", line)
            if cm:
                cols.append(cm.group(1))
        tables[name] = cols
    return tables


def load_local_schema() -> dict[str, list[str]]:
    text = SQL_MY.read_text(encoding="utf-8", errors="replace")
    tables = parse_sql_tables(text)
    if SQL_PATCHES.exists():
        for p in sorted(SQL_PATCHES.glob("*.sql")):
            t = p.read_text(encoding="utf-8", errors="replace")
            if re.search(r"CREATE\s+TABLE", t, re.I):
                tables.update(parse_sql_tables(t))
            for am in re.finditer(
                r"ALTER\s+TABLE\s+[`\"]?(\w+)[`\"]?\s+ADD\s+(?:COLUMN\s+)?[`\"]?(\w+)[`\"]?",
                t,
                re.I,
            ):
                tables.setdefault(am.group(1), [])
                if am.group(2) not in tables[am.group(1)]:
                    tables[am.group(1)].append(am.group(2))
    return tables


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip()
        if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
            v = v[1:-1]
        else:
            v = v.split("#", 1)[0].strip()
        out[k] = v
    return out


def db_connect_kwargs() -> dict[str, Any] | None:
    """从环境变量或 backend .env.prod 读连接；失败返回 None。"""
    file_env = _parse_env_file(REPO / "ruoyi-fastapi-backend" / ".env.prod")
    host = os.getenv("HIL_DB_HOST") or os.getenv("DB_HOST") or file_env.get("DB_HOST") or "192.168.100.52"
    port_s = os.getenv("HIL_DB_PORT") or os.getenv("DB_PORT") or file_env.get("DB_PORT") or "3306"
    user = os.getenv("HIL_DB_USER") or os.getenv("DB_USERNAME") or file_env.get("DB_USERNAME") or "root"
    password = os.getenv("HIL_DB_PASSWORD") or os.getenv("DB_PASSWORD")
    if password is None:
        password = file_env.get("DB_PASSWORD")
    database = (
        os.getenv("HIL_DB_DATABASE")
        or os.getenv("DB_DATABASE")
        or file_env.get("DB_DATABASE")
        or "ruoyi-fastapi"
    )
    try:
        port = int(str(port_s).strip().split()[0])
    except (TypeError, ValueError):
        port = 3306
    if not host or password is None:
        return None
    if host in ("ruoyi-mysql", "mysql8", "mysql"):
        host = os.getenv("HIL_IPC_IP") or os.getenv("HIL_DB_HOST") or "192.168.100.52"
    if host in ("127.0.0.1", "localhost") and not os.getenv("HIL_DB_HOST"):
        host = os.getenv("HIL_IPC_IP") or "192.168.100.52"
    return {"host": host, "port": port, "user": user, "password": password, "database": database}


def fetch_remote_schema(conn_kw: dict[str, Any]) -> dict[str, list[str]]:
    import pymysql

    conn = pymysql.connect(connect_timeout=5, **conn_kw)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME, ORDINAL_POSITION",
            (conn_kw["database"],),
        )
        tables: dict[str, list[str]] = {}
        for tname, cname in cur.fetchall():
            tables.setdefault(tname, []).append(cname)
        return tables
    finally:
        conn.close()


def diff_schema(local: dict[str, list[str]], remote: dict[str, list[str]]) -> dict[str, Any]:
    local_tables = set(local)
    remote_tables = set(remote)
    ignore = {"apscheduler_jobs", "schema_version"}
    missing_tables = sorted((local_tables - remote_tables) - ignore)
    extra_tables = sorted((remote_tables - local_tables) - ignore)
    missing_columns: dict[str, list[str]] = {}
    for t in sorted(local_tables & remote_tables):
        miss = [c for c in local[t] if c not in set(remote[t])]
        if miss:
            missing_columns[t] = miss
    return {
        "missing_tables": missing_tables,
        "extra_tables": extra_tables,
        "missing_columns": missing_columns,
        "local_table_count": len(local_tables),
        "remote_table_count": len(remote_tables),
    }
