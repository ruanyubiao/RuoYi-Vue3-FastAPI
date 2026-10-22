# -*- coding: utf-8 -*-
"""数据库结构对照（marker: db_schema）。

本地真源：ruoyi-fastapi-backend/sql/ruoyi-fastapi-my.sql + sql/patches/*.sql
目标：DUT MySQL information_schema，对照**全部**本地 CREATE TABLE（含 sys_*）。
运行期表 apscheduler_jobs / schema_version 可存在于远端但不要求在本地 SQL。
"""
from __future__ import annotations

import pytest

from hil.report.db_schema import (
    db_connect_kwargs,
    diff_schema,
    fetch_remote_schema,
    load_local_schema,
)

pytestmark = [pytest.mark.db_schema]

PAYLOAD_TABLES = ("payload_cmd_sequence", "payload_tm_frame", "payload_tx_log")
RUNTIME_ONLY = {"apscheduler_jobs", "schema_version"}


def _remote_or_skip():
    kw = db_connect_kwargs()
    if not kw:
        pytest.skip("无数据库连接配置：请设 HIL_DB_HOST/HIL_DB_PASSWORD 或保证 backend/.env.prod 可读")
    try:
        return fetch_remote_schema(kw), kw
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"无法连接目标库 {kw.get('host')}:{kw.get('port')}/{kw.get('database')}: {exc}")


def test_schema_tables_present():
    """本地 SQL 中每一张表在 DUT 都必须存在。"""
    local = load_local_schema()
    remote, _kw = _remote_or_skip()
    d = diff_schema(local, remote)
    assert not d["missing_tables"], f"目标库缺表: {d['missing_tables']}"


def test_schema_columns_match():
    """本地 SQL 各表字段在 DUT 无缺失（多余列不失败）。"""
    local = load_local_schema()
    remote, _kw = _remote_or_skip()
    d = diff_schema(local, remote)
    assert not d["missing_columns"], f"目标库缺字段: {d['missing_columns']}"


def test_schema_payload_tables():
    """业务三表额外点名（与全表对照互补）。"""
    local = load_local_schema()
    remote, _kw = _remote_or_skip()
    missing_t = [t for t in PAYLOAD_TABLES if t not in remote]
    assert not missing_t, f"缺 payload 表: {missing_t}"
    miss_cols = {}
    for t in PAYLOAD_TABLES:
        miss = [c for c in local.get(t, []) if c not in set(remote.get(t, []))]
        if miss:
            miss_cols[t] = miss
    assert not miss_cols, f"payload 表缺字段: {miss_cols}"


def test_schema_extra_remote_tables_noted():
    """远端多出的表仅记录（运行期表允许）；不失败。"""
    local = load_local_schema()
    remote, _kw = _remote_or_skip()
    d = diff_schema(local, remote)
    extras = [t for t in d["extra_tables"] if t not in RUNTIME_ONLY]
    # 仅打印，便于报告；框架表若在本地 SQL 则不会出现在 extra
    print(f"[db_schema] remote_extra_beyond_runtime={extras} runtime_ok={sorted(RUNTIME_ONLY & set(remote))}")
