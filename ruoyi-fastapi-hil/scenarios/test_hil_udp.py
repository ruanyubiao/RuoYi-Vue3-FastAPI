# -*- coding: utf-8 -*-
"""UDP 硬件在环（marker: hil_udp）：按 scenarios/goldens/udp_*.json 闭环。

发遥控（若 case 为 send_order）：**仅** Playwright 点单板页「发送指令」。
推遥测观察：模拟器推包 + 字段黄金对比（刷新为附加断言）。
开 UDP：接口 open_udp（板页打开对话框未封装时保留）。
关 UDP：**优先**板页 UI（udp_ui_close：「关闭 UDP · host:port」）；
用例收尾 ensure_hardware_idle 仅作兜底（内部可含 close API），禁止把 close_udp/close_all 当作显式关 UDP。
"""
from __future__ import annotations

import pytest

from conftest import require_udp
from hil.config import CONFIG
from hil.goldens import GoldenCase, load_all_cases
from scenarios.hil_steps import assert_fields_on_page, assert_refreshing, assert_wire_hex

pytestmark = [pytest.mark.hil_udp, pytest.mark.asyncio(loop_scope='session')]


def _udp_cases() -> list[GoldenCase]:
    return [c for c in load_all_cases() if c.protocol.startswith('udp_')]


def _case_id(c: GoldenCase) -> str:
    return c.case_id


@pytest.mark.parametrize('case', _udp_cases(), ids=_case_id)
async def test_udp_golden_case(ui, api, case: GoldenCase):
    require_udp()
    if case.status != 'ready':
        pytest.skip(case.skip_reason or f'缺黄金 status={case.status}')

    from hil.browser.pages import pick_fields, send_order
    from hil.hw.udp_sim import UdpSim
    from hil.samples import hex_to_bytes, tm_fields

    busy = api.busy_net(CONFIG.udp_ipc_port)
    if busy:
        pytest.fail(f'UDP 端口被占用：{busy}')

    sim = UdpSim('xl_udp_dj', CONFIG)
    sim.start()
    sim.start_telemetry()
    opened = None
    try:
        ip, src = CONFIG.test_pc_ip_info()
        print(f'[HIL] UDP 测试机 IP={ip}（{src}） bind={sim.bind} -> 工控机 {sim.peer}')
        opened = api.open_udp('xl_udp_dj', remote_host=ip, remote_port=CONFIG.udp_test_pc_port,
                             local_port=CONFIG.udp_ipc_port)
        page = await ui.goto(case.page or '/xl/board/dj', settle_ms=800)

        if case.ui_action == 'send_order':
            assert case.tx_expect_hex
            expect = hex_to_bytes(case.tx_expect_hex)
            await send_order(page, case.order_id)
            # UDP 遥控：模拟器应在 rx 中看到（若协议走同一链路）；无则至少不报 API 发送
            got = None
            if hasattr(sim, 'wait_for'):
                got = sim.wait_for(lambda fr: fr == expect, timeout=10)
            elif hasattr(sim, 'rx_items'):
                import time
                end = time.monotonic() + 10
                while time.monotonic() < end:
                    for fr in list(getattr(sim, 'rx_items', [])):
                        if fr == expect:
                            got = fr
                            break
                    if got:
                        break
                    await page.wait_for_timeout(200)
            assert_wire_hex(got, case.tx_expect_hex, label=f'{case.case_id} UDP 遥控线帧')

        elif case.ui_action == 'tm_observe':
            assert sim.tx_count >= 0
            # 附加：表格应刷新
            await assert_refreshing(page, CONFIG.tm_wait_s, root='.panel-tm .payload-tm-table')
            assert sim.tx_count > 0, f'{case.case_id}: 模拟器未推遥测'
            if case.tm_golden_key:
                await assert_fields_on_page(
                    ui, api, page, case.tm_table_key or 'DJ',
                    pick_fields(tm_fields(case.tm_golden_key), set(case.tm_exclude)),
                    CONFIG.tm_wait_s, root='.panel-tm .payload-tm-table')
        else:
            pytest.fail(f'未知 ui_action={case.ui_action}')

        from hil.browser.pages import udp_ui_close
        try:
            await udp_ui_close(page, CONFIG.udp_ipc_port)
        except Exception as exc:  # noqa: BLE001
            print(f'[HIL] 成功路径网页关 UDP 失败: {exc}', flush=True)
    finally:
        # 显式关 UDP：优先网页；ensure_hardware_idle 仅作兜底（内部可含 close API）
        try:
            page = getattr(ui, 'page', None)
            if page is not None and opened:
                from hil.browser.pages import udp_ui_close
                try:
                    ok = await udp_ui_close(page, CONFIG.udp_ipc_port)
                    print(f'[HIL] 网页关闭 UDP → {ok}', flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f'[HIL] 网页关闭 UDP 失败: {exc}', flush=True)
            try:
                api.ensure_hardware_idle(reason=f'after {case.case_id}', timeout_s=12.0)
            except Exception as exc:  # noqa: BLE001
                print(f'[HIL] 收尾 ensure_idle 失败: {exc}', flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f'[HIL] 收尾关 UDP 失败: {exc}', flush=True)
        sim.stop()
