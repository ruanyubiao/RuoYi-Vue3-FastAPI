# -*- coding: utf-8 -*-
"""调试·时间转换：纪元+周/周内秒/毫秒换算与日期解析，对 timeconv_goldens.json。"""
from __future__ import annotations

import pytest
from scenarios.debug_ui_helpers import load_json, el_select_option_containing

pytestmark = [pytest.mark.ui_only]

GOLD = load_json("timeconv_goldens.json")
PROTO_CASES = GOLD["protocol_cases"]
DATE_CASES = GOLD["date_parse_cases"]
EPOCH_META = GOLD["epochs"]
UI = GOLD["ui"]


async def _open_timeconv(ui):
    page = await ui.goto("/debug/timeconv")
    await page.locator(".timeconv-page").wait_for(timeout=20000)
    # 页面默认开启日期自动刷新；深测前先停掉，避免结果表被 nowTick 抢写
    live = page.locator(".live-btn")
    if await live.count():
        label = ((await live.get_attribute("aria-label")) or "")
        if "暂停" in label:
            await live.click()
            await page.wait_for_timeout(100)
    await page.wait_for_timeout(400)
    return page


async def _select_epoch(page, epoch_id: str):
    needle = EPOCH_META[epoch_id]["label_contains"]
    await el_select_option_containing(page, UI["epoch_label"], needle)


async def _select_format(page, fmt: str):
    label = UI["format"][fmt]
    group = page.locator(".epoch-form .el-radio-group").first
    await group.get_by_text(label, exact=True).click()
    await page.wait_for_timeout(200)


async def _fill_fields(page, case: dict):
    for name in ("week", "sow", "ms"):
        item = page.locator(".epoch-form .el-form-item").filter(has_text=UI["fields"][name]).first
        box = item.locator("input").first
        await box.click()
        await box.fill("")
        await box.fill(str(case[name]))
        await box.blur()
    await page.wait_for_timeout(150)


async def _table_value(page, label: str) -> str:
    rows = page.locator(".result-table tbody tr")
    n = await rows.count()
    for i in range(n):
        row = rows.nth(i)
        cells = row.locator("td")
        if await cells.count() < 2:
            continue
        lab = ((await cells.nth(0).inner_text()) or "").strip()
        if lab == label or label in lab:
            mono = row.locator(".mono").first
            if await mono.count():
                return ((await mono.inner_text()) or "").strip()
            return ((await cells.nth(1).inner_text()) or "").strip()
    raise AssertionError(f"table row {label!r} not found (rows={n})")


async def _date_input_value(page) -> str:
    return ((await page.locator(".date-input input").input_value()) or "").strip()


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("case", PROTO_CASES, ids=[c["id"] for c in PROTO_CASES])
async def test_timeconv_protocol_to_unix(ui, case):
    page = await _open_timeconv(ui)
    await _select_epoch(page, case["epoch"])
    await _select_format(page, case["format"])
    await _fill_fields(page, case)
    await page.locator(".epoch-form").get_by_role("button", name=UI["calc"]).click()
    await page.wait_for_timeout(400)

    got_ms = await _date_input_value(page)
    assert got_ms == case["expect"]["unix_ms"], (
        f"date input unix_ms got={got_ms} expect={case['expect']['unix_ms']}"
    )

    iso = await _table_value(page, UI["iso_utc"])
    assert iso == case["expect"]["iso_utc"], (
        f"ISO UTC got={iso} expect={case['expect']['iso_utc']}"
    )

    unix_ms_row = await _table_value(page, UI["unix_ms"])
    assert unix_ms_row == case["expect"]["unix_ms"], f"table unix_ms got={unix_ms_row}"

    unix_sec_row = await _table_value(page, UI["unix_sec"])
    assert unix_sec_row == case["expect"]["unix_sec"], f"table unix_sec got={unix_sec_row}"

    assert not ui.page_errors, ui.page_errors[:3]


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("case", DATE_CASES, ids=[c["id"] for c in DATE_CASES])
async def test_timeconv_date_parse(ui, case):
    page = await _open_timeconv(ui)
    box = page.locator(".date-input input")
    await box.fill("")
    await box.fill(case["input"])
    await box.blur()
    await page.wait_for_timeout(500)
    iso = await _table_value(page, UI["iso_utc"])
    assert iso == case["expect_iso_utc"], f"ISO UTC got={iso} expect={case['expect_iso_utc']}"
    unix_ms_row = await _table_value(page, UI["unix_ms"])
    assert unix_ms_row == case["expect_unix_ms"], f"unix_ms got={unix_ms_row}"
    assert not ui.page_errors, ui.page_errors[:3]
