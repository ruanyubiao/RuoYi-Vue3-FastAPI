import pytest
from playwright.async_api import async_playwright

from common.base_page_test import BasePageTest
from common.config import Config


async def _open_and_expect(path: str, text: str) -> None:
    async with async_playwright() as p:
        test_instance = BasePageTest()
        await test_instance.setup(p)
        try:
            await test_instance.goto_page(Config.frontend_url + path)
            assert '/login' not in test_instance.page.url, f'{path} 被重定向到登录页'
            await test_instance.wait_for_page_title(text)
        finally:
            await test_instance.teardown()


@pytest.mark.asyncio
async def test_dashboard_page() -> None:
    """测试仪表盘页面"""
    await _open_and_expect('/index', '首页')


@pytest.mark.asyncio
@pytest.mark.skip(reason='this product SQL has no Druid / 数据监控 menu')
async def test_druid_page() -> None:
    """If Druid is added back, assert the page title 数据监控."""
    return


@pytest.mark.asyncio
async def test_build_page() -> None:
    """测试表单构建页面"""
    await _open_and_expect('/tool/build', 'Form Generator')
