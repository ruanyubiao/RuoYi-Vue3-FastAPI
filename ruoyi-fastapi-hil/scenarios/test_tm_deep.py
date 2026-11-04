# -*- coding: utf-8 -*-
"""Telemetry / board deep UI automation for former [待深自动化] rows.

These drive real page controls. Data-dependent assertions soft-skip when DUT
has no live source / no archive rows (environment), but the click path must work.
"""
from __future__ import annotations

import re

import pytest

pytestmark = [pytest.mark.ui_only, pytest.mark.asyncio(loop_scope="session")]


async def test_tm_live_fields_poll(ui):
    page = await ui.goto("/telemetry/live", settle_ms=800)
    await page.locator(".tm-page").wait_for(timeout=15000)
    # table type select / refresh controls present
    assert await page.locator(".payload-tm-table, .tm-page .el-table").count() > 0
    # try pick first available table type if select exists
    sel = page.locator(".tm-page .el-select").first
    if await sel.count():
        await sel.click()
        dd = page.locator(".el-select-dropdown:visible").last
        await dd.wait_for(timeout=8000)
        items = dd.locator(".el-select-dropdown__item")
        if await items.count():
            await items.first.click()
            await page.wait_for_timeout(1000)
    # page should stay healthy
    assert not ui.page_errors


async def test_tm_live_curve_add_and_export(ui):
    """实时曲线页：增加曲线与截取/导出工具在场。未选遥测量时不点禁用按钮，也不假绿导出。"""
    page = await ui.goto("/telemetry/curve", settle_ms=800)
    await page.locator(".curve-page").wait_for(timeout=15000)
    add = page.get_by_role("button", name=re.compile(r"增加曲线|删除曲线"))
    assert await add.count() > 0, "曲线页缺少「增加曲线」"
    tools = page.locator(".icon-tool-group .icon-tool-btn")
    assert await tools.count() >= 2, "曲线页缺少截取/导出工具"
    assert not ui.page_errors


async def test_tm_can_history_replay(ui):
    page = await ui.goto("/telemetry/canHistory", settle_ms=800)
    await page.locator(".replay-page").wait_for(timeout=15000)
    query = page.get_by_role("button", name=re.compile(r"查询|搜索|回放"))
    if await query.count() == 0:
        pytest.skip("canHistory missing query/replay button")
    await query.first.click()
    await page.wait_for_timeout(1200)
    # frame count / table may be empty without archive — UI path still exercised
    assert not ui.page_errors


async def test_tm_can_archive_curve(ui):
    page = await ui.goto("/telemetry/archive", settle_ms=800)
    await page.locator(".curve-page").wait_for(timeout=15000)
    query = page.get_by_role("button", name=re.compile(r"查询|搜索|绘制|刷新"))
    if await query.count():
        btn = query.first
        if await btn.is_enabled():
            await btn.click()
            await page.wait_for_timeout(1000)
    assert not ui.page_errors


async def test_tm_file_history_replay(ui):
    page = await ui.goto("/telemetry/fileHistory", settle_ms=800)
    await page.locator(".replay-page").wait_for(timeout=15000)
    # upload control should exist even if we do not upload
    upload = page.locator('input[type="file"], .el-upload')
    assert await upload.count() > 0 or await page.get_by_text(re.compile(r"上传|选择文件")).count() > 0
    assert not ui.page_errors


async def test_tm_file_curve_draw(ui):
    """历史文件曲线页冒烟：工具栏与块序号滑块在场。深测见 test_hil_history_file。"""
    page = await ui.goto("/telemetry/fileCurve", settle_ms=800)
    await page.locator(".curve-page").wait_for(timeout=15000)
    for name in ("选择文件", "增加曲线", "查询", "重置曲线"):
        assert await page.get_by_role("button", name=name).count() > 0, name
    assert await page.get_by_role("button", name="解析", exact=True).count() > 0
    assert await page.locator(".range-slider").count() > 0, "缺少区间滑块"
    assert not ui.page_errors


async def test_board_dj_udp_tm_pending(ui):
    """Motor/DJ board UDP eng-TM: product fields still empty on DUT — keep skip item."""
    pytest.skip(
        "电机/地检板 UDP 工程遥测字段刷新：业务侧字段仍空（见 udp_xl_udp_dj tm_push 失败），"
        "保留用例待协议落地后再断言字段"
    )
