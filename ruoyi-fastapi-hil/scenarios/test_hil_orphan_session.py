# -*- coding: utf-8 -*-
"""孤儿 session 对账（marker: ui_only / hil_can 轻量）。

对齐 e433496：sessions 与 registry alive 不一致时的孤儿候选。
HIL 不能安全杀掉采集进程，故：
- 只读 orphan_session_report
- 若发现孤儿则 fail（环境脏）
- 无法注入真孤儿时本条作为健康检查通过

单独跑：pytest scenarios/test_hil_orphan_session.py -m ui_only
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.ui_only]


def test_orphan_session_reconcile_readonly(api):
    """只读对账：当前不应残留「session 有、registry 无 alive」的孤儿。"""
    report = api.orphan_session_report()
    orphans = report.get('orphans') or []
    assert not orphans, (
        f'发现孤儿 session（刷新首页仍可能显示已死连接）: {orphans!r}；'
        f'请 ensure_hardware_idle / 检查采集端。report={report!r}'
    )


@pytest.mark.asyncio(loop_scope='session')
async def test_home_open_time_not_from_dead_session(ui, api):
    """尽力：首页打开后，若 orphan 为空则通过；有孤儿则 fail。

    无法在自动化里真杀采集进程注入孤儿 —— 真注入请手工/运维脚本，本条不假绿。
    """
    report = api.orphan_session_report()
    if report.get('orphans'):
        await ui.goto('/index', settle_ms=800)
        await ui.screenshot('orphan_sessions_on_home')
        pytest.fail(f'首页检查前已有孤儿 session: {report["orphans"]!r}')
    page = await ui.goto('/index', settle_ms=600)
    # 冒烟：页面可开且无 JS 错
    await page.locator('.device-service-page, .app-container').first.wait_for(timeout=15000)
    assert not ui.page_errors, ui.page_errors[:3]