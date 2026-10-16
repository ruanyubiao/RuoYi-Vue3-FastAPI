import pytest
from playwright.async_api import async_playwright

from common.base_page_test import BasePageTest, admin_token_cookie
from common.config import Config
from common.login_helper import LoginHelper


class OnlineUserTest(BasePageTest):
    """在线用户测试类"""

    async def test_online_user_operations(self) -> None:
        """测试在线用户强退。库里的第二个账号是 test，不是 niangao。"""
        other_name = 'test'
        token = LoginHelper().login(other_name, Config.password)
        assert token, f'{other_name} 登录应该成功'

        other_context = await self.browser.new_context()
        await other_context.add_cookies([admin_token_cookie(token)])
        other_page = await other_context.new_page()
        await other_page.goto(Config.frontend_url + '/index')

        await self.page.goto(Config.frontend_url + '/monitor/online')
        await self.page.wait_for_load_state('networkidle')

        await self.page.locator('div.el-form-item', has_text='用户名称').locator('input').fill(other_name)
        await self.page.get_by_role('button', name='搜索').click()
        await self.wait_for_list_refresh()

        rows = self.page.locator('.el-table__body tr', has_text=other_name)
        assert await rows.count() > 0, f'在线用户列表应能搜到刚登录的 {other_name}'
        await rows.first.get_by_role('button', name='强退').click()
        await self.page.get_by_role('dialog').get_by_role('button', name='确定').click()
        await self.page.wait_for_selector('text=删除成功', timeout=5000)

        await self.page.get_by_role('button', name='搜索').click()
        await self.wait_for_list_refresh()
        assert await rows.count() == 0, f'强退后在线列表不应再有 {other_name}'

        await other_context.close()


@pytest.mark.asyncio
async def test_online_user_page() -> None:
    """测试在线用户页面功能"""
    async with async_playwright() as p:
        test_instance = OnlineUserTest()
        await test_instance.setup(p)
        try:
            await test_instance.test_online_user_operations()
        finally:
            await test_instance.teardown()
