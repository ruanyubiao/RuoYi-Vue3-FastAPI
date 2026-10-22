# -*- coding: utf-8 -*-
"""调试·数据模拟：页面冒烟 + /payload/telemetry/dev/* 接口。

覆盖：debug/simulate 页关键控件、填充/发送，以及 can-yc / sample / samples / pipeline。
覆盖调试→数据模拟页及其 /payload/telemetry/dev/*。
"""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.ui_only]


def _good_hex(api) -> str:
    """从 DUT 黄金样例取可用 HEX（前端内嵌 SAMPLE_HEX 可能与当前校验不一致）。"""
    data = api.telemetry_dev_sample(assembler_id='passthrough', parser_id='tm_can_biu')
    hx = (data or {}).get('hex') if isinstance(data, dict) else None
    assert hx and len(str(hx).strip()) > 20, f'sample 无 hex: {data!r}'
    return str(hx)


@pytest.mark.asyncio(loop_scope='session')
async def test_simulate_page_fill_sample(ui):
    """数据模拟页：点击「填入样例」后 HEX 文本框有内容。"""
    page = await ui.goto('/debug/simulate')
    await page.get_by_text('BIU-CAN遥测复合帧数据模拟').first.wait_for(state='visible', timeout=15000)
    await page.get_by_role('button', name='填入样例').click()
    area = page.locator('textarea.hex-textarea').nth(1)
    await area.wait_for(state='visible', timeout=10000)
    val = await area.input_value()
    assert val and len(val.strip()) > 20, f'填入样例后 HEX 为空: {val!r}'
    assert not ui.page_errors, ui.page_errors[:3]


@pytest.mark.asyncio(loop_scope='session')
async def test_simulate_page_pipeline_sample_and_send(ui):
    """数据模拟页：点通用模拟示例外链填充后发送，命中 /dev/pipeline。"""
    page = await ui.goto('/debug/simulate')
    card = page.locator('.block-card').filter(has_text='通用数据发送模拟')
    await card.get_by_text('示例数据').first.wait_for(state='visible', timeout=15000)
    # 等 samples 接口拉完按钮
    sample_btn = card.locator('button.sample-btn').first
    await sample_btn.wait_for(state='visible', timeout=15000)
    await sample_btn.click()
    area = card.locator('textarea.hex-textarea').first
    val = await area.input_value()
    assert val and len(val.strip()) > 20, f'示例填充后 HEX 为空: {val!r}'
    async with page.expect_response(
        lambda r: '/payload/telemetry/dev/pipeline' in r.url and r.request.method == 'POST',
        timeout=20000,
    ) as resp_info:
        await card.get_by_role('button', name='发送').click()
    resp = await resp_info.value
    assert resp.ok, f'pipeline HTTP {resp.status}'
    body = await resp.json()
    assert body.get('code') in (200, None), body
    await card.locator('.result-alert').wait_for(state='visible', timeout=10000)
    assert not ui.page_errors, ui.page_errors[:3]


@pytest.mark.asyncio(loop_scope='session')
async def test_simulate_page_send_can_yc(ui, api):
    """数据模拟页：用黄金样例 HEX 填入 BIU 卡片后发送，命中 /dev/can-yc。"""
    hx = _good_hex(api)
    page = await ui.goto('/debug/simulate')
    card = page.locator('.block-card').filter(has_text='BIU-CAN遥测复合帧数据模拟')
    area = card.locator('textarea.hex-textarea').first
    await area.fill(hx)
    async with page.expect_response(
        lambda r: '/payload/telemetry/dev/can-yc' in r.url and r.request.method == 'POST',
        timeout=20000,
    ) as resp_info:
        await card.get_by_role('button', name='发送').click()
    resp = await resp_info.value
    assert resp.ok, f'can-yc HTTP {resp.status}'
    body = await resp.json()
    assert body.get('code') in (200, None), body
    await card.locator('.result-alert').wait_for(state='visible', timeout=10000)
    assert not ui.page_errors, ui.page_errors[:3]


def test_dev_api_samples(api):
    """GET /payload/telemetry/dev/samples：按组装器+解析器返回 items 列表。"""
    data = api.telemetry_dev_samples('passthrough', 'tm_can_biu')
    assert isinstance(data, dict), data
    items = data.get('items')
    assert isinstance(items, list) and len(items) >= 1, data


def test_dev_api_sample(api):
    """GET /payload/telemetry/dev/sample：返回可用 hex。"""
    data = api.telemetry_dev_sample(assembler_id='passthrough', parser_id='tm_can_biu')
    assert isinstance(data, dict) and data.get('hex'), data


def test_dev_api_pipeline(api):
    """POST /payload/telemetry/dev/pipeline：透传+BIU 解析注入成功。"""
    data = api.telemetry_dev_pipeline(_good_hex(api), 'passthrough', 'tm_can_biu')
    assert isinstance(data, dict), data
    assert (
        data.get('dataType') is not None
        or data.get('parsedCount') is not None
        or data.get('fieldCount') is not None
        or data.get('assemblerId') == 'passthrough'
    ), data


def test_dev_api_can_yc(api):
    """POST /payload/telemetry/dev/can-yc：注入 CAN 遥测复合帧成功。"""
    data = api.telemetry_dev_can_yc(_good_hex(api))
    assert isinstance(data, dict), data
    assert data.get('dataType') is not None or data.get('fieldCount') is not None, data



@pytest.mark.asyncio(loop_scope="session")
async def test_simulate_click_start_stop_and_clear(ui):
    """能点的都点：开始模拟→停止模拟、清空、示例按钮。"""
    page = await ui.goto("/debug/simulate")
    card = page.locator(".block-card").filter(has_text="BIU-CAN遥测复合帧数据模拟")
    await card.get_by_role("button", name="填入样例").click()
    await card.get_by_role("button", name="开始模拟").click()
    await page.wait_for_timeout(600)
    stop = card.get_by_role("button", name="停止模拟")
    if await stop.count():
        await stop.click()
    await card.get_by_role("button", name="清空").click()
    # 通用卡片：点一个示例 + 清空
    pipe = page.locator(".block-card").filter(has_text="通用数据发送模拟")
    sample = pipe.locator("button.sample-btn").first
    if await sample.count():
        await sample.click()
    await pipe.get_by_role("button", name="清空").click()
    assert not ui.page_errors, ui.page_errors[:3]
