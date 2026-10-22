# -*- coding: utf-8 -*-
"""调试·遥测计算：按表/字段填 HEX 点计算，与 tmcalc_goldens.json 对比。"""
from __future__ import annotations

import pytest
from scenarios.debug_ui_helpers import load_json, el_select_option_containing

pytestmark = [pytest.mark.ui_only]

CASES = load_json("tmcalc_goldens.json")["cases"]


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    "case",
    CASES,
    ids=[f"{c['table']}:{c['field']}" for c in CASES],
)
async def test_tmcalc_field_matches_golden(ui, case):
    page = await ui.goto("/debug/tmCalc")
    await page.locator(".tm-calc-page").wait_for(timeout=15000)
    # 遥测表：选项 label 通常含 key 或 name
    needle = case.get("table_name") or case.get("table_needle") or case["table"]
    await el_select_option_containing(page, "遥测表", needle)
    await page.wait_for_timeout(400)
    # 遥测量：选项形如 "JGB001 名称"
    await el_select_option_containing(page, "遥测量", case["field"])
    # Hex（单行 el-input）
    await page.keyboard.press("Escape")  # 关掉可能残留的下拉
    hex_item = page.locator(".tm-calc-page .el-form-item").filter(has_text="Hex")
    hex_box = hex_item.locator("input").first
    await hex_box.wait_for(state="visible", timeout=10000)
    await hex_box.fill(case["hex"])
    await hex_box.blur()
    # padTail 默认勾选即可
    await page.get_by_role("button", name="计算").click()
    # 结果表第一行当前值
    row = page.locator(".tm-calc-page .el-table tbody tr").first
    await row.wait_for(timeout=15000)
    await page.wait_for_timeout(300)
    # 找「当前值」列：表头定位
    headers = page.locator(".tm-calc-page .el-table__header th")
    show_idx = None
    for i in range(await headers.count()):
        ht = (await headers.nth(i).inner_text()).strip()
        if "当前值" in ht or "值" == ht:
            show_idx = i
            break
    cells = row.locator("td")
    if show_idx is None:
        # 回退：常见布局 参数名称后一列
        show_idx = min(2, await cells.count() - 1)
    got = (await cells.nth(show_idx).inner_text()).strip()
    exp = str(case["expect_show"]).strip()
    if case.get("expect_err"):
        # 允许错误态，只要有展示
        assert got, f"期望错误态但无值: {got}"
    else:
        assert got == exp or got.replace(" ", "") == exp.replace(" ", ""), f"show got={got!r} expect={exp!r}"
    assert not ui.page_errors, ui.page_errors[:3]
