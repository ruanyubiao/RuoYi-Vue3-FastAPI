import os
from urllib.parse import urlparse


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == '':
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, '').strip()
    try:
        return int(value) if value else default
    except ValueError:
        return default


class Config:
    """E2E 打本机 test-* 容器 + PC 后端（python app.py --env=test）。

    所有项均可用环境变量覆盖（便于换端口 / 账号 / 有头调试），默认值即 run_test.bat 拉起的 test 栈。
    """

    frontend_url = os.getenv('E2E_FRONTEND_URL', 'http://localhost:18080').rstrip('/')
    backend_url = os.getenv('E2E_BACKEND_URL', 'http://localhost:19099').rstrip('/')
    app_title = os.getenv('E2E_APP_TITLE', '激光终端地检系统')
    root_dept_name = os.getenv('E2E_ROOT_DEPT_NAME', '成都总公司')

    username = os.getenv('E2E_USERNAME', 'admin')
    password = os.getenv('E2E_PASSWORD', 'admin123')

    # E2E_HEADED=1 打开浏览器窗口；E2E_SLOW_MO=200 每步放慢毫秒数，便于肉眼观察
    headless = not _env_bool('E2E_HEADED', False)
    slow_mo = _env_int('E2E_SLOW_MO', 0)
    # 页面级默认超时（毫秒）
    timeout_ms = _env_int('E2E_TIMEOUT_MS', 10000)

    # Admin-Token cookie 的域名跟随前端地址，避免换成 127.0.0.1 / 机器名后 cookie 不生效
    cookie_domain = urlparse(frontend_url).hostname or 'localhost'
