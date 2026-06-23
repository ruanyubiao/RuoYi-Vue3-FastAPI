"""遥测数据查询服务层。"""

from __future__ import annotations

from typing import Any

from redis import asyncio as aioredis

from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.redis_store import get_curve_points, get_telemetry, set_curve_subscribe


class PayloadTelemetryService:
    @classmethod
    async def get_table(cls, redis: aioredis.Redis, device_id: str, table_type: str) -> dict[str, Any]:
        data = await get_telemetry(redis, device_id, table_type) or {}
        fields = data.get('fields') or data.get('rows') or []
        rows = []
        for f in fields:
            rows.append(
                {
                    'id': f.get('id', ''),
                    'name': f.get('name', ''),
                    'value': f.get('value', f.get('show', '')),
                    'show': f.get('show', f.get('value', '')),
                    'unit': f.get('unit', ''),
                    'hex': f.get('hex', ''),
                }
            )
        return {
            'type': (table_type or '').upper(),
            'name': data.get('name', ''),
            'ts': data.get('ts', ''),
            'rows': rows,
        }

    @classmethod
    def get_fields(cls, table_type: str, reload: bool = False) -> list[dict[str, Any]]:
        table_def = PayloadConfigService.get_telemetry_table_def(table_type, reload=reload)
        rows = table_def.get('row', [])
        return [
            {
                'id': r.get('id', ''),
                'name': r.get('name', ''),
                'unit': r.get('unit', ''),
            }
            for r in rows
            if r.get('id')
        ]

    @classmethod
    async def subscribe_curve(
        cls, redis: aioredis.Redis, device_id: str, table_type: str, field: str, enabled: bool = True
    ) -> None:
        await set_curve_subscribe(redis, device_id, table_type, field, enabled)

    @classmethod
    async def get_curve_data(
        cls, redis: aioredis.Redis, device_id: str, table_type: str, field: str, limit: int = 600
    ) -> dict[str, Any]:
        table_def = PayloadConfigService.get_telemetry_table_def(table_type)
        name = field
        unit = ''
        for r in table_def.get('row', []):
            if r.get('id') == field:
                name = r.get('name', field)
                unit = r.get('unit', '')
                break
        points = await get_curve_points(redis, device_id, table_type, field, limit)
        return {'field': field, 'name': name, 'unit': unit, 'points': points}
