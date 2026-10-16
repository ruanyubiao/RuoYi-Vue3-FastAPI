import re
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright

from common.config import Config
from common.login_helper import LoginHelper


def admin_token_cookie(token: str) -> dict[str, Any]:
    """前端读取的 Admin-Token cookie（域名跟随 Config.frontend_url）。"""
    return {
        'name': 'Admin-Token',
        'value': token,
        'domain': Config.cookie_domain,
        'path': '/',
        'httpOnly': False,
        'secure': False,
        'sameSite': 'Lax',
    }


async def launch_browser(playwright: Playwright) -> Browser:
    """统一的浏览器启动参数（E2E_HEADED / E2E_SLOW_MO 可调）。"""
    return await playwright.chromium.launch(headless=Config.headless, slow_mo=Config.slow_mo)


class BasePageTest:
    browser: Browser | None = None
    context: BrowserContext | None = None
    page: Page | None = None
    token: str | None = None

    async def setup(self, playwright: Playwright) -> None:
        """初始化浏览器和登录"""
        self.token = LoginHelper().login()
        assert self.token is not None, '登录应该成功'

        self.browser = await launch_browser(playwright)
        self.context = await self.browser.new_context()
        self.context.set_default_timeout(Config.timeout_ms)
        await self.context.add_cookies([admin_token_cookie(self.token)])
        self.page = await self.context.new_page()

    async def teardown(self) -> None:
        """清理资源"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()

    async def goto_page(self, url: str) -> None:
        """导航到指定页面"""
        await self.page.goto(url)

    async def wait_for_page_title(self, title_text: str, timeout: int = 10000) -> None:
        """等待页面出现指定文本"""
        locator = self.page.get_by_text(title_text).first
        await locator.wait_for(timeout=timeout)
        assert title_text in (await locator.inner_text())

    async def wait_for_list_refresh(self, timeout: int = 10000) -> None:
        """等待列表/请求刷新完成，替代固定 sleep。

        先等网络空闲，再等 Element Plus 的 loading 遮罩消失；网络长连接（轮询/WS）导致
        networkidle 不触发时不报错，只依赖遮罩判断。
        """
        try:
            await self.page.wait_for_load_state('networkidle', timeout=timeout)
        except Exception:
            pass
        mask = self.page.locator('.el-loading-mask:visible')
        try:
            await mask.first.wait_for(state='hidden', timeout=timeout)
        except Exception:
            pass

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> None:
        """等待选择器出现"""
        await self.page.wait_for_selector(selector, timeout=timeout)

    async def query_selector(self, selector: str) -> Any:
        """查询选择器元素"""
        return await self.page.query_selector(selector)

    async def click_button(self, button_text: str) -> None:
        """点击按钮"""
        button = await self.page.wait_for_selector(f'text="{button_text}"', timeout=5000)
        await button.click()

    async def fill_input(self, selector: str, value: str) -> None:
        """填写输入框"""
        await self.page.fill(selector, value)

    async def get_text_content(self, selector: str) -> str | None:
        """获取元素文本内容"""
        element = await self.page.query_selector(selector)
        if element:
            return await element.text_content()
        return None

    async def get_table_total_rows(self) -> int:
        """获取分页组件上的总条数（先等列表刷新完成）"""
        await self.wait_for_list_refresh()
        element = self.page.locator('span.el-pagination__total').first
        await element.wait_for(state='attached', timeout=10000)
        text = await element.text_content() or ''
        match = re.search(r'\d+', text)
        assert match, f'分页总数文本无数字: {text!r}'
        return int(match.group())
