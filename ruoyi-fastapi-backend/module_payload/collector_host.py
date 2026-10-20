"""当前采集机标识。请求里用上下文，监工和工作进程用环境变量。"""

from __future__ import annotations

import os
import re
from contextvars import ContextVar

_HOST_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_ctx: ContextVar[str | None] = ContextVar('collector_host', default=None)

HEADER_NAME = 'X-Collector-Host'


def normalize_collector_host(value: str | None, *, fallback: str = 'local') -> str:
    """只保留字母、数字、下划线和连字符。空或非法时用 fallback。"""
    raw = str(value or '').strip()
    if _HOST_RE.fullmatch(raw):
        return raw
    fb = str(fallback or 'local').strip()
    if _HOST_RE.fullmatch(fb):
        return fb
    return 'local'


def current_collector_host() -> str:
    """请求上下文优先，其次 COLLECTOR_HOST，再次配置，最后 local。"""
    picked = _ctx.get()
    if picked:
        return picked
    env = os.environ.get('COLLECTOR_HOST')
    if env and str(env).strip():
        return normalize_collector_host(env)
    try:
        from config.env import AppConfig

        return normalize_collector_host(getattr(AppConfig, 'collector_host', None))
    except Exception:
        return 'local'


def set_collector_host(value: str | None):
    """绑定当前上下文的采集机。返回 token，用完交给 reset。"""
    host = normalize_collector_host(value, fallback=current_collector_host())
    return _ctx.set(host)


def reset_collector_host(token) -> None:
    """恢复 set_collector_host 之前的上下文。"""
    _ctx.reset(token)
