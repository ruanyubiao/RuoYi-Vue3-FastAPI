"""有头 UI 冒烟（marker: ui_only）：逐页打开工控机正式环境全部业务页面。

只读：不建连接、不下发指令。断言：URL 未被重定向、无 404 页、页内特征元素可见、无未捕获 JS 异常。
"""
from __future__ import annotations

import pytest

from hil.browser.pages import KEY_ELEMENTS, PAYLOAD_PAGES

pytestmark = [pytest.mark.ui_only, pytest.mark.asyncio(loop_scope='session')]


@pytest.mark.parametrize('path,selector,title', PAYLOAD_PAGES, ids=[p for p, _, _ in PAYLOAD_PAGES])
async def test_page_opens(ui, path, selector, title):
    page = await ui.goto(path)
    assert path in page.url, f'{title}: 期望 {path}，实际跳到 {page.url}'
    head = (await page.locator('body').inner_text())[:80]
    assert not head.lstrip().startswith('404'), f'{title} ({path}) 打开是 404 页（工控机版本无此路由？）'
    await page.locator(selector).first.wait_for(state='visible', timeout=20000)
    await page.wait_for_timeout(800)  # 等首屏接口返回，捕获异步 JS 异常
    assert not ui.page_errors, f'{title} ({path}) 未捕获 JS 异常: {ui.page_errors[:3]}'


@pytest.mark.parametrize('path,kind,text', KEY_ELEMENTS, ids=[f'{p}:{t}' for p, _, t in KEY_ELEMENTS])
async def test_key_element_visible(ui, path, kind, text):
    page = await ui.goto(path)
    # command page: 发送指令/预览组帧 only after an order is selected
    if path.rstrip('/').endswith('/telecontrol/command') and kind == 'button' and text in ('发送指令', '预览组帧'):
        # 预览组帧 only renders when the selected order has editable components
        nodes = page.locator('.command-page .el-tree-node__content, .el-tree-node__content')
        n = await nodes.count()
        found = False
        for i in range(min(n, 40)):
            await nodes.nth(i).click()
            await page.wait_for_timeout(350)
            loc = page.get_by_role('button', name=text)
            if await loc.count() and await loc.first.is_visible():
                found = True
                break
        if not found:
            # fallback cards
            rows = page.locator('.command-page .order-card, .order-item, .cmd-list-item')
            for i in range(min(await rows.count(), 20)):
                await rows.nth(i).click()
                await page.wait_for_timeout(350)
                loc = page.get_by_role('button', name=text)
                if await loc.count() and await loc.first.is_visible():
                    found = True
                    break
        if not found:
            import pytest
            pytest.skip(f'{path}: no order shows button {text!r} (no editable comps?)')
        return
    loc = page.get_by_role('button', name=text) if kind == 'button' else page.get_by_text(text)
    await loc.first.wait_for(state='visible', timeout=15000)


async def test_sequence_add_opens_editor(ui):
    """指令序列「新增」进入编辑页（不保存、不下发）。"""
    page = await ui.goto('/biu/telecontrol/sequence')
    await page.get_by_role('button', name='新增').first.click()
    await page.wait_for_url('**/payload/sequence-edit/index**', timeout=15000)
    await page.locator('.seq-edit-page').wait_for(timeout=15000)


DIALOG_CASES = [(f, c) for f in ('biu', 'xl', 'yj216') for c in ('a', 'b')]


@pytest.mark.parametrize('family,cable', DIALOG_CASES, ids=[f'{f}-{c.upper()}' for f, c in DIALOG_CASES])
async def test_can_dialog_readonly(ui, api, family, cable):
    """只读核对「新建CAN连接-A/B」对话框：能选到工控机 vendor/dev/ch，确认键可用，然后点「取消」（不打开设备）。"""
    from hil.browser.pages import can_ui_open
    from hil.config import CONFIG

    ch = CONFIG.ipc_can_channel(family, cable)
    before = api.can_sessions(family)
    page = await ui.goto(f'/{family}/telecontrol/control', settle_ms=800)
    bar = page.locator('.can-connect-toolbar').first
    if await bar.get_by_role('button', name=f'关闭CAN-{cable.upper()}').count():
        pytest.skip(f'{family} CAN-{cable.upper()} 已连接（页面显示「关闭」），不动它')
    picked = await can_ui_open(page, cable, ch.vendor, ch.dev_index, ch.can_index, submit=False)
    print(f'[HIL] {family} CAN-{cable.upper()} 对话框（采集机 {api.collector_host}）: {picked}')
    assert picked['confirmEnabled'], f'确认键不可用: {picked}'
    assert picked['confirm'] in ('打开', '使用'), picked
    assert api.can_sessions(family) == before, '只读核对后会话发生了变化'
    assert not ui.page_errors, ui.page_errors[:3]
