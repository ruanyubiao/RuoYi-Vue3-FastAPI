"""有头 Playwright 会话：登录（表单优先，失败则 API token 写 Admin-Token cookie）、跳转、JS 异常收集、截图。"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from hil.config import CONFIG, HILConfig


class FrontendUnreachable(RuntimeError):
    pass


def check_reachable(url: str, timeout: float = 5.0) -> None:
    import socket

    u = urlparse(url)
    try:
        socket.create_connection((u.hostname, u.port or 80), timeout=timeout).close()
    except OSError as exc:
        raise FrontendUnreachable(f'无法连接正式环境 {url}: {exc}（检查网线/IP/工控机服务是否启动）') from exc


class BrowserSession:
    def __init__(self, cfg: HILConfig = CONFIG) -> None:
        self.cfg = cfg
        self._pw = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.page_errors: list[str] = []
        self.collector_host = ''

    async def start(self) -> Page:
        check_reachable(self.cfg.frontend_url)
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(headless=not self.cfg.headed, slow_mo=self.cfg.slow_mo_ms)
        self.context = await self.browser.new_context(viewport={'width': 1600, 'height': 900})
        self.page = await self.context.new_page()
        self.page.on('pageerror', lambda err: self.page_errors.append(str(err)))
        return self.page

    async def login(self) -> None:
        page = self.page
        await page.goto(f'{self.cfg.frontend_url}/login', wait_until='domcontentloaded')
        try:
            await page.get_by_placeholder('账号').fill(self.cfg.username, timeout=10000)
            await page.get_by_placeholder('密码').fill(self.cfg.password)
            await page.get_by_role('button', name=re.compile('登\\s*录')).click()
            await page.wait_for_url(lambda u: '/login' not in u, timeout=20000)
            print('[HIL] 表单登录成功')
            await self.apply_collector()
            return
        except Exception as exc:  # noqa: BLE001
            print(f'[HIL] 表单登录失败，改用 API token: {exc}')
        from hil.ipc_api import IpcApi

        token = IpcApi(self.cfg).login()
        await self.context.add_cookies([{
            'name': 'Admin-Token', 'value': token,
            'domain': urlparse(self.cfg.frontend_url).hostname, 'path': '/',
        }])
        await page.goto(f'{self.cfg.frontend_url}/index', wait_until='domcontentloaded')
        await self.apply_collector()

    async def apply_collector(self) -> str:
        """与接口客户端选同一台采集机，写前端 localStorage「payload:collectorHost」（utils/collectorHost.js），
        之后页面所有请求都带 X-Collector-Host。"""
        from hil.ipc_api import IpcApi

        host = self.cfg.collector_info()[0]
        if not host:
            api = IpcApi(self.cfg)
            api.login()
            host = api.collector_host
        await self.page.evaluate('([k, v]) => localStorage.setItem(k, v)', ['payload:collectorHost', host])
        self.collector_host = host
        print(f'[HIL] 页面采集机 = {host}（{self.cfg.collector_info()[1]}）')
        return host

    async def set_local_json(self, key: str, value) -> None:
        """写 localStorage（前端 cache.local.setJSON 同格式），用于预选遥测表等页面偏好。"""
        await self.page.evaluate('([k, v]) => localStorage.setItem(k, v)', [key, json.dumps(value)])

    async def goto(self, path: str, settle_ms: int = 0) -> Page:
        self.page_errors.clear()
        await self.page.goto(f'{self.cfg.frontend_url}{path}', wait_until='domcontentloaded', timeout=30000)
        try:
            await self.page.wait_for_load_state('networkidle', timeout=8000)
        except Exception:  # noqa: BLE001  页面有轮询时 networkidle 不一定到
            pass
        if settle_ms:
            await self.page.wait_for_timeout(settle_ms)
        return self.page

    async def screenshot(self, tag: str) -> str | None:
        if not self.page:
            return None
        safe = re.sub(r'[^\w.-]+', '_', tag)[:120]
        p = self.cfg.artifacts_dir / f'{time.strftime("%H%M%S")}_{safe}.png'
        try:
            await self.page.screenshot(path=str(p), full_page=True)
        except Exception as exc:  # noqa: BLE001
            print(f'[HIL] 截图失败: {exc}')
            return None
        print(f'[HIL] 截图: {p}')
        return str(p)

    async def close(self) -> None:
        for obj in (self.context, self.browser):
            if obj:
                try:
                    await obj.close()
                except Exception:  # noqa: BLE001
                    pass
        if self._pw:
            await self._pw.stop()
