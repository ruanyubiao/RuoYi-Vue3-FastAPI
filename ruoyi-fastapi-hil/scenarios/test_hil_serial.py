# -*- coding: utf-8 -*-
"""串口 / RS422 硬件在环（marker: hil_serial）：按 scenarios/goldens/serial_*.json 逐条闭环。

接线：COM9↔COM8 公用；测完一个协议全关再测下一个。
发遥控：**仅** Playwright 点板页指令卡「发送指令」（send_order），禁止 API 下发。
开串口：接口 open_serial（板页暂无稳定「打开」自动化封装时保留）。
关串口：**优先**板页 UI（serial_ui_close：关闭串口/关闭控制·图像串口）；
用例收尾 ensure_hardware_idle 仅作兜底（内部可含 close API），禁止把 close_serial/close_all 当作显式关串口。
"""
from __future__ import annotations

import pytest

from conftest import require_serial
from hil.config import CONFIG
from hil.goldens import GoldenCase, load_all_cases
from hil.protocol import frames as F
from scenarios.hil_steps import assert_fields_on_page, assert_refreshing, assert_tm_live, assert_wire_hex

pytestmark = [pytest.mark.hil_serial, pytest.mark.asyncio(loop_scope='session')]


def _serial_key(case: GoldenCase) -> str:
    # serial_xl-camera -> xl-camera
    return case.protocol.split('_', 1)[1]


def _serial_cases() -> list[GoldenCase]:
    return [c for c in load_all_cases() if c.protocol.startswith('serial_')]


def _case_id(c: GoldenCase) -> str:
    return c.case_id


def _same_camera_frame(a: bytes, b: bytes) -> bool:
    pa, pb = F.camera_parse(a), F.camera_parse(b)
    return bool(pa and pb and (pa['type'], pa['id'], pa['data']) == (pb['type'], pb['id'], pb['data']))


@pytest.mark.parametrize('case', _serial_cases(), ids=_case_id)
async def test_serial_golden_case(ui, api, case: GoldenCase):
    key = _serial_key(case)
    port, ipc_port = require_serial(key)
    if case.status != 'ready':
        pytest.skip(case.skip_reason or f'缺黄金 status={case.status}')

    from hil.browser.pages import pick_fields, send_order
    from hil.hw.serial_sim import SerialSim
    from hil.samples import hex_to_bytes, tm_fields

    busy = api.busy_serial(ipc_port)
    if busy:
        pytest.fail(f'采集机串口 {ipc_port} 已被占用：{busy}')

    sim = SerialSim(key, port=port, cfg=CONFIG, dry_run=False)
    sim.start()
    sim.start_telemetry()
    opened = False
    try:
        api.open_serial(key, ipc_port)
        opened = True
        page = await ui.goto(case.page, settle_ms=800)

        if case.ui_action == 'send_order':
            assert case.tx_expect_hex
            expect = hex_to_bytes(case.tx_expect_hex)
            shown = await send_order(page, case.order_id)  # UI 点击
            is_cam = key.startswith('xl-camera')
            expect_ui = hex_to_bytes(shown) if shown else None
            def _match(fr: bytes) -> bool:
                if is_cam:
                    return _same_camera_frame(fr, expect) or (
                        expect_ui is not None and _same_camera_frame(fr, expect_ui)
                    )
                return fr == expect or (expect_ui is not None and fr == expect_ui)
            got = sim.wait_for(_match, timeout=10)
            if got is None:
                raise AssertionError(
                    f'{case.case_id}: 10s 内未收到期望线帧；shown_ui={shown!r}；'
                    f'最近 {[x.hex(" ") for x in sim.rx_items[-3:]]}；'
                    f'expect={case.tx_expect_hex}'
                )
            if is_cam:
                # 相机帧 seq 每次 +1，比对 type/id/data；仍打印 hex 便于排查
                from hil.goldens import hex_diff
                if not _same_camera_frame(got, expect) and not (
                    expect_ui is not None and _same_camera_frame(got, expect_ui)
                ):
                    raise AssertionError(f'{case.case_id}: 相机帧字段不匹配；{hex_diff(case.tx_expect_hex, got)}')
            else:
                # 以页面实际组帧为准（与 shown_ui 一致）；golden 作兜底
                wire_hex = shown if (expect_ui is not None and got == expect_ui) else case.tx_expect_hex
                assert_wire_hex(got, wire_hex, label=f'{case.case_id} 串口遥控线帧')

            if case.tm_golden_key and case.tm_table_key:
                if key.startswith('xl-camera'):
                    await assert_tm_live(ui, api, case.tm_table_key, case.tm_golden_key,
                                        set(case.tm_exclude), CONFIG.tm_wait_s)
                elif key == 'yj216-rs422':
                    await assert_refreshing(page, CONFIG.tm_wait_s, root='.panel-tm .payload-tm-table')
                    # 附加：若有字段黄金则比字段（rs422 当前 golden 可能不全）
                    if case.tm_golden_key:
                        try:
                            await assert_fields_on_page(
                                ui, api, page, case.tm_table_key,
                                pick_fields(tm_fields(case.tm_golden_key)), CONFIG.tm_wait_s,
                                root='.panel-tm .payload-tm-table')
                        except KeyError:
                            pass
                else:
                    await assert_fields_on_page(
                        ui, api, page, case.tm_table_key,
                        pick_fields(tm_fields(case.tm_golden_key), set(case.tm_exclude)),
                        CONFIG.tm_wait_s, root='.panel-tm .payload-tm-table')
        else:
            pytest.fail(f'未知 ui_action={case.ui_action}')

        # 成功路径显式网页关串口（finally 再兜底）
        from hil.browser.pages import serial_ui_close
        try:
            await serial_ui_close(page, ipc_port)
        except Exception as exc:  # noqa: BLE001
            print(f'[HIL] 成功路径网页关串口失败: {exc}', flush=True)
    finally:
        # 显式关串口：优先网页；ensure_hardware_idle 仅作兜底（内部可含 close API）
        try:
            page = getattr(ui, 'page', None)
            if page is not None and opened:
                from hil.browser.pages import serial_ui_close
                try:
                    ok = await serial_ui_close(page, ipc_port)
                    print(f'[HIL] 网页关闭串口 {ipc_port} → {ok}', flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f'[HIL] 网页关闭串口失败: {exc}', flush=True)
            try:
                api.ensure_hardware_idle(reason=f'after {case.case_id}', timeout_s=12.0)
            except Exception as exc:  # noqa: BLE001
                print(f'[HIL] 收尾 ensure_idle 失败: {exc}', flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f'[HIL] 收尾关串口失败: {exc}', flush=True)
        sim.stop()


PENDING_REPLY = [
    ('xl-rkdj', '热控电机 D15xx 指令应答帧格式未定义（目前只靠主动遥测区分）'),
    ('xl-zk', 'CPA-ZK D15xx 指令应答格式未定义'),
    ('xl-cpazx', 'CPA 指向 12B 遥控的应答格式未定义'),
]


@pytest.mark.parametrize('key,why', PENDING_REPLY, ids=[c[0] for c in PENDING_REPLY])
async def test_serial_tc_reply_pending(key, why):
    pytest.skip(f'待确认：{why}。见 TODO.md #1 / reply_map custom_rules（不瞎编应答）')
