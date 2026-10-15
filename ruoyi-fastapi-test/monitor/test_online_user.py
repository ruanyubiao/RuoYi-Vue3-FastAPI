import pytest
from playwright.async_api import async_playwright

from common.base_page_test import BasePageTest
from common.config import Config


class OnlineUserTest(BasePageTest):
    """在线用户测试类"""

    async def test_online_user_operations(self) -> None:
        """测试在线用户强退"""
        # 1. 模拟 niangao 用户登录以产生在线会话
        # 使用一个新的上下文来模拟另一个用户的登录
        niangao_context = await self.browser.new_context()
        niangao_page = await niangao_context.new_page()

        # 登录 niangao
        try:
            await niangao_page.goto(Config.frontend_url + '/login')
            await niangao_page.locator('div.el-form-item', has_text='账号').locator('input').fill('niangao')
            await niangao_page.locator('div.el-form-item', has_text='密码').locator('input').fill('admin123')
            await niangao_page.get_by_role('button', name='登 录').click()
            # 等待登录成功
            await niangao_page.wait_for_url('**/index')
        except Exception as e:
            print(f'Niangao login failed: {e}. Trying 123456')
            try:
                await niangao_page.locator('div.el-form-item', has_text='密码').locator('input').fill('123456')
                await niangao_page.get_by_role('button', name='登 录').click()
                await niangao_page.wait_for_url('**/index')
            except Exception as e2:
                print(f'Niangao login failed again: {e2}')

        # 2. 切换回 admin (self.page) 进行操作
        await self.page.goto(Config.frontend_url + '/monitor/online')
        await self.page.wait_for_load_state('networkidle')

        # 3. 搜索 niangao 用户
        await self.page.locator('div.el-form-item', has_text='用户名称').locator('input').fill('niangao')
        await self.page.get_by_role('button', name='搜索').click()
        await self.wait_for_list_refresh()

        # 4. 强退操作：niangao 刚登录，列表里必须有它，否则说明会话没建立或搜索失效
        rows = self.page.locator('.el-table__body tr', has_text='niangao')
        assert await rows.count() > 0, '在线用户列表应能搜到刚登录的 niangao'
        await rows.first.get_by_role('button', name='强退').click()
        await self.page.get_by_role('button', name='确定').click()
        await self.page.wait_for_selector('text=删除成功', timeout=5000)

        # 再次搜索确认会话已被踢掉
        await self.page.get_by_role('button', name='搜索').click()
        await self.wait_for_list_refresh()
        assert await rows.count() == 0, '强退后在线列表不应再有 niangao'

        # 关闭 niangao 的上下文
        await niangao_context.close()


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
