# -*- coding: utf-8 -*-
"""YJ216 CAN 控制页自定义发送冒烟（marker: hil_can）。

对齐 a8dc8f1 customSend 修复：Hex 发送不炸，历史有记录。
缺线帧黄金时只做「成功+历史」；不代替完整 wire golden。

单独跑：pytest scenarios/test_hil_yj216_custom_send.py -m hil_can
"""
from __future__ import annotations

import time

import pytest

from conftest import can_skip_reason
from hil.config import CONFIG

pytestmark = [pytest.mark.hil_can, pytest.mark.asyncio(loop_scope='session')]

CABLE = 'a'
# 与 K1501 同业务 HEX，YJ216 控制页「发送遥控指令」走 customSend/build_telecommand
PAYLOAD = '0A 91 00 01 00 01 55 55'


async def test_yj216_control_custom_send_smoke(ui, api):
    r = can_skip_reason('yj216')
    if r:
        pytest.skip(r)

    from hil.browser.pages import can_select_send, can_ui_close, can_ui_open, control_send_hex
    from hil.hw.can_sim import CanSim

    ch = CONFIG.ipc_can_channel('yj216', CABLE)
    busy = api.busy_can(ch.vendor, ch.dev_index, [ch.can_index])
    if busy and not CONFIG.allow_busy:
        pytest.fail(f'CAN 占用：{busy}')

    sim = CanSim('yj216', CONFIG, dry_run=False, cable=CABLE)
    sim.start()
    source = f'yj216_can_{CABLE}'
    try:
        try:
            api.clear_telecontrol_history(source)
        except Exception:
            pass
        page = await ui.goto('/yj216/telecontrol/control', settle_ms=800)
        await can_ui_open(page, CABLE, ch.vendor, ch.dev_index, ch.can_index)
        await can_select_send(page, CABLE)
        await control_send_hex(page, PAYLOAD)
        # 页面不应弹致命错
        await page.wait_for_timeout(800)
        err_box = page.locator('.el-message--error, .el-notification--error')
        if await err_box.count():
            txt = (await err_box.first.inner_text()).strip()
            # 允许业务告警，但 customSend 崩溃类要失败
            if any(k in txt for k in ('Traceback', 'TypeError', '异常', '500')):
                pytest.fail(f'YJ216 customSend 页面报错: {txt}')
        deadline = time.monotonic() + 8
        hist = []
        while time.monotonic() < deadline:
            hist = api.telecontrol_history(source, limit=5)
            if hist:
                break
            time.sleep(0.25)
        assert hist, 'YJ216 自定义发送后历史为空'
        # 名称侧：自定义发送应被 history_label 收成「自定义发送」或保留可读名
        names = [str(h.get('name') or '') for h in hist]
        assert not any('protocolBuild' in n for n in names), names
        await can_ui_close(page, CABLE)
    finally:
        try:
            api.ensure_hardware_idle(reason='after yj216 customSend', timeout_s=12.0)
        except Exception:
            pass
        sim.stop()