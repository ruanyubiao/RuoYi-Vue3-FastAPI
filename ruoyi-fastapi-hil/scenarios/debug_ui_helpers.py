# -*- coding: utf-8 -*-
"""调试页 Playwright 公共操作。"""
from __future__ import annotations

import json
from hil.config import HIL_ROOT

TESTDATA = HIL_ROOT / "hil" / "testdata" / "debug"


def load_json(name: str):
    return json.loads((TESTDATA / name).read_text(encoding="utf-8"))


async def el_select_by_label(page, form_label: str, option_text: str, timeout: int = 15000):
    item = page.locator(".el-form-item").filter(has_text=form_label).first
    await item.locator(".el-select").click()
    dropdown = page.locator(".el-select-dropdown:visible").last
    await dropdown.wait_for(state="visible", timeout=timeout)
    opt = dropdown.locator(".el-select-dropdown__item").filter(has_text=option_text).first
    await opt.click()


async def el_select_option_containing(page, form_label: str, needle: str, timeout: int = 15000):
    item = page.locator(".el-form-item").filter(has_text=form_label).first
    await item.locator(".el-select").click()
    dropdown = page.locator(".el-select-dropdown:visible").last
    await dropdown.wait_for(state="visible", timeout=timeout)
    opt = dropdown.locator(".el-select-dropdown__item").filter(has_text=needle).first
    await opt.wait_for(state="visible", timeout=timeout)
    text = (await opt.inner_text()).strip()
    await opt.click()
    return text
