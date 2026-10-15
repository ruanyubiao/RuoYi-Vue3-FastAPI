"""全局前置：测试栈没起来时直接给出明确提示，而不是几十个用例各自超时。"""

import os

import pytest
import requests

from common.config import Config


@pytest.fixture(scope='session', autouse=True)
def _require_test_stack() -> None:
    if os.getenv('E2E_SKIP_PREFLIGHT') == '1':
        return
    for name, url in (('后端', f'{Config.backend_url}/health'), ('前端', f'{Config.frontend_url}/login')):
        try:
            requests.get(url, timeout=5)
        except requests.RequestException as exc:  # noqa: PERF203
            pytest.exit(
                f'{name}不可达: {url} ({exc.__class__.__name__})。请先用 run_test.bat 拉起 test 栈，'
                '或用 E2E_BACKEND_URL / E2E_FRONTEND_URL 指向已运行的环境。',
                returncode=3,
            )
