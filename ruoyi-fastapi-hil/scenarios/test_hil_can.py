# -*- coding: utf-8 -*-
"""CAN 硬件在环（marker: hil_can）：按 scenarios/goldens/can_*.json 逐条闭环。

接线：BIU/XL/YJ216 公用同一根 CAN（A/B）；测完一个协议全关再测下一个。
发遥控：**仅** Playwright 点指令页「发送指令」（send_command_order），禁止 API / Hex 透传框作为闭环路径。
开/关 CAN **仅**工具栏 UI（can_ui_open / can_ui_close）；用例收尾再 ensure_hardware_idle 兜底，禁止把 close_can_device/close_all 当作显式关 CAN。
"""
from __future__ import annotations

import pytest

from conftest import require_can
from hil.config import CONFIG
from hil.goldens import GoldenCase, load_all_cases
from scenarios.hil_steps import assert_tm_live, assert_wire_hex

pytestmark = [pytest.mark.hil_can, pytest.mark.asyncio(loop_scope='session')]

CABLES = ('a', 'b')


def _family_of(case: GoldenCase) -> str:
    # can_biu -> biu
    return case.protocol.split('_', 1)[1]


def _can_cases() -> list[GoldenCase]:
    return [c for c in load_all_cases() if c.protocol.startswith('can_')]


def _case_id(c: GoldenCase) -> str:
    return c.case_id


@pytest.mark.parametrize('case', _can_cases(), ids=_case_id)
async def test_can_golden_case(ui, api, case: GoldenCase):
    family = _family_of(case)
    require_can(family)
    if case.status != 'ready':
        pytest.skip(case.skip_reason or f'缺黄金 status={case.status}')

    from hil.browser.pages import (
        can_select_send,
        can_ui_close,
        can_ui_open,
        control_timed_tm,
        control_tm_request,
        send_command_order,
    )
    from hil.hw.can_sim import CanSim

    chs = {c: CONFIG.ipc_can_channel(family, c) for c in CABLES}
    col = api.collector()
    host = api.collector_host
    v0 = chs['a'].vendor
    vend = [v for v in col.get('canVendors') or [] if int(v.get('value', -1)) == v0]
    assert col.get('online'), f'采集机 {host} 不在线'
    assert vend, f'采集机 {host} 无 vendor {v0}'
    busy = api.busy_can(v0, chs['a'].dev_index, [chs[c].can_index for c in CABLES])
    if busy and not CONFIG.allow_busy:
        pytest.fail(f'采集机 {host} CAN 通道被占用：{busy}')

    cable = case.cable or 'a'
    sims = {c: CanSim(family, CONFIG, dry_run=False, cable=c) for c in CABLES}
    started: list[str] = []
    try:
        for c in CABLES:
            sims[c].start()
            started.append(c)

        # 开连接：指令页与控制页均有 CanConnectToolbar
        open_path = case.page if case.ui_action == 'send_order' else f'/{family}/telecontrol/control'
        page = await ui.goto(open_path, settle_ms=800)
        for c in CABLES:
            ch = chs[c]
            await can_ui_open(page, c, ch.vendor, ch.dev_index, ch.can_index)

        me = sims[cable]
        other = sims['b' if cable == 'a' else 'a']

        if case.ui_action == 'send_order':
            page = await ui.goto(f'/{family}/telecontrol/command', settle_ms=600)
            await can_select_send(page, cable)
            o0 = len(other.model.events)
            # UI 点击指令卡发送（禁止 API）
            await send_command_order(page, case.order_id)
            assert case.tx_expect_hex, 'ready 用例必须有 tx_expect_hex'
            from hil.samples import hex_to_bytes
            expect = hex_to_bytes(case.tx_expect_hex)
            got_ev = me.wait_for(lambda ev: ev.kind == 'telecommand' and ev.payload == expect, timeout=10)
            assert_wire_hex(
                got_ev.payload if got_ev else None,
                case.tx_expect_hex,
                label=f'{case.case_id} CAN-{cable.upper()} 遥控线帧',
            )
            assert not any(e.kind == 'telecommand' for e in other.model.events[o0:]), \
                f'{case.case_id}: 发到 {cable} 另一路也收到（A/B 映射错）'

            if case.tm_golden_key and case.tm_table_key:
                # 遥控后若挂了遥测黄金：先 UI 点遥测请求再比字段
                page = await ui.goto(f'/{family}/telecontrol/control', settle_ms=500)
                await can_select_send(page, cable)
                await control_tm_request(page)
                assert me.wait_for(lambda ev: ev.kind == 'tm_request', timeout=10)
                await assert_tm_live(ui, api, case.tm_table_key, case.tm_golden_key,
                                    set(case.tm_exclude), CONFIG.tm_wait_s)

        elif case.ui_action == 'tm_request':
            page = await ui.goto(f'/{family}/telecontrol/control', settle_ms=500)
            await can_select_send(page, cable)
            n0 = me.model.tm_req_count
            await control_tm_request(page)  # UI 按钮
            assert me.wait_for(lambda ev: ev.kind == 'tm_request', timeout=10)
            assert me.model.tm_req_count > n0
            if case.tm_golden_key and case.tm_table_key:
                await assert_tm_live(ui, api, case.tm_table_key, case.tm_golden_key,
                                    set(case.tm_exclude), CONFIG.tm_wait_s)
            # 定时遥测也走 UI（assert_tm_live 可能已跳走，回到控制页）
            page = await ui.goto(f'/{family}/telecontrol/control', settle_ms=500)
            await can_select_send(page, cable)
            n1 = me.model.tm_req_count
            await control_timed_tm(page, True)
            await page.wait_for_timeout(3500)
            await control_timed_tm(page, False)
            assert me.model.tm_req_count >= n1 + 2, f'{case.case_id}: 定时遥测请求偏少'

        else:
            pytest.fail(f'未知 ui_action={case.ui_action}')

        page = await ui.goto(open_path, settle_ms=400)
        for c in CABLES:
            await can_ui_close(page, c)
        busy_after_close = api.busy_can(v0, chs['a'].dev_index, [chs[c].can_index for c in CABLES])
        assert not busy_after_close, f'网页关 CAN 后 busy_can 仍占用：{busy_after_close}'
    finally:
        # 显式关 CAN：优先网页「关闭CAN-A/B」；ensure_hardware_idle 仅作兜底（内部可含 close API）
        try:
            page = getattr(ui, 'page', None)
            if page is not None:
                from hil.browser.pages import can_ui_close
                for c in CABLES:
                    try:
                        ok = await can_ui_close(page, c)
                        print(f'[HIL] 网页关闭 CAN-{c.upper()} → {ok}', flush=True)
                    except Exception as exc:  # noqa: BLE001
                        print(f'[HIL] 网页关闭 CAN-{c.upper()} 失败: {exc}', flush=True)
            try:
                api.ensure_hardware_idle(reason=f'after {case.case_id}', timeout_s=12.0)
            except Exception as exc:  # noqa: BLE001
                print(f'[HIL] 收尾 ensure_idle 失败: {exc}', flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f'[HIL] 收尾关 CAN 失败: {exc}', flush=True)
        for c in started:
            sims[c].stop()


@pytest.mark.skip(reason='待确认：XL 实时遥控包下位机应答格式未定义，见 TODO.md #1 / reply_map custom_rules')
async def test_xl_realtime_tc_reply():
    """XL 实时遥控 → 下位机应答（待补黄金后纳入 goldens）。"""
