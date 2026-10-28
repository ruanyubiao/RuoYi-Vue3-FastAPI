# -*- coding: utf-8 -*-
"""调试·校验计算：填 HEX、选算法、计算，与 checksum_goldens.json 对比。"""
from __future__ import annotations

import pytest
from hil.debug_algo import CRC_MODELS, SUM_MODELS
from scenarios.debug_ui_helpers import load_json

pytestmark = [pytest.mark.ui_only]

GOLD = load_json("checksum_goldens.json")
CASES = GOLD["cases"]
PREFS_KEY = "payload:checksum:algos:v1"
NAME_TO_ID = {m["name"]: m["id"] for m in SUM_MODELS + CRC_MODELS}


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_checksum_calc_matches_golden(ui, case):
    page = await ui.goto("/debug/checksum")
    await page.evaluate(
        "([key, ids]) => localStorage.setItem(key, JSON.stringify(ids))",
        [PREFS_KEY, case["algo_ids"]],
    )
    await page.reload()
    await page.locator(".checksum-page").wait_for(timeout=15000)
    # 录入 HEX
    await page.locator(".hex-view").click()
    box = page.locator(".el-dialog:visible textarea").first
    await box.wait_for(state="visible", timeout=10000)
    await box.fill(case["hex"])
    await page.locator(".el-dialog:visible").get_by_role("button", name="确定").click()
    await page.wait_for_timeout(200)
    # 算法选择：确保勾选
    await page.get_by_role("button", name="算法选择").click()
    await page.locator(".el-drawer:visible .el-tree, .el-tree").first.wait_for(timeout=10000)
    await page.evaluate(
        """() => {
      document.querySelectorAll('.el-drawer .el-tree .el-checkbox').forEach(el => {
        if (!el.classList.contains('is-checked')) el.click();
      });
    }"""
    )
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(200)
    if case.get("start") not in (None, 0) or case.get("end") not in (None, -1):
        nums = page.locator(".checksum-page .el-input-number input")
        if await nums.count() >= 2:
            await nums.nth(0).fill(str(case["start"]))
            await nums.nth(1).fill(str(case["end"]))
            await page.locator(".checksum-page").click()
    await page.get_by_role("button", name="计算").click()
    table = page.locator(".checksum-page .result-table")
    await table.locator("tbody tr").first.wait_for(timeout=15000)
    await page.wait_for_timeout(300)
    rows = table.locator("tbody tr")
    got = {}  # name -> {hex, hexLe}
    for i in range(await rows.count()):
        cells = rows.nth(i).locator("td")
        name = (await cells.nth(0).inner_text()).strip()
        # col1=HEX大端 col2=HEX小端（与 checksum/index.vue 一致）
        hex_be = (await cells.nth(1).inner_text()).strip().replace(" ", "").upper() if await cells.count() > 1 else ""
        hex_le = (await cells.nth(2).inner_text()).strip().replace(" ", "").upper() if await cells.count() > 2 else ""
        got[name] = {"hex": hex_be, "hexLe": hex_le}
    bad = []
    for name, vals in got.items():
        aid = NAME_TO_ID.get(name)
        if not aid or aid not in case["expect"]:
            continue
        exp = case["expect"][aid]
        exp_be = str(exp["hex"]).upper().replace(" ", "")
        exp_le = str(exp.get("hexLe") or "").upper().replace(" ", "")
        if vals["hex"] != exp_be:
            bad.append(f"{name} BE: got={vals['hex']} expect={exp_be}")
        if exp_le and vals["hexLe"] != exp_le:
            bad.append(f"{name} LE: got={vals['hexLe']} expect={exp_le}")
    assert got, "结果表为空"
    assert not bad, "; ".join(bad[:10])
    assert not ui.page_errors, ui.page_errors[:3]
