# -*- coding: utf-8 -*-
"""首页/遥测 → 历史文件数据 & 历史文件曲线 深测。

流程：选遥测表 → 上传样本 → 解析 → 解析进程可见 → 页面操作 → 确认进程回收。
样本：hil/testdata/history_file/（zip 入库，跑时再解压）。

改进：
- 同名覆盖上传只抽测 1 个代表表（overwrite_probe_table），其它表只上传一次。
- 用例前后 ensure_fileplay_idle，避免 Redis 僵尸槽把解析队列占满。
"""
from __future__ import annotations

import pytest

from hil.browser import pages as P
from hil.config import CONFIG
from hil.history_file import (
    HISTORY_FILE_TABLES,
    cleanup_history_file_data,
    ensure_history_file_data,
    overwrite_probe_table,
    sample_path_for,
    skip_reason,
)
from hil.ipc_api import IpcApi

pytestmark = [pytest.mark.ui_only, pytest.mark.asyncio(loop_scope="session")]


@pytest.fixture(scope="session")
def history_file_bundle():
    """会话级：删旧 data → 解压 zip；失败也尽量删 data。"""
    data_dir, manifest = ensure_history_file_data(force=True)
    try:
        yield data_dir, manifest
    finally:
        cleanup_history_file_data()


@pytest.fixture(scope="session")
def fileplay_api():
    """登录一次，供 ensure_fileplay_idle 使用。"""
    api = IpcApi(CONFIG)
    api.login()
    return api


@pytest.fixture
def fileplay_idle(fileplay_api):
    """深测用例前后清解析进程/缓存（不解压冒烟，避免无 IPC 时挂）。"""
    fileplay_api.ensure_fileplay_idle(reason="history_file setup", timeout_s=25.0)
    yield fileplay_api
    try:
        fileplay_api.ensure_fileplay_idle(reason="history_file teardown", timeout_s=25.0)
    except Exception as exc:  # noqa: BLE001
        print(f"[HIL] history_file teardown fileplay idle 失败: {exc}", flush=True)


def _need_sample(table: str, bundle):
    data_dir, manifest = bundle
    reason = skip_reason(table, manifest)
    if reason:
        pytest.skip(reason)
    path = sample_path_for(table, data_dir, manifest)
    if path is None:
        pytest.skip(f"样本文件缺失: {table}")
    return path, manifest["tables"][table]


@pytest.mark.parametrize("table", HISTORY_FILE_TABLES, ids=lambda t: t.replace(":", "_"))
async def test_history_file_data_deep(ui, history_file_bundle, fileplay_idle, table):
    """历史文件数据：上传解析 + 选帧操作 + 进程回收。"""
    path, meta = _need_sample(table, history_file_bundle)
    page = await ui.goto("/telemetry/fileHistory", settle_ms=800)
    await page.locator(".replay-page").wait_for(timeout=20000)

    await P.file_toolbar_select_tm(page, table)
    await P.file_browser_upload_and_pick(page, path)
    fileplay_idle.ensure_fileplay_idle(channel="history", reason=f"before parse {table}", timeout_s=15.0)
    await P.file_click_parse(page)
    rows = await P.file_open_sessions_and_snapshot(page)
    assert rows is not None
    await P.file_close_sessions_dialog(page)

    frames = await P.file_wait_parsed(page, timeout_s=120.0, min_frames=1)
    assert frames >= 1
    await P.file_history_exercise_frames(page, settle_ms=2000)
    await P.file_assert_process_recycled(page, file_name=meta["file"], timeout_s=90.0)
    assert not ui.page_errors, ui.page_errors[:3]


@pytest.mark.parametrize("table", HISTORY_FILE_TABLES, ids=lambda t: t.replace(":", "_"))
async def test_history_file_curve_deep(ui, history_file_bundle, fileplay_idle, table):
    """历史文件曲线：上传解析 + 加曲线/查询/工具 + 进程回收。"""
    path, meta = _need_sample(table, history_file_bundle)
    page = await ui.goto("/telemetry/fileCurve", settle_ms=800)
    await page.locator(".curve-page").wait_for(timeout=20000)

    await P.file_toolbar_select_tm(page, table)
    await P.file_browser_upload_and_pick(page, path)
    fileplay_idle.ensure_fileplay_idle(channel="curve", reason=f"before parse curve {table}", timeout_s=15.0)
    await P.file_click_parse(page)
    rows = await P.file_open_sessions_and_snapshot(page)
    assert rows is not None
    await P.file_close_sessions_dialog(page)

    await P.file_wait_parsed(page, timeout_s=120.0, min_frames=1)
    await P.file_curve_add_fields(page, count=3)
    await P.file_curve_query_and_tools(page, query_wait_s=25.0)
    await P.file_assert_process_recycled(page, file_name=meta["file"], timeout_s=90.0)
    assert not ui.page_errors, ui.page_errors[:3]


async def test_history_file_overwrite_upload_once(ui, history_file_bundle, fileplay_idle):
    """同名文件再上传 → 点「覆盖」：只抽测一个代表表。"""
    data_dir, manifest = history_file_bundle
    table = overwrite_probe_table(manifest)
    if not table:
        pytest.skip("manifest 无可用样本表")
    path, meta = _need_sample(table, (data_dir, manifest))
    page = await ui.goto("/telemetry/fileHistory", settle_ms=800)
    await page.locator(".replay-page").wait_for(timeout=20000)
    await P.file_toolbar_select_tm(page, table)
    # first upload
    await P.file_browser_upload_and_pick(page, path)
    # second upload same name → overwrite confirm
    await P.file_browser_upload_and_pick(page, path)
    fileplay_idle.ensure_fileplay_idle(channel="history", reason="before overwrite parse", timeout_s=15.0)
    await P.file_click_parse(page)
    frames = await P.file_wait_parsed(page, timeout_s=120.0, min_frames=1)
    assert frames >= 1
    await P.file_assert_process_recycled(page, file_name=meta["file"], timeout_s=90.0)
    assert not ui.page_errors, ui.page_errors[:3]


async def test_history_file_data_unpack_smoke(history_file_bundle):
    """纯数据冒烟：确认 zip 能解压且至少有一份样本；未 skip 表帧数 >= min_frames(manifest)。"""
    data_dir, manifest = history_file_bundle
    tables = manifest.get("tables") or {}
    assert tables, "manifest.tables 为空"
    min_frames = int(manifest.get("min_frames") or 1000)
    for info in tables.values():
        assert (data_dir / info["file"]).is_file(), info["file"]
        assert int(info.get("frame_count_sample") or 0) >= min_frames, info
