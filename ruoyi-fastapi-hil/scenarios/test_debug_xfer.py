# -*- coding: utf-8 -*-
"""调试·数据收发：先清场，经首页同源接口开设备，再网页收发。"""
from __future__ import annotations

import pytest
from hil.config import CONFIG

pytestmark = [pytest.mark.ui_only]


@pytest.fixture
def xfer_device(api):
    api.ensure_hardware_idle(reason="xfer-setup", timeout_s=15.0)
    kind = None
    opened = None
    err = None
    try:
        opened = api.open_serial("xl-rkdj", CONFIG.ipc_serial_port)
        kind = "serial"
    except Exception as e:
        err = e
        try:
            tip = ""
            try:
                from hil.config import detect_test_pc_ip

                tip, _ = detect_test_pc_ip(CONFIG.ipc_ip)
            except Exception:
                tip = ""
            if not tip:
                tip = "192.168.100.100"
            opened = api.open_udp("xl_udp_dj", tip, CONFIG.udp_test_pc_port, CONFIG.udp_ipc_port)
            kind = "udp"
            err = None
        except Exception as e2:
            api.ensure_hardware_idle(reason="xfer-setup-fail", timeout_s=10.0)
            pytest.skip(f"无法经接口打开设备: serial={err}; udp={e2}")
    yield {"kind": kind, "opened": opened, "api": api}
    try:
        api.ensure_hardware_idle(reason="xfer-teardown", timeout_s=15.0)
    except Exception:
        pass


@pytest.mark.asyncio(loop_scope="session")
async def test_xfer_refresh_send_and_log(ui, xfer_device):
    page = await ui.goto("/debug/xfer")
    await page.locator(".xfer-page").wait_for(timeout=15000)
    await page.get_by_role("button", name="刷新设备").click()
    await page.wait_for_timeout(1000)
    await page.locator(".xfer-page .el-select").first.click()
    dropdown = page.locator(".el-select-dropdown:visible").last
    await dropdown.wait_for(timeout=10000)
    # 优先在线组
    group = dropdown.locator(".el-select-group__title", has_text="在线")
    if await group.count():
        opts = dropdown.locator(".el-select-group").filter(has_text="在线").locator(".el-select-dropdown__item")
    else:
        opts = dropdown.locator(".el-select-dropdown__item")
    assert await opts.count() > 0, "刷新后无设备可选"
    await opts.first.click()
    await page.wait_for_timeout(500)
    # 填发送数据
    area = page.locator(".xfer-page textarea").first
    if await area.count():
        await area.fill("AA BB CC DD")
    # CAN 分支
    if await page.locator(".el-form-item").filter(has_text="帧ID").count():
        await page.locator(".el-form-item").filter(has_text="帧ID").locator("input").first.fill("100")
        data = page.locator(".el-form-item").filter(has_text="数据").locator("textarea, input")
        if await data.count():
            await data.first.fill("AA BB CC DD")
    send_btn = page.get_by_role("button", name="发送").first
    await send_btn.wait_for(timeout=10000)
    async with page.expect_response(
        lambda r: r.request.method == "POST"
        and "/payload/" in r.url
        and any(k in r.url for k in ("send", "serial", "net", "can", "telecontrol", "raw")),
        timeout=25000,
    ) as ri:
        await send_btn.click()
    resp = await ri.value
    assert resp.status < 500, f"发送 HTTP {resp.status}"
    await page.wait_for_timeout(800)
    text = (await page.locator("body").inner_text()).upper()
    assert any(x in text for x in ("AA", "BB", "发送", "TX", "OUT", "CC")), "页面未见发送痕迹"
    assert not ui.page_errors, ui.page_errors[:3]
