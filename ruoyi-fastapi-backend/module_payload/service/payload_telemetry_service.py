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

    @classmethod
    async def inject_pipeline(
        cls,
        redis: aioredis.Redis,
        hex_text: str,
        assembler_id: str,
        parser_id: str,
    ) -> dict[str, Any]:
        """通用模拟：HEX → 组装器 →（可选写 assembled）→ 解析器。来源 http:devtest。"""
        import json
        from datetime import datetime

        from module_payload import redis_keys as rk
        from module_payload.assemblers import create_assembler, normalize_assembler_id
        from module_payload.cfg.can_yc_frame import hex_to_bytes
        from module_payload.constants import ERROR_LOG_MAX, SRC_KIND_HTTP
        from module_payload.parsers import resolve_parser
        from module_payload.service.payload_error_store import normalize_error_type

        aid = normalize_assembler_id(assembler_id)
        pid = (parser_id or '').strip()
        if not pid:
            raise ServiceException(message='请选择帧解析类型（解析器）')

        ingest = resolve_parser(pid)
        if ingest is None or not hasattr(ingest, 'ingest_bytes_async'):
            raise ServiceException(message=f'未知或不可用的解析器: {pid}')

        try:
            raw = hex_to_bytes(hex_text)
        except Exception as e:
            raise ServiceException(message=f'HEX 解析失败: {e}') from e
        if not raw:
            raise ServiceException(message='HEX 为空')

        device_id = 'http:devtest'
        assembler = create_assembler(aid)

        async def _push_error(stage: str, message: str, data_len: int | None = None) -> None:
            error_type = normalize_error_type(stage)
            entry = {
                'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
                'type': error_type,
                'stage': stage,
                'message': message,
                'deviceId': device_id,
                'assemblerId': aid,
                'parserId': pid,
            }
            if data_len is not None:
                entry['dataLen'] = data_len
            dumped = json.dumps(entry, ensure_ascii=False)
            await redis.set(rk.error_type_latest_key(error_type), dumped)
            key = rk.error_type_key(error_type)
            await redis.lpush(key, dumped)
            await redis.ltrim(key, 0, ERROR_LOG_MAX - 1)

        try:
            payloads = assembler.feed(raw)
        except Exception as e:
            await _push_error('assembler', f'组装异常: {e}', len(raw))
            raise ServiceException(message=f'组装异常: {e}') from e

        take_errors = getattr(assembler, 'take_errors', None)
        asm_errors: list[str] = []
        if callable(take_errors):
            asm_errors = take_errors()
            for err in asm_errors:
                await _push_error('assembler', err, len(raw))

        if not payloads:
            detail = '；'.join(asm_errors) if asm_errors else '未组装出完整载荷（可能缺子包）'
            raise ServiceException(message=detail)

        results: list[dict[str, Any]] = []
        for item in payloads:
            if not item.data:
                continue
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            meta = dict(item.meta or {})
            meta.setdefault('assemblerId', aid)
            assembled_entry = {
                'deviceId': device_id,
                'assemblerId': aid,
                'ts': ts,
                'len': len(item.data),
                'hex': ' '.join(f'{b:02X}' for b in item.data),
                'meta': meta,
            }
            dumped = json.dumps(assembled_entry, ensure_ascii=False)
            await redis.set(rk.assembled_latest_key(device_id), dumped)
            log_key = rk.assembled_log_key(device_id)
            await redis.lpush(log_key, dumped)
            await redis.ltrim(log_key, 0, 49)

            try:
                parsed = await ingest.ingest_bytes_async(
                    redis,
                    item.data,
                    src_param=device_id,
                    src_kind=SRC_KIND_HTTP,
                    parser_id=pid,
                )
                results.append(parsed)
            except ValueError as e:
                await _push_error('parser', str(e), len(item.data))
                raise ServiceException(message=str(e)) from e
            except RuntimeError as e:
                await _push_error('parser', str(e), len(item.data))
                raise ServiceException(message=str(e)) from e

        if not results:
            raise ServiceException(message='组装完成但解析器未产出结果')

        last = results[-1]
        return {
            'assemblerId': aid,
            'parserId': pid,
            'assembledCount': len(payloads),
            'parsedCount': len(results),
            'assemblerErrors': asm_errors,
            'dataType': last.get('dataType'),
            'name': last.get('name'),
            'fieldCount': last.get('fieldCount'),
            'ts': last.get('ts'),
            'results': results,
        }
