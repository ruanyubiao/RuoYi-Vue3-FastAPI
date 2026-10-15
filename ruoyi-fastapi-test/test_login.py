from http import HTTPStatus

import pytest
import requests
from playwright.async_api import async_playwright

from common.base_page_test import admin_token_cookie, launch_browser
from common.config import Config
from common.login_helper import LoginHelper


@pytest.mark.asyncio
async def test_login_page_loads() -> None:
    """测试登录页面是否能正常加载"""
    async with async_playwright() as p:
        browser = await launch_browser(p)
        try:
            page = await browser.new_page()
            await page.goto(Config.frontend_url + '/login')
            # 等表单真正渲染出来再断言，避免 SPA 尚未挂载时 query_selector 返回 None
            await page.locator('input[placeholder="账号"]').wait_for(timeout=10000)
            await page.locator('input[placeholder="密码"]').wait_for(timeout=10000)
            assert Config.app_title in await page.title()
        finally:
            await browser.close()


def test_captcha_disabled_in_test_env() -> None:
    """测试栈依赖验证码已关闭（disable_captcha.sql），否则后续所有登录都会失败"""
    response = requests.get(f'{Config.backend_url}/captchaImage', timeout=20)
    assert response.status_code == HTTPStatus.OK, f'captchaImage HTTP={response.status_code}'
    body = response.json()
    assert body.get('code') == HTTPStatus.OK, body
    enabled = body.get('captchaEnabled', (body.get('data') or {}).get('captchaEnabled'))
    assert enabled is False, f'测试环境验证码应关闭，实际 captchaEnabled={enabled!r}'


def test_login_without_captcha() -> None:
    """测试在禁用验证码的情况下登录流程"""
    helper = LoginHelper()

    # 尝试登录（测试环境中验证码已禁用）
    token = helper.login()

    # 验证登录结果
    assert token is not None, '登录应该成功'
    assert len(token) > 0, '应该返回有效的token'


@pytest.mark.asyncio
async def test_login_flow_with_playwright() -> None:
    """使用Playwright测试完整的登录流程（测试环境中验证码已禁用）"""
    async with async_playwright() as p:
        browser = await launch_browser(p)
        try:
            page = await browser.new_page()
            await page.goto(Config.frontend_url + '/login')
            await page.wait_for_selector('input[placeholder="账号"]')

            await page.fill('input[placeholder="账号"]', Config.username)
            await page.fill('input[placeholder="密码"]', Config.password)
            # 若依登录按钮文案是「登 录」（中间有空格），按主按钮定位更稳
            await page.locator('button.el-button--primary').first.click()

            try:
                await page.wait_for_url('**/index**', timeout=10000)
            except Exception as exc:
                message = page.locator('.el-message')
                detail = await message.first.text_content() if await message.count() else ''
                raise AssertionError(f'登录应该成功，未跳转到首页: {detail or exc}') from exc
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_protected_routes_require_auth() -> None:
    """测试受保护的路由需要认证：未登录访问应被重定向到登录页"""
    async with async_playwright() as p:
        browser = await launch_browser(p)
        try:
            page = await browser.new_page()
            await page.goto(Config.frontend_url + '/system/user')
            # 路由守卫是异步跳转，显式等待登录页而不是立即读 URL
            try:
                await page.wait_for_url('**/login**', timeout=10000)
            except Exception as exc:
                raise AssertionError(f'未登录访问受保护页面没有重定向到登录页，当前URL: {page.url}') from exc
            await page.wait_for_selector('input[placeholder="账号"]')
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_authenticated_access() -> None:
    """测试认证后的访问"""
    # 首先通过API登录获取token
    helper = LoginHelper()
    token = helper.login()

    assert token is not None, '登录应该成功'

    # 使用Playwright测试带认证的访问
    async with async_playwright() as p:
        browser = await launch_browser(p)
        context = await browser.new_context(
            storage_state={'cookies': [admin_token_cookie(token)], 'origins': []},
        )
        page = await context.new_page()

        # 访问受保护的页面
        await page.goto(Config.frontend_url + '/system/user')

        # 检查是否能够访问受保护的页面（而不是被重定向到登录页）
        current_url = page.url
        assert '/login' not in current_url, '已登录用户应该能够访问受保护页面'

        # 用户列表表格出现才算真正进入了页面
        await page.locator('.el-table').first.wait_for(timeout=10000)
        await page.get_by_text('用户名称').first.wait_for(timeout=10000)

        await context.close()
        await browser.close()
