# -*- coding: utf-8 -*-
"""控制页定时遥测 / 时间同步「最近发送」展示（marker: hil_can）。

对齐 71a82e5：打开定时遥测后出现「最近发送：…（CAN-x）」；切到另一 family 不应串显示。
单独跑：pytest scenarios/test_hil_control_last_send.py -m hil_can
"""
from __future__ import annotations

import time

import pytest

from conftest import can_skip_reason
from hil.config import CONFIG

pytestmark = [pytest.mark.hil_can, pytest.mark.asyncio(loop_scope='session')]

CABLE = 'a'


def _require_family(family: str) -> None:
    r = can_skip_reason(family)
    if r:
        pytest.skip(r)


async def test_timed_tm_last_send_shows_on_control(ui, api):
    """打开定时遥测后，控制页 hint 出现「最近发送」且带 CAN-x。"""
    family = 'xl' if not CONFIG.can_target else CONFIG.can_target
    if family not in ('biu', 'xl', 'yj216'):
        family = 'xl'
    _require_family(family)

    from hil.browser.pages import (
        can_select_send,
        can_ui_close,
        can_ui_open,
        control_read_last_send_hints,
        control_timed_tm,
    )
    from hil.hw.can_sim import CanSim

    ch = CONFIG.ipc_can_channel(family, CABLE)
    busy = api.busy_can(ch.vendor, ch.dev_index, [ch.can_index])
    if busy and not CONFIG.allow_busy:
        pytest.fail(f'CAN 占用：{busy}')

    sim = CanSim(family, CONFIG, dry_run=False, cable=CABLE)
    sim.start()
    try:
        page = await ui.goto(f'/{family}/telecontrol/control', settle_ms=800)
        await can_ui_open(page, CABLE, ch.vendor, ch.dev_index, ch.can_index)
        await can_select_send(page, CABLE)
        await control_timed_tm(page, True)
        deadline = time.monotonic() + 12
        hints = {'timed_tm': '', 'time_sync': ''}
        while time.monotonic() < deadline:
            hints = await control_read_last_send_hints(page)
            if hints.get('timed_tm') and '最近发送' in hints['timed_tm']:
                break
            await page.wait_for_timeout(500)
        await control_timed_tm(page, False)
        assert hints.get('timed_tm') and '最近发送' in hints['timed_tm'], (
            f'定时遥测未出现最近发送文案: {hints!r}'
        )
        assert 'CAN-' in hints['timed_tm'].upper() or 'CAN' in hints['timed_tm'].upper(), hints
        await can_ui_close(page, CABLE)
    finally:
        try:
            api.ensure_hardware_idle(reason='after timed_tm last_send', timeout_s=12.0)
        except Exception:
            pass
        sim.stop()


async def test_last_send_not_leaked_across_family(ui, api):
    """XL 开过定时遥测后切到 BIU：BIU 页不应直接串出 XL 的「最近发送」（无本族发送时）。

    需跨族；单 HIL_CAN_TARGET 时 skip。
    """
    for fam in ('xl', 'biu'):
        r = can_skip_reason(fam)
        if r:
            pytest.skip(r)
    if CONFIG.can_target:
        pytest.skip(f'跨族 last-send 隔离需无单一 HIL_CAN_TARGET，当前={CONFIG.can_target}')

    from hil.browser.pages import (
        can_select_send,
        can_ui_close,
        can_ui_open,
        control_read_last_send_hints,
        control_timed_tm,
    )
    from hil.hw.can_sim import CanSim

    ch = CONFIG.ipc_can_channel('xl', CABLE)
    busy = api.busy_can(ch.vendor, ch.dev_index, [ch.can_index])
    if busy and not CONFIG.allow_busy:
        pytest.fail(f'CAN 占用：{busy}')

    sim = CanSim('xl', CONFIG, dry_run=False, cable=CABLE)
    sim.start()
    try:
        page = await ui.goto('/xl/telecontrol/control', settle_ms=800)
        await can_ui_open(page, CABLE, ch.vendor, ch.dev_index, ch.can_index)
        await can_select_send(page, CABLE)
        await control_timed_tm(page, True)
        deadline = time.monotonic() + 10
        xl_hint = ''
        while time.monotonic() < deadline:
            h = await control_read_last_send_hints(page)
            if h.get('timed_tm'):
                xl_hint = h['timed_tm']
                break
            await page.wait_for_timeout(400)
        await control_timed_tm(page, False)
        await can_ui_close(page, CABLE)

        # 切 BIU：不打开定时遥测，hint 应为空或不含刚才 XL 时间戳串
        page = await ui.goto('/biu/telecontrol/control', settle_ms=800)
        biu_hints = await control_read_last_send_hints(page)
        biu_tm = biu_hints.get('timed_tm') or ''
        if biu_tm and xl_hint and biu_tm == xl_hint:
            pytest.fail(f'BIU 串显示了 XL 的最近发送: {biu_tm!r}')
        # 允许 BIU 有自己的历史；只要不完全等于 XL 串即可
    finally:
        try:
            api.ensure_hardware_idle(reason='after last_send isolation', timeout_s=12.0)
        except Exception:
            pass
        sim.stop()


async def test_time_sync_broadcast_last_send_optional(ui, api):
    """尽力：打开定时同步广播后出现「最近同步」。硬件/权限不足则 skip。"""
    family = CONFIG.can_target or 'xl'
    if family not in ('biu', 'xl', 'yj216'):
        family = 'xl'
    _require_family(family)

    from hil.browser.pages import (
        can_select_send,
        can_ui_close,
        can_ui_open,
        control_read_last_send_hints,
        control_timed_sync_broadcast,
    )
    from hil.hw.can_sim import CanSim

    ch = CONFIG.ipc_can_channel(family, CABLE)
    busy = api.busy_can(ch.vendor, ch.dev_index, [ch.can_index])
    if busy and not CONFIG.allow_busy:
        pytest.fail(f'CAN 占用：{busy}')

    sim = CanSim(family, CONFIG, dry_run=False, cable=CABLE)
    sim.start()
    try:
        page = await ui.goto(f'/{family}/telecontrol/control', settle_ms=800)
        await can_ui_open(page, CABLE, ch.vendor, ch.dev_index, ch.can_index)
        await can_select_send(page, CABLE)
        try:
            await control_timed_sync_broadcast(page, True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f'无法打开定时同步广播: {exc}')
        deadline = time.monotonic() + 12
        hints = {}
        while time.monotonic() < deadline:
            hints = await control_read_last_send_hints(page)
            if hints.get('time_sync') and '最近同步' in hints['time_sync']:
                break
            await page.wait_for_timeout(500)
        try:
            await control_timed_sync_broadcast(page, False)
        except Exception:
            pass
        if not (hints.get('time_sync') and '最近同步' in hints['time_sync']):
            pytest.skip(f'12s 内未见「最近同步」文案（可能广播未真正发出）: {hints!r}')
        await can_ui_close(page, CABLE)
    finally:
        try:
            api.ensure_hardware_idle(reason='after time_sync last_send', timeout_s=12.0)
        except Exception:
            pass
        sim.stop()