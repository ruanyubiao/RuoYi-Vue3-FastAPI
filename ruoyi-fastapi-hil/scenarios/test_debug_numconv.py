# -*- coding: utf-8 -*-
"""调试·数字转换：数字→HEX / 进制转换，与 numconv_goldens.json 对比。"""
from __future__ import annotations

import pytest
from scenarios.debug_ui_helpers import load_json, el_select_by_label

pytestmark = [pytest.mark.ui_only]

GOLD = load_json("numconv_goldens.json")
# 每类型取前 2 条，控制 UI 耗时
NUM_CASES = []
seen = {}
for c in GOLD["number_to_hex"]:
    n = seen.get(c["type"], 0)
    if n >= 2:
        continue
    seen[c["type"]] = n + 1
    NUM_CASES.append(c)
BASE_CASES = GOLD["base"]


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    "case",
    NUM_CASES,
    ids=[f"{c['type']}:{c['text']}" for c in NUM_CASES],
)
async def test_numconv_number_to_hex(ui, case):
    page = await ui.goto("/debug/numconv")
    await page.locator(".numconv-page").wait_for(timeout=15000)
    section = page.locator(".conv-section").filter(has_text="数字转 HEX")
    await el_select_by_label(page, "数字类型", case["type"])
    num_item = section.locator(".el-form-item").filter(has_text="数字").filter(has_not_text="数字类型")
    await num_item.locator("input").first.fill(case["text"])
    await section.get_by_role("button", name="计算").click()
    row = section.locator(".result-table tbody tr").first
    await row.wait_for(timeout=10000)
    cells = row.locator("td")
    # 输入 | 大端 | 小端
    be = (await cells.nth(1).inner_text()).strip()
    le = (await cells.nth(2).inner_text()).strip()
    assert be.replace(" ", "").upper() == case["expect"]["be"].replace(" ", "").upper(), (be, case["expect"]["be"])
    assert le.replace(" ", "").upper() == case["expect"]["le"].replace(" ", "").upper(), (le, case["expect"]["le"])
    assert not ui.page_errors, ui.page_errors[:3]


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    "case",
    BASE_CASES,
    ids=[f"{c['value']}_{c['from']}to{c['to']}" for c in BASE_CASES],
)
async def test_numconv_base_convert(ui, case):
    page = await ui.goto("/debug/numconv")
    await page.locator(".numconv-page").wait_for(timeout=15000)
    section = page.locator(".conv-section").filter(has_text="整数进制转换")
    await section.locator("input.el-input__inner, .base-value input").first.fill(case["value"])
    # 输入进制 el-input-number
    base_num = section.locator(".base-extra .el-input-number input, .el-input-number input").first
    await base_num.fill(str(case["from"]))
    await base_num.press("Enter")
    await section.get_by_role("button", name="计算").click()
    await page.wait_for_timeout(400)
    # 结果表：按目标进制列读取
    label_map = {2: "二进制", 8: "八进制", 10: "十进制", 16: "十六进制", 64: "Base64"}
    want_label = label_map.get(case["to"])
    table = section.locator(".base-result-table")
    headers = table.locator("thead th")
    col = None
    for i in range(await headers.count()):
        if want_label and want_label in (await headers.nth(i).inner_text()):
            col = i
            break
    body = await section.inner_text()
    exp = str(case["expect"]).upper().replace(" ", "")
    if col is not None:
        cell = table.locator("tbody tr").first.locator("td").nth(col)
        got = (await cell.inner_text()).strip().upper().replace(" ", "")
        # 二进制可能分组
        got2 = got.replace(" ", "")
        assert exp in got2 or got2 == exp, f"col {want_label} got={got} expect={case['expect']}"
    else:
        assert exp in body.upper().replace(" ", ""), f"期望 {case['expect']} 未出现: {body[:300]}"
    assert not ui.page_errors, ui.page_errors[:3]
