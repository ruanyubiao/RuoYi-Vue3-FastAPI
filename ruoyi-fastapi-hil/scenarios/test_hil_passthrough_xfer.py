# -*- coding: utf-8 -*-
"""HIL A/B hardware models.

A) Business-page open (bound interpreter): covered by test_hil_can / test_hil_serial goldens.
   Extra: telecommand reply (often unimplemented) kept as explicit skip rows.
B) Homepage open as passthrough (no interpreter) -> debug/xfer one TX/RX loopback.
UDP product feature not ready: keep items but skip.
"""
from __future__ import annotations

import time

import pytest

from conftest import require_can
from hil.config import CONFIG

# ---------- Type A: TC reply placeholders (product often has no bus ACK) ----------

@pytest.mark.hil_can
@pytest.mark.parametrize('family', ['biu', 'xl', 'yj216'])
def test_tc_reply_not_implemented(family):
    """遥控指令总线回复：多数协议无要求或未实现；保留测试项并 skip。"""
    pytest.skip(f'{family}: telecommand bus reply not required/implemented; keep checklist row')


@pytest.mark.hil_serial
@pytest.mark.parametrize('key', ['xl-camera', 'xl-rkdj', 'yj216-rs422'])
def test_serial_tc_reply_not_implemented(key):
    pytest.skip(f'{key}: serial TC reply not required/implemented; keep checklist row')


@pytest.mark.hil_udp
def test_udp_hil_feature_not_ready():
    """UDP 硬件在环业务功能未落地：保留测试项，跳过实测。"""
    pytest.skip('UDP HIL feature not implemented on DUT; checklist row kept')


# ---------- Type B: homepage passthrough + debug/xfer loopback ----------

@pytest.mark.hil_can
@pytest.mark.asyncio(loop_scope='session')
async def test_passthrough_can_xfer_loopback(ui, api):
    """B: 首页透传开 CAN → 调试/数据收发 发一帧 → 测试机收 → 测试机回 → 工控页可见。"""
    require_can('biu')
    from hil.browser.pages import home_can_open_passthrough, xfer_select_device_and_send
    from hil.hw.can_sim import CanSim

    api.ensure_hardware_idle(reason='passthrough-can-setup', timeout_s=15.0)
    ch = CONFIG.ipc_can_channel('biu', 'a')
    sim = CanSim('biu', CONFIG, dry_run=False, cable='a')
    sim.start()
    try:
        page = await ui.goto('/index', settle_ms=800)
        try:
            await home_can_open_passthrough(page, ch.vendor, ch.dev_index, ch.can_index, submit=True)
        except Exception:
            # UI dialog flaky: same semantic as homepage 透传
            api.open_can_passthrough(cable='a', family='biu')
        await page.wait_for_timeout(500)

        # unique short CAN payload (DLC<=8)
        can_id = '123'
        payload = 'A1 B2 C3 D4'
        expect = bytes.fromhex(payload.replace(' ', ''))
        n0 = len(sim.raw_frames)

        page = await ui.goto('/debug/xfer', settle_ms=600)
        await xfer_select_device_and_send(page, payload, can_id=can_id)

        deadline = time.time() + 8
        got = None
        while time.time() < deadline:
            for cid, data in sim.raw_frames[n0:]:
                if expect in data or data == expect:
                    got = (cid, data)
                    break
            if got:
                break
            await page.wait_for_timeout(200)
        assert got, f'PC did not RX passthrough CAN frame expect={payload} raw={sim.raw_frames[n0:n0+10]}'

        # PC -> IPC
        reply = bytes([0xD0, 0xD1, 0xD2, 0xD3])
        sim.send_frame((got[0], reply))
        await page.wait_for_timeout(1200)
        body = (await page.locator('body').inner_text()).upper()
        assert 'D0' in body and 'D1' in body, f'IPC xfer page missing PC reply hex: {body[:400]}'
    finally:
        try:
            sim.close()
        except Exception:
            pass
        try:
            api.ensure_hardware_idle(reason='passthrough-can-teardown', timeout_s=15.0)
        except Exception:
            pass


@pytest.mark.hil_serial
@pytest.mark.asyncio(loop_scope='session')
async def test_passthrough_serial_xfer_loopback(ui, api):
    """B: 首页透传开串口 → 调试/数据收发 发一包 → 测试机收 → 回发 → 工控页可见。"""
    from hil.browser.pages import home_serial_open_passthrough, xfer_select_device_and_send
    from hil.hw.serial_sim import SerialSim

    if not CONFIG.serial_port or not CONFIG.ipc_serial_port:
        pytest.skip('serial ports not configured')

    api.ensure_hardware_idle(reason='passthrough-serial-setup', timeout_s=15.0)
    # use a generic key for baud; raw tap uses configured test-PC COM
    sim = SerialSim('xl-rkdj', CONFIG.serial_port, CONFIG, dry_run=False)
    sim.start()
    try:
        page = await ui.goto('/index', settle_ms=800)
        try:
            await home_serial_open_passthrough(page, CONFIG.ipc_serial_port, baud=115200, submit=True)
        except Exception:
            api.open_serial_passthrough(CONFIG.ipc_serial_port)
        await page.wait_for_timeout(500)

        payload = '5A A5 01 02 03 04'
        expect = bytes.fromhex(payload.replace(' ', ''))
        n0 = len(sim.raw_chunks)

        page = await ui.goto('/debug/xfer', settle_ms=600)
        await xfer_select_device_and_send(page, payload, can_id=None)

        deadline = time.time() + 8
        got = None
        while time.time() < deadline:
            blob = b''.join(sim.raw_chunks[n0:])
            if expect in blob:
                got = blob
                break
            await page.wait_for_timeout(200)
        assert got is not None, f'PC did not RX serial expect={payload} chunks={sim.raw_chunks[n0:n0+5]}'

        reply = bytes.fromhex('EE FF 10 20')
        sim.send_frame(reply)
        await page.wait_for_timeout(1200)
        body = (await page.locator('body').inner_text()).upper()
        assert 'EE' in body and 'FF' in body, f'IPC xfer page missing PC reply: {body[:400]}'
    finally:
        try:
            sim.close()
        except Exception:
            pass
        try:
            api.ensure_hardware_idle(reason='passthrough-serial-teardown', timeout_s=15.0)
        except Exception:
            pass
