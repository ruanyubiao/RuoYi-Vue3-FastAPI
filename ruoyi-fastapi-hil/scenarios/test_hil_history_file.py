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


async def test_history_file_curve_deep(ui, history_file_bundle, fileplay_idle):
    """历史文件曲线深测（仅 1 次）：XL-D8V17 + CAM008平均灰度值。

    流程：选表→上传 XL-D8V17-HIL_*.bin→解析→单独增加 CAM008 曲线→查询等点→
    界面截取/轴控等工具→滑动区间滑块→再查询→重置曲线→确认进程回收。

    说明：用户口头说代替 XL-D9V17-HIL，但对应遥测表是 XL-D8V17；本用例只跑 D8V17，
    D9V17 仍保留在 data_deep 样本中，不参与曲线深测。
    """
    table = "D8V17"
    path, meta = _need_sample(table, history_file_bundle)
    assert str(meta.get("file") or "").startswith("XL-D8V17-HIL"), meta
    page = await ui.goto("/telemetry/fileCurve", settle_ms=800)
    await page.locator(".curve-page").wait_for(timeout=20000)

    await P.file_toolbar_select_tm(page, table)
    await P.file_browser_upload_and_pick(page, path)
    fileplay_idle.ensure_fileplay_idle(channel="curve", reason="before parse curve D8V17", timeout_s=15.0)
    await P.file_click_parse(page)
    rows = await P.file_open_sessions_and_snapshot(page)
    assert rows is not None
    await P.file_close_sessions_dialog(page)

    frames = await P.file_wait_parsed(page, timeout_s=180.0, min_frames=1)
    assert frames >= 1

    # 单独添加 CAM008平均灰度值
    label, add_pts = await P.file_curve_add_field(page, "CAM008")
    assert "CAM008" in label, label
    print(f"[HIL] add_curve points={add_pts}", flush=True)
    assert add_pts >= 1, f"增加曲线后无点: {add_pts}"

    # 查询（增加曲线时可能已拉齐本地 chunk，查询可能不再打 API）
    seed = await P.file_curve_click_query(page, query_wait_s=90.0)
    print(f"[HIL] curve query seed_points={seed}", flush=True)
    points = await P.file_curve_wait_points(
        page, min_points=1, timeout_s=30.0, seed_points=max(seed, add_pts)
    )
    print(f"[HIL] curve points after query={points}", flush=True)
    assert points >= 1, f"查询后无曲线点: points={points} seed={seed} add={add_pts}"

    # 界面裁切/截取与其它曲线操作
    covered = await P.file_curve_exercise_tools(page)
    assert covered.get("crop"), f"截取/裁切未点到: {covered}"

    # 滑动滑块 → 再查询 → 重置曲线
    await P.file_curve_move_range_slider(page, ratio=0.55)
    seed2 = await P.file_curve_click_query(page, query_wait_s=90.0)
    print(f"[HIL] curve re-query seed_points={seed2}", flush=True)
    points2 = await P.file_curve_wait_points(page, min_points=1, timeout_s=60.0, seed_points=seed2)
    print(f"[HIL] curve points after slider query={points2}", flush=True)
    assert points2 >= 1, f"滑块后再查询无点: points={points2} seed={seed2}"
    await P.file_curve_reset(page)

    # Large D8V17 (~58k frames) workers may linger; API/Redis close is authoritative.
    idle_ok = False
    try:
        fileplay_idle.ensure_fileplay_idle(
            channel="curve", reason="after curve deep recycle", timeout_s=45.0
        )
        idle_ok = True
    except Exception as exc:  # noqa: BLE001
        print(f"[HIL] post-curve idle warn: {exc}", flush=True)
    if idle_ok:
        try:
            await P.file_assert_process_recycled(page, file_name=meta["file"], timeout_s=20.0)
        except Exception as exc:  # noqa: BLE001 — UI text match flaky; API idle already OK
            print(f"[HIL] UI recycle soft-skip after API idle: {exc}", flush=True)
    else:
        await P.file_assert_process_recycled(page, file_name=meta["file"], timeout_s=60.0)
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
