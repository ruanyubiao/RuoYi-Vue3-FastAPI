# -*- coding: utf-8 -*-
"""解析 ``tests/data/payload_tm_frame.sql``（Navicat INSERT）为内存归档行。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

_DATA = Path(__file__).resolve().parent / 'data'
DEFAULT_SQL = _DATA / 'payload_tm_frame.sql'

_INSERT_RE = re.compile(
    r"^INSERT INTO `payload_tm_frame` VALUES \((.*)\);\s*$",
    re.M,
)


def _split_sql_values(body: str) -> list[str]:
    """按逗号拆 SQL VALUES 参数（支持单引号串与反斜杠转义）。"""
    out: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        while i < n and body[i] in ' \t\r\n':
            i += 1
        if i >= n:
            break
        if body[i] == "'":
            i += 1
            buf: list[str] = []
            while i < n:
                ch = body[i]
                if ch == '\\' and i + 1 < n:
                    buf.append(body[i + 1])
                    i += 2
                    continue
                if ch == "'":
                    i += 1
                    break
                buf.append(ch)
                i += 1
            out.append(''.join(buf))
        else:
            j = i
            while j < n and body[j] != ',':
                j += 1
            out.append(body[i:j].strip())
            i = j
        if i < n and body[i] == ',':
            i += 1
    return out


def load_archive_rows(path: Path | None = None) -> list[SimpleNamespace]:
    """解析 Navicat 导出的 payload_tm_frame INSERT 行。"""
    sql_path = path or DEFAULT_SQL
    text = sql_path.read_text(encoding='utf-8')
    rows: list[SimpleNamespace] = []
    for m in _INSERT_RE.finditer(text):
        parts = _split_sql_values(m.group(1))
        if len(parts) < 11:
            raise AssertionError(f'INSERT 字段不足: {len(parts)}')
        points = json.loads(parts[8]) if parts[8] not in ('', 'NULL') else {}
        parsed = json.loads(parts[9]) if parts[9] not in ('', 'NULL') else {}
        rows.append(
            SimpleNamespace(
                id=int(parts[0]),
                ts_ms=int(parts[1]),
                data_kind=parts[2],
                data_sub=parts[3].upper(),
                src_kind=parts[4],
                src_param=parts[5],
                parser_id=None if parts[6] in ('', 'NULL') else parts[6],
                raw_hex=parts[7],
                points_json=points,
                parsed_json=parsed,
                field_count=int(parts[10]),
            )
        )
    rows.sort(key=lambda r: (r.ts_ms, r.id))
    return rows
