import pytest
from playwright.async_api import async_playwright

from common.base_page_test import BasePageTest
from common.config import Config


class ServerMonitorTest(BasePageTest):
    """服务监控测试类"""

    async def test_server_monitor(self) -> None:
        """测试服务监控页面"""
        await self.page.goto(Config.frontend_url + '/monitor/server')
        await self.page.wait_for_load_state('networkidle')

        # 验证主要板块存在
        await self.page.wait_for_selector('text=CPU')
        await self.page.wait_for_selector('text=内存')
        await self.page.wait_for_selector('text=服务器信息')
        await self.page.wait_for_selector('text=Python解释器信息')
        await self.page.wait_for_selector('text=磁盘状态')

        # PC 后端路径含 ruoyi-fastapi-backend；若依 Docker 镜像则是 /app
        project_path_row = self.page.locator('tr', has_text='项目路径')
        await project_path_row.wait_for(timeout=5000)
        text = await project_path_row.text_content() or ''
        assert 'ruoyi-fastapi-backend' in text or '/app' in text, f'unexpected project path: {text}'


@pytest.mark.asyncio
async def test_server_monitor_page() -> None:
    """测试服务监控页面功能"""
    async with async_playwright() as p:
        test_instance = ServerMonitorTest()
        await test_instance.setup(p)
        try:
            await test_instance.test_server_monitor()
        finally:
            await test_instance.teardown()
