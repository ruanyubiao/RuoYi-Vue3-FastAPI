"""遥测数据查询服务层。"""

from __future__ import annotations

from typing import Any

from redis import asyncio as aioredis

from exceptions.exception import ServiceException
from module_payload.cfg.can_yc_frame import hex_to_bytes, parse_can_yc_frame, verify_can_yc_frame
from module_payload.cfg.payload_config_loader import TELE_METRY_CFG_FILE
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.redis_store import (
    append_curve_points,
    get_curve_points,
    get_telemetry,
    set_telemetry,
)


class PayloadTelemetryService:
    _tm_mgr = None

    @classmethod
    def _get_tm_mgr(cls):
        if cls._tm_mgr is None:
            from TeleMetryParser import TeleMetryCfgManager

            mgr = TeleMetryCfgManager.instance()
            if not mgr.init(str(TELE_METRY_CFG_FILE)):
                raise ServiceException(message='遥测配置初始化失败')
            cls._tm_mgr = mgr
        return cls._tm_mgr

    @classmethod
    async def get_table(
        cls,
        redis: aioredis.Redis,
        device_id: str,
        table_type: str,
        data_id: str | None = None,
        need_cfg: bool = False,
    ) -> dict[str, Any]:
        data = await get_telemetry(redis, device_id, table_type) or {}
        ts = data.get('ts', '')
        current_id = data.get('dataId')
        has_data = current_id is not None
        changed = not (
            data_id is not None
            and str(data_id) != ''
            and current_id is not None
            and str(data_id) == str(current_id)
        )

        result: dict[str, Any] = {
            'type': (table_type or '').upper(),
            'name': data.get('name', ''),
            'ts': ts,
            'dataId': current_id,
            'changed': changed,
            'connected': has_data,
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
        device_id: str,
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
        points = await get_curve_points(redis, device_id, table_type, field, limit, since_t)
        return {
            'deviceId': device_id,
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
                    item['device_id'],
                    item['type'],
                    item['field'],
                    item.get('limit', 500),
                    item.get('since_t'),
                )
            )
        return results

    @classmethod
    async def inject_can_yc(cls, redis: aioredis.Redis, device_id: str, hex_text: str) -> dict[str, Any]:
        """
        开发测试：注入已组帧的 CAN 遥测复合帧。
        流程对齐 C++ setPayloadCommandCanYcDataTest -> createCanYcAck，
        再按采集进程 _parse_and_store 写入 Redis。
        """
        if not device_id:
            raise ServiceException(message='请指定设备ID')
        try:
            raw = hex_to_bytes(hex_text)
        except ValueError as e:
            raise ServiceException(message=f'HEX 格式错误: {e}') from e

        ok, msg, frame = verify_can_yc_frame(raw)
        if not ok:
            raise ServiceException(message=msg)

        parsed = parse_can_yc_frame(frame)
        table_key = parsed['dataType']
        # 与 can_collector._parse_and_store 一致：payload 从 dataType 之后到帧尾（含校验和）
        payload_hex = ' '.join(f'{b:02X}' for b in frame[4:])

        tm_mgr = cls._get_tm_mgr()
        lines = tm_mgr.parse_hex(table_key, payload_hex, include_datetime=False)
        if not lines:
            raise ServiceException(message=f'遥测解析无结果: dataType=0x{table_key}')

        cfg = tm_mgr.get_table_cfg_by_key(table_key)
        fields: list[dict[str, Any]] = []
        for ln in lines:
            num = getattr(ln, 'val', None)
            raw = num.value() if num is not None and hasattr(num, 'value') else None
            fields.append(
                {
                    'id': getattr(ln, 'id', ''),
                    'name': getattr(ln, 'name', ''),
                    'value': raw,
                    'show': getattr(ln, 'show', ''),
                    'hex': getattr(ln, 'hex', ''),
                    'unit': getattr(ln, 'unit', ''),
                }
            )

        stored = await set_telemetry(redis, device_id, table_key, fields, cfg.name if cfg else table_key)
        await append_curve_points(redis, device_id, table_key, fields, stored.get('ts', ''))
        return {
            'deviceId': device_id,
            'dataType': table_key,
            'frameType': parsed['frameType'],
            'dataLen': parsed['dataLen'],
            'size': parsed['size'],
            'fieldCount': len(fields),
            'name': stored.get('name', ''),
            'ts': stored.get('ts', ''),
        }
