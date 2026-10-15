import time

import requests

from common.config import Config

_HTTP_OK = 200


class LoginHelper:
    """
    登录辅助类（测试环境已关验证码，直接用账号密码换 token）
    """

    def __init__(self, base_url: str = Config.frontend_url) -> None:
        self.base_url = base_url
        self.session = requests.Session()

    def login(
        self,
        username: str | None = None,
        password: str | None = None,
        max_retries: int = 3,
    ) -> str | None:
        """
        执行登录，返回 token；失败返回 None。账号密码默认取 Config（可用 E2E_USERNAME / E2E_PASSWORD 覆盖）。
        网络异常 / 非 200 会退避重试；业务层明确拒绝（密码错等）不再重试。
        """
        login_data = {
            'username': username if username is not None else Config.username,
            'password': password if password is not None else Config.password,
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Referer': f'{self.base_url}/login'}

        for attempt in range(1, max_retries + 1):
            try:
                response = self.session.post(
                    f'{Config.backend_url}/login',
                    data=login_data,
                    headers=headers,
                    timeout=20,
                )
            except requests.RequestException as exc:
                print(f'登录请求异常（第 {attempt} 次）: {exc}')
                time.sleep(min(2 * attempt, 5))
                continue

            if response.status_code != _HTTP_OK:
                print(f'登录请求失败（第 {attempt} 次）: 状态码 {response.status_code}')
                time.sleep(min(2 * attempt, 5))
                continue

            try:
                result = response.json()
            except ValueError:
                print(f'登录响应不是 JSON: {response.text[:200]}')
                return None

            if result.get('code') == _HTTP_OK or result.get('success'):
                token = result.get('token') or (result.get('data') or {}).get('token')
                if token:
                    return token
                print(f'登录失败: 响应中未找到token - {result}')
                return None
            print(f'登录失败: {result.get("msg", "未知错误")}')
            return None

        print('登录失败，已达到最大重试次数')
        return None


# 使用示例
if __name__ == '__main__':
    token = LoginHelper().login()
    print(f'获取到token: {token}' if token else '登录失败')
