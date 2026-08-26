"""采集进程用同步 Redis 客户端。"""

from __future__ import annotations

import json
import os
from typing import Any

import redis
from dotenv import load_dotenv

from config.paths import resolve_dotenv_path

load_dotenv(resolve_dotenv_path(os.environ.get('APP_ENV', '')))


def _redis_config() -> dict[str, Any]:
    """从环境变量组装同步 Redis 连接参数。"""
    return {
        'host': os.environ.get('REDIS_HOST', '127.0.0.1'),
        'port': int(os.environ.get('REDIS_PORT', '6379')),
        'username': os.environ.get('REDIS_USERNAME') or None,
        'password': os.environ.get('REDIS_PASSWORD') or None,
        'db': int(os.environ.get('REDIS_DATABASE', '2')),
        'decode_responses': True,
    }


def create_sync_redis() -> redis.Redis:
    """创建采集子进程用的同步 Redis 客户端。"""
    cfg = _redis_config()
    # Docker/WSL2 下空闲 TCP 易被掐；keepalive 避免下次 GET 重连卡数秒
    cfg['socket_keepalive'] = True
    cfg['health_check_interval'] = 15
    return redis.Redis(**cfg)


def dumps_json(data: Any) -> str:
    """JSON 序列化（保留中文）。"""
    return json.dumps(data, ensure_ascii=False)


def loads_json(text: str | None) -> Any:
    """JSON 反序列化；空串返回 None。"""
    if not text:
        return None
    return json.loads(text)
