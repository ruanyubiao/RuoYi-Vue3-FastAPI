"""遥测数据查询服务层。"""

from __future__ import annotations

from typing import Any

from redis import asyncio as aioredis

from exceptions.exception import ServiceException
from module_payload.cfg.payload_config_loader import PayloadConfigLoader
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.redis_store import (
    get_curve_points,
    get_telemetry_latest,
)


class PayloadTelemetryService:
    """遥测热层查询：最新表/曲线来自 Redis，表结构来自配置。"""

    SOURCE_LIVE = 'live'
    SOURCE_DB = 'db'
    SOURCE_FILE = 'file'

    @classmethod
    def _norm_table_source(cls, source: str | None) -> str:
        """统一 source：live / db / file。未识别按 live。mysql 视为 db 别名。"""
        k = str(source or cls.SOURCE_LIVE).strip().lower()
        if k in ('db', 'mysql', 'history', 'canplay', 'archive'):
            return cls.SOURCE_DB
        if k in ('file', 'fileplay'):
            return cls.SOURCE_FILE
        return cls.SOURCE_LIVE

    @classmethod
    def _cfg_only_table(cls, table_type: str, need_cfg: bool) -> dict[str, Any]:
        """历史页：不读 Redis 热层。need_cfg 时只回表定义骨架（空值）。"""
        cfg_meta = PayloadConfigLoader.find_telemetry_table_meta(table_type)
        result: dict[str, Any] = {
            'type': (table_type or '').upper(),
            'name': '',
            'ts': '',
            'dataId': None,
            'changed': False,
            'srcParam': '',
            'cfgDatetime': cfg_meta.get('datetime') or '',
            'cfgMtime': cfg_meta.get('mtime') or '',
        }
        if not need_cfg:
            return result
        table_def = cfg_meta.get('table') or PayloadConfigService.get_telemetry_table_def(table_type)
        result['cfg'] = table_def
        result['name'] = table_def.get('name', '')
        result['rows'] = [
            {
                'id': r.get('id', ''),
                'name': r.get('name', ''),
                'value': '',
                'show': '',
                'unit': r.get('unit', ''),
                'hex': '',
            }
            for r in (table_def.get('row') or [])
            if r.get('id')
        ]
        result['changed'] = True
        return result

    @classmethod
    async def get_table(
        cls,
        redis: aioredis.Redis,
        table_type: str,
        data_id: str | None = None,
        need_cfg: bool = False,
        source: str = 'live',
    ) -> dict[str, Any]:
        """读 Redis 最新一帧；changed=false 时不下发 rows。need_cfg 时附带表定义。

        HTTP 是热层瘦信封：只回表格轮询字段（type/name/ts/dataId/changed/srcParam
        + cfg 戳）。dataKind/dataSub/srcKind/parserId 仍在 Redis 帧内，不在此重复。

        source 非 live（db/file）时不碰 payload:tm，避免历史页把实时值画上去。
        """
        if cls._norm_table_source(source) != cls.SOURCE_LIVE:
            return cls._cfg_only_table(table_type, need_cfg)
        data = await get_telemetry_latest(redis, table_type) or {}
        ts = data.get('ts', '')
        current_id = data.get('dataId')
        has_data = current_id is not None
        same_id = (
            data_id is not None
            and str(data_id) != ''
            and current_id is not None
            and str(data_id) == str(current_id)
        )

        src_param = data.get('srcParam') or ''
        cfg_meta = PayloadConfigLoader.find_telemetry_table_meta(table_type)
        result: dict[str, Any] = {
            'type': (table_type or '').upper(),
            'name': data.get('name', ''),
            'ts': ts,
            'dataId': current_id,
            'changed': not same_id,
            'srcParam': src_param if has_data else '',
            # 配置时间戳：前端可据此使 localStorage 失效，无需等 TTL
            'cfgDatetime': cfg_meta.get('datetime') or '',
            'cfgMtime': cfg_meta.get('mtime') or '',
        }

        if need_cfg:
            table_def = cfg_meta.get('table') or PayloadConfigService.get_telemetry_table_def(table_type)
            result['cfg'] = table_def
            if not result['name']:
                result['name'] = table_def.get('name', '')

        # 无热层：空表骨架只在 needCfg 时回一次；后续轮询不再带 rows
        if not has_data:
            if need_cfg:
                table_def = result.get('cfg') or cfg_meta.get('table') or {}
                if not result.get('name') and table_def.get('name'):
                    result['name'] = table_def.get('name', '')
                result['rows'] = [
                    {
                        'id': r.get('id', ''),
                        'name': r.get('name', ''),
                        'value': '',
                        'show': '',
                        'unit': r.get('unit', ''),
                        'hex': '',
                    }
                    for r in (table_def.get('row') or [])
                    if r.get('id')
                ]
                result['changed'] = True
                return result
            # 客户端仍带着旧 dataId，说明热层已消失，通知清空
            if data_id is not None and str(data_id) != '':
                result['changed'] = True
                result['rows'] = []
                return result
            result['changed'] = False
            return result

        if same_id:
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
    def get_fields(cls, table_type: str, reload: bool = False, family: str | None = None) -> list[dict[str, Any]]:
        """从表定义取字段 id/name/unit（不读 Redis）。"""
        table_def = PayloadConfigService.get_telemetry_table_def(table_type, reload=reload, family=family)
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
        """从 Redis ZSet 取实时曲线点。"""
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
        """批量取多条实时曲线。"""
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
        与真 CAN 共用 BiuCanTmIngest（严格校验 + 解析 + Redis/归档）。
        来源固定 http:devtest；表类型取自帧内 dataType，无需 API 传解析类型。
        """
        from module_payload.constants import SRC_KIND_HTTP
        from module_payload.parsers.biu_can_tm import BiuCanTmIngest

        try:
            return await BiuCanTmIngest.ingest_hex_async(
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
        from datetime import datetime

        from module_payload import redis_keys as rk
        from module_payload.assemblers import create_assembler, normalize_assembler_id
        from module_payload.cfg.hex_text import hex_to_bytes
        from module_payload.constants import ERROR_LOG_MAX, SRC_KIND_HTTP
        from module_payload.parsers import resolve_parser
        from module_payload.pipeline import assembled_entry, feed_assembler, write_assembled_async
        from module_payload.store.error_store import normalize_error_type
        from module_payload.store.jsonutil import dumps_json

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
            """模拟页解析失败写入 Redis 错误列表。"""
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
            dumped = dumps_json(entry)
            await redis.set(rk.error_type_latest_key(error_type), dumped)
            key = rk.error_type_key(error_type)
            await redis.lpush(key, dumped)
            await redis.ltrim(key, 0, ERROR_LOG_MAX - 1)

        try:
            payloads, asm_errors = feed_assembler(assembler, raw)
        except Exception as e:
            await _push_error('assembler', f'组装异常: {e}', len(raw))
            raise ServiceException(message=f'组装异常: {e}') from e

        for err in asm_errors:
            await _push_error('assembler', err, len(raw))

        if not payloads:
            detail = '；'.join(asm_errors) if asm_errors else '未组装出完整载荷（可能缺子包）'
            raise ServiceException(message=detail)

        results: list[dict[str, Any]] = []
        # 模拟注入按「整条样例」自洽：清掉该来源的 D9 mux last-known，
        # 避免同进程上一条样例（或其它通道）污染本条解析结果。
        mux_cache = getattr(ingest, '_d9_mux_cache', None)
        if isinstance(mux_cache, dict):
            mux_cache.pop(device_id, None)

        for item in payloads:
            if not item.data:
                continue
            entry = assembled_entry(device_id, aid, item.data, item.meta)
            await write_assembled_async(redis, device_id, entry)

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

    @classmethod
    def get_simulate_sample(
        cls,
        *,
        key: str = '',
        assembler_id: str = '',
        parser_id: str = '',
    ) -> dict[str, Any]:
        """通用模拟示例 HEX：按黄金用例 key 或组装器+解析器取一条；匹配不到返回空 dict。"""
        from module_payload.tm_golden_samples import get_simulate_sample as load_sample

        return load_sample(key=key, assembler_id=assembler_id, parser_id=parser_id)

    @classmethod
    def list_simulate_samples(
        cls,
        *,
        assembler_id: str = '',
        parser_id: str = '',
    ) -> list[dict[str, str]]:
        """通用模拟：按组装器+解析器列出可选黄金样本按钮。"""
        from module_payload.tm_golden_samples import list_simulate_samples as load_samples

        return load_samples(assembler_id=assembler_id, parser_id=parser_id)
