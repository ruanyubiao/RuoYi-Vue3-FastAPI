"""遥测数据查询服务层。"""

from __future__ import annotations

from typing import Any

from redis import asyncio as aioredis

from exceptions.exception import ServiceException
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.redis_store import (
    get_curve_points,
    get_telemetry_latest,
)


class PayloadTelemetryService:
    @classmethod
    async def get_table(
        cls,
        redis: aioredis.Redis,
        table_type: str,
        data_id: str | None = None,
        need_cfg: bool = False,
    ) -> dict[str, Any]:
        data = await get_telemetry_latest(redis, table_type) or {}
        ts = data.get('ts', '')
        current_id = data.get('dataId')
        has_data = current_id is not None
        changed = not (
            data_id is not None
            and str(data_id) != ''
            and current_id is not None
            and str(data_id) == str(current_id)
        )

        src_param = data.get('srcParam') or ''
        src_kind = data.get('srcKind') or ''
        result: dict[str, Any] = {
            'type': (table_type or '').upper(),
            'name': data.get('name', ''),
            'ts': ts,
            'dataId': current_id,
            'changed': changed,
            'connected': has_data,
            'dataKind': data.get('dataKind') or 'tm',
            'dataSub': data.get('dataSub') or (table_type or '').upper(),
            'srcKind': src_kind,
            'srcParam': src_param,
            'dataSource': src_param if has_data else '',
            'parserId': data.get('parserId') or '',
        }

        if need_cfg:
            table_def = PayloadConfigService.get_telemetry_table_def(table_type)
            result['cfg'] = table_def
            if not result['name']:
                result['name'] = table_def.get('name', '')

        if not changed:
            return result

        rows = []
        for f in data.get('fields') or []:
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
        result['rows'] = rows
        return result

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
    async def get_curve_data(
        cls,
        redis: aioredis.Redis,
        table_type: str,
        field: str,
        limit: int = 500,
        since_t: int | None = None,
    ) -> dict[str, Any]:
        table_def = PayloadConfigService.get_telemetry_table_def(table_type)
        name = field
        unit = ''
        for r in table_def.get('row', []):
            if r.get('id') == field:
                name = r.get('name', field)
                unit = r.get('unit', '')
                break
        points = await get_curve_points(redis, table_type, field, limit, since_t)
        return {
            'type': (table_type or '').upper(),
            'field': field,
            'name': name,
            'unit': unit,
            'points': points,
        }

    @classmethod
    async def get_curve_data_batch(
        cls, redis: aioredis.Redis, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for item in items:
            results.append(
                await cls.get_curve_data(
                    redis,
                    item['type'],
                    item['field'],
                    item.get('limit', 500),
                    item.get('since_t'),
                )
            )
        return results

    @classmethod
    async def inject_can_yc(cls, redis: aioredis.Redis, hex_text: str) -> dict[str, Any]:
        """
        开发测试：注入已组帧的 CAN 遥测复合帧。
        与真 CAN 共用 TmCanYcIngest（严格校验 + 解析 + Redis/归档）。
        来源固定 http:devtest；表类型取自帧内 dataType，无需 API 传解析类型。
        """
        from module_payload.constants import SRC_KIND_HTTP
        from module_payload.parsers.tm_can_yc_ingest import TmCanYcIngest

        try:
            return await TmCanYcIngest.ingest_hex_async(
                redis,
                hex_text,
                src_param='http:devtest',
                src_kind=SRC_KIND_HTTP,
            )
        except ValueError as e:
            raise ServiceException(message=str(e)) from e
        except RuntimeError as e:
            raise ServiceException(message=str(e)) from e
