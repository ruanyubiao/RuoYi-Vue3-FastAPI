"""地检业务页冒烟：登录后逐页打开菜单路由，不打开串口 / CAN / 硬件。"""

import pytest
from playwright.async_api import async_playwright

from common.base_page_test import BasePageTest
from common.config import Config

# (路由, 页内特征选择器)。选择器尽量落在主内容区，避免只命中侧栏菜单。
PAYLOAD_PAGES: list[tuple[str, str]] = [
    ('/index', '.device-service-page'),
    ('/biu/telecontrol/control', '.control-page'),
    ('/biu/telecontrol/command', '.command-page'),
    ('/biu/telecontrol/sequence', 'input[placeholder="请输入序列名称"]'),
    ('/xl/telecontrol/control', '.control-page'),
    ('/xl/telecontrol/command', '.command-page'),
    ('/xl/telecontrol/sequence', 'input[placeholder="请输入序列名称"]'),
    ('/yj216/telecontrol/control', '.control-page'),
    ('/yj216/telecontrol/command', '.command-page'),
    ('/yj216/telecontrol/sequence', 'input[placeholder="请输入序列名称"]'),
    ('/telemetry/live', '.tm-page'),
    ('/telemetry/curve', '.curve-page'),
    ('/telemetry/archive', '.curve-page'),
    ('/xl/board/camera', '.camera-page'),
    ('/xl/board/rkdj', '.board-page'),
    ('/xl/board/zk', '.board-page'),
    ('/xl/refactor', 'text=暂为空白页'),
    ('/debug/simulate', 'text=通用数据发送模拟'),
    ('/debug/xfer', '.xfer-page'),
    ('/debug/configFile', 'text=重新载入配置'),
    ('/debug/tmCalc', '.tm-calc-page'),
    ('/debug/checksum', '.checksum-page'),
]


class PayloadPagesTest(BasePageTest):
    """地检菜单页加载。"""

    async def _open(self, path: str) -> None:
        url = Config.frontend_url + path
        await self.page.goto(url, wait_until='domcontentloaded', timeout=30000)
        assert path in self.page.url, f'期望打开 {path}，实际 {self.page.url}'

    async def test_payload_pages_load(self) -> None:
        """每个地检菜单页都能打开并露出特征 UI。"""
        failures: list[str] = []
        for path, selector in PAYLOAD_PAGES:
            try:
                await self._open(path)
                await self.page.wait_for_selector(selector, timeout=20000)
            except Exception as exc:
                failures.append(f'{path} ({selector}): {exc}')
        assert not failures, '地检页冒烟失败:\n' + '\n'.join(failures)

        await self._open('/biu/telecontrol/control')
        await self.page.get_by_text('目标地址').first.wait_for(timeout=10000)
        await self.page.get_by_role('button', name='新建CAN连接-A').wait_for(timeout=10000)

        await self._open('/xl/telecontrol/control')
        await self.page.get_by_text('时间同步 GNSS 有效').wait_for(timeout=10000)

        await self._open('/xl/board/camera')
        await self.page.get_by_role('button', name='新建控制串口连接').wait_for(timeout=10000)

        await self._open('/telemetry/archive')
        await self.page.get_by_text('再选择时间区间查询').wait_for(timeout=10000)

        await self._open('/index')
        await self.page.get_by_role('button', name='新建 CAN 连接').wait_for(timeout=10000)

    async def test_sequence_add_opens_editor(self) -> None:
        """指令序列「新增」进入编辑页（不保存、不下发）。"""
        await self._open('/biu/telecontrol/sequence')
        await self.page.get_by_role('button', name='新增').first.click()
        await self.page.wait_for_url('**/payload/sequence-edit/index**', timeout=15000)
        await self.page.wait_for_selector('.seq-edit-page', timeout=15000)
        await self.page.get_by_placeholder('请输入序列名称').wait_for(timeout=10000)


@pytest.mark.asyncio
async def test_payload_pages_load() -> None:
    """地检菜单页冒烟。"""
    async with async_playwright() as playwright:
        test_instance = PayloadPagesTest()
        await test_instance.setup(playwright)
        try:
            await test_instance.test_payload_pages_load()
        finally:
            await test_instance.teardown()


@pytest.mark.asyncio
async def test_sequence_add_opens_editor() -> None:
    """指令序列新增进入编辑页。"""
    async with async_playwright() as playwright:
        test_instance = PayloadPagesTest()
        await test_instance.setup(playwright)
        try:
            await test_instance.test_sequence_add_opens_editor()
        finally:
            await test_instance.teardown()
