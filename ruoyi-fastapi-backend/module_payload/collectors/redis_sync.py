"""采集进程用同步 Redis 客户端。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import redis
from dotenv import load_dotenv

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_env = os.environ.get('APP_ENV', '')
load_dotenv(_BACKEND_ROOT / ('.env.dev' if _env == '' else f'.env.{_env}'))


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
