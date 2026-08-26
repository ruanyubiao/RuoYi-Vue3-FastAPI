"""LVDS 工程遥测服务层（演示数据）。"""

from __future__ import annotations

import math
import time
from typing import Any

from redis import asyncio as aioredis

from module_payload import redis_keys as rk
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.redis_store import get_lvds_points


class PayloadLvdsService:
    """LVDS 工程遥测：信号列表与波形点（无数据时用演示曲线）。"""

    DEMO_DEVICE = 'lvds:demo'
    ENGINEERING_TYPES = ('7E9B', '7E9D', '7E9F')

    @classmethod
    def list_signals(cls, table_type: str = '7E9B', reload: bool = False) -> list[dict[str, Any]]:
        """从遥测表定义抽出信号；配置为空时回落演示项。"""
        table_def = PayloadConfigService.get_telemetry_table_def(table_type, reload=reload)
        signals = []
        for r in table_def.get('row', []):
            rid = r.get('id', '')
            if not rid:
                continue
            signals.append(
                {
                    'id': rid,
                    'name': r.get('name', rid),
                    'varName': rid.lower(),
                    'unit': r.get('unit', ''),
                }
            )
        if not signals:
            # 配置未就绪时仍给出可画曲线的占位信号
            signals = [
                {'id': 'qd_x_pos', 'name': 'QD x坐标', 'varName': 'qd_x_pos', 'unit': ''},
                {'id': 'qd_y_pos', 'name': 'QD y坐标', 'varName': 'qd_y_pos', 'unit': ''},
            ]
        return signals

    @classmethod
    async def get_data(
        cls,         redis: aioredis.Redis, signal: str, device_id: str = DEMO_DEVICE, limit: int = 2000
    ) -> dict[str, Any]:
        """读 Redis 波形点；无点则生成演示数据。"""
        points = await get_lvds_points(redis, device_id, signal, limit)
        if not points:
            points = cls._generate_demo_points(signal, limit)
        return {'signal': signal, 'deviceId': device_id, 'points': points}

    @classmethod
    def _generate_demo_points(cls, signal: str, limit: int) -> list[dict[str, Any]]:
        """按信号名散列生成正弦演示点。"""
        now_ms = int(time.time() * 1000)
        seed = sum(ord(c) for c in signal)
        points = []
        for i in range(min(limit, 500)):
            t = now_ms - (limit - i) * 2
            phase = (seed + i) * 0.02
            v = math.sin(phase) * 100 + math.cos(phase * 0.3) * 20 + (seed % 10)
            points.append({'t': t, 'v': round(v, 4)})
        return points
