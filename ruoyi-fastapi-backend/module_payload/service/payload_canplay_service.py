"""历史 CAN 表回放：按时间在 MySQL ``payload_tm_frame`` 计帧，按序号取帧。

不经文件解析进程。open 生成短会话 id，meta 写入 ``payload:canplay:{session}``（1h 过期）。
get_frame 优先 Redis ``f:{n}``；未命中则 DAO offset 查询再解析进 Hash。
每次响应带 frameCount，与文件回放滑块协议一致。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from module_payload import redis_keys as rk
from module_payload.constants import split_tm_table_key
from module_payload.dao.payload_tm_archive_dao import PayloadTmArchiveDao
from module_payload.fileplay.detect import fields_to_rows
from module_payload.fileplay import store
from module_payload.parsers.tm_can_yc_ingest import TmCanYcIngest
from module_payload.parsers.xl_can_tm import XlCanTmIngest


def _parse_time_ms(value: str | int | float | None) -> int:
    """毫秒时间戳、秒级时间戳（<1e10 则 ×1000）或 ``YYYY-MM-DD HH:mm:ss``。"""
    if value is None or value == '':
        raise ValueError('时间不能为空')
    if isinstance(value, (int, float)):
        v = int(value)
        return v if v > 10_000_000_000 else v * 1000
    text = str(value).strip().replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y/%m/%d %H:%M:%S'):
        try:
            return int(datetime.strptime(text, fmt).timestamp() * 1000)
        except ValueError:
            continue
    try:
        return int(float(text))
    except ValueError as e:
        raise ValueError(f'无法解析时间: {value}') from e


class PayloadCanPlayService:
    """历史 CAN 数据回放会话（不经文件解析进程）。"""

    @classmethod
    async def open(
        cls,
        db: AsyncSession,
        redis: aioredis.Redis,
        table_type: str,
        start: str | int,
        end: str | int,
    ) -> dict[str, Any]:
        """按表类型 + 时间窗 COUNT 帧数，写入 canplay 会话 Hash（1 小时过期）。"""
        data_sub = (table_type or '').upper()
        start_ms = _parse_time_ms(start)
        end_ms = _parse_time_ms(end)
        if start_ms > end_ms:
            raise ValueError('起始时间不能晚于结束时间')
        # 精确计数（SQL COUNT），滑块 max 一开始就准
        count = await PayloadTmArchiveDao.count_frames(db, data_sub, start_ms, end_ms)
        session = uuid.uuid4().hex[:16]
        meta = {
            'session': session,
            'type': data_sub,
            'startMs': start_ms,
            'endMs': end_ms,
            'frameCount': count,
            'frameCountExact': True,
            'status': 'ready',
        }
        key = rk.canplay_hash_key(session)
        await redis.hset(key, mapping={'meta': json.dumps(meta, ensure_ascii=False)})
        await redis.expire(key, 3600)
        return meta

    @classmethod
    async def get_frame(
        cls,
        db: AsyncSession,
        redis: aioredis.Redis,
        session: str,
        index: int,
    ) -> dict[str, Any]:
        """取第 N 帧（1-based）。会话过期需重新 open。响应含 frameCount。"""
        key = rk.canplay_hash_key(session)
        raw_meta = await redis.hget(key, 'meta')
        meta = json.loads(raw_meta) if raw_meta else None
        if not meta:
            raise ValueError('回放会话不存在或已过期，请重新解析')
        count = int(meta.get('frameCount') or 0)
        idx = max(1, int(index or 1))
        cached = store.loads(await redis.hget(key, store.frame_field(idx)))
        # 未缓存且序号合法：offset = index-1 对应时间范围内第 N 条归档行
        if cached is None and 1 <= idx <= count:
            row = await PayloadTmArchiveDao.get_frame_at_offset(
                db,
                meta['type'],
                int(meta['startMs']),
                int(meta['endMs']),
                idx - 1,
            )
            cached = cls._row_to_snap(row, meta['type'], idx) if row else None
            if cached:
                await redis.hset(key, store.frame_field(idx), json.dumps(cached, ensure_ascii=False))
        return {
            'frame': cached,
            'frameCount': count,
            'frameCountExact': True,
            'type': meta.get('type') or '',
            'session': session,
        }

    @classmethod
    def _row_to_snap(cls, row: Any, table_type: str, index: int) -> dict[str, Any]:
        """归档行 → 遥测表快照。优先 raw_hex 再解析（与实时 ingest 一致）；
        失败则用 points_json 键值对拼行。
        """
        fam, _local = split_tm_table_key(table_type)
        fields = None
        name = ''
        if getattr(row, 'raw_hex', None):
            try:
                ingest = XlCanTmIngest if fam == 'xl' else TmCanYcIngest
                parsed = ingest.parse_hex(row.raw_hex)
                fields = parsed.fields
                name = parsed.name
            except Exception:
                fields = None
        parsed_json = row.parsed_json if isinstance(row.parsed_json, dict) else {}
        if not name:
            name = str(parsed_json.get('name') or '')
        if fields is None:
            points = row.points_json if isinstance(row.points_json, dict) else {}
            fields = [
                {'id': k, 'name': k, 'value': v, 'show': v, 'unit': '', 'hex': ''}
                for k, v in points.items()
            ]
        ts_ms = int(row.ts_ms or 0)
        return {
            'type': table_type,
            'name': name,
            'rows': fields_to_rows(fields),
            'tsMs': ts_ms,
            'ts': datetime.fromtimestamp(ts_ms / 1000.0).strftime('%Y-%m-%d %H:%M:%S') if ts_ms else '',
            'dataSource': getattr(row, 'src_param', '') or 'mysql',
            'frameIndex': index,
        }
