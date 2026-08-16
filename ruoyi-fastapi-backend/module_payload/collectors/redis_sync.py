"""采集进程用同步 Redis 客户端。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import redis
from dotenv import load_dotenv

from config.paths import get_package_root

_BACKEND_ROOT = get_package_root()
_env = os.environ.get('APP_ENV', '')
_env_name = '.env.dev' if _env == '' else f'.env.{_env}'
# 与 config/env.py 一致：cwd 可覆盖，再包根，再 config/（wheel 副本）
for _base in (Path.cwd(), _BACKEND_ROOT, _BACKEND_ROOT / 'config'):
    _env_file = _base / _env_name
    if _env_file.is_file():
        load_dotenv(_env_file)
        break
else:
    load_dotenv(_BACKEND_ROOT / _env_name)


def _redis_config() -> dict[str, Any]:
    return {
        'host': os.environ.get('REDIS_HOST', '127.0.0.1'),
        'port': int(os.environ.get('REDIS_PORT', '6379')),
        'username': os.environ.get('REDIS_USERNAME') or None,
        'password': os.environ.get('REDIS_PASSWORD') or None,
        'db': int(os.environ.get('REDIS_DATABASE', '2')),
        'decode_responses': True,
    }


def create_sync_redis() -> redis.Redis:
    return redis.Redis(**_redis_config())


def dumps_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def loads_json(text: str | None) -> Any:
    if not text:
        return None
    return json.loads(text)
