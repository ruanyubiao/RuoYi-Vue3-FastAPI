"""服务健康检查：数据库、Redis 与运行时基本信息。"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

from sqlalchemy import text

from config.database import async_engine
from config.env import AppConfig, DataBaseConfig

_STARTED_AT = time.monotonic()
_CHECK_TIMEOUT_S = 2.0


class HealthService:
    @classmethod
    async def check(cls, redis: Any | None) -> tuple[dict[str, Any], int]:
        database, redis_check = await asyncio.gather(
            cls._check_database(),
            cls._check_redis(redis),
        )
        overall = 'ok' if database['status'] == 'ok' and redis_check['status'] == 'ok' else 'error'

        now = datetime.now().astimezone()  # 或直接用 datetime.now()
        time_str = f"{now.year}-{now.month}-{now.day} {now.hour:02d}:{now.minute:02d}:{now.second:02d}"
        # time_str = datetime.now().astimezone().isoformat(timespec='milliseconds')
        payload = {
            'status': overall,
            'service': AppConfig.app_name,
            'version': cls._app_version(),
            'env': AppConfig.app_env,
            'time': time_str,
            'uptimeSeconds': int(time.monotonic() - _STARTED_AT),
            'database': database,
            'redis': redis_check,
            'collectors': cls._collectors(),
        }
        return payload, 200 if overall == 'ok' else 503

    @staticmethod
    def _app_version() -> str:
        try:
            from version import appVersion

            return str(appVersion)
        except Exception:
            return AppConfig.app_version

    @classmethod
    async def _check_database(cls) -> dict[str, Any]:
        result: dict[str, Any] = {'status': 'error', 'type': DataBaseConfig.db_type}
        started = time.perf_counter()
        try:
            await asyncio.wait_for(cls._ping_database(), timeout=_CHECK_TIMEOUT_S)
            result['status'] = 'ok'
        except Exception as exc:
            result['error'] = cls._safe_error(exc)
        result['latencyMs'] = round((time.perf_counter() - started) * 1000, 1)
        return result

    @staticmethod
    async def _ping_database() -> None:
        async with async_engine.connect() as conn:
            await conn.execute(text('SELECT 1'))

    @classmethod
    async def _check_redis(cls, redis: Any | None) -> dict[str, Any]:
        result: dict[str, Any] = {'status': 'error'}
        started = time.perf_counter()
        if redis is None:
            result['error'] = 'Redis 未初始化'
            result['latencyMs'] = round((time.perf_counter() - started) * 1000, 1)
            return result
        try:
            await asyncio.wait_for(redis.ping(), timeout=_CHECK_TIMEOUT_S)
            result['status'] = 'ok'
        except Exception as exc:
            result['error'] = cls._safe_error(exc)
        result['latencyMs'] = round((time.perf_counter() - started) * 1000, 1)
        return result

    @staticmethod
    def _collectors() -> dict[str, int]:
        try:
            from module_payload.collectors.process_manager import CollectorProcessManager

            opened = CollectorProcessManager.instance().list_opened()
        except Exception:
            return {'opened': 0, 'alive': 0}
        return {
            'opened': len(opened),
            'alive': sum(1 for item in opened if item.get('alive')),
        }

    @staticmethod
    def _safe_error(exc: BaseException) -> str:
        text = f'{type(exc).__name__}: {exc}'
        return text[:240]
