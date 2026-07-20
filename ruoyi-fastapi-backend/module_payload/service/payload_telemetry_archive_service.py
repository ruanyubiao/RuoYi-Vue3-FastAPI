from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any

from redis import asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import AsyncSessionLocal
from config.env import DataBaseConfig
from module_payload.constants import DATA_KIND_TM, PARSER_TM_CAN_YC, infer_src_kind
from module_payload.dao.payload_tm_archive_dao import PayloadTmArchiveDao
from module_payload.entity.do.payload_tm_field_num_do import PayloadTmFieldNum
from module_payload.entity.do.payload_tm_frame_do import PayloadTmFrame
from module_payload.entity.do.payload_tx_log_do import PayloadTxLog
from module_payload import redis_keys as rk
from utils.log_util import logger

ARCHIVE_BATCH_SIZE = 50
ARCHIVE_FLUSH_INTERVAL_S = 0.5
TX_BATCH_SIZE = 50


def _numeric_fields_from_parsed(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in fields:
        fid = row.get('id')
        if not fid:
            continue
        try:
            val = float(row.get('value', row.get('show', 0)))
        except (TypeError, ValueError):
            continue
        out.append({'field_id': fid, 'value_num': val})
    return out


def build_archive_event(
    *,
    ts_ms: int,
    raw_hex: str,
    fields: list[dict[str, Any]],
    data_sub: str,
    src_param: str,
    name: str = '',
    src_kind: str | None = None,
    data_kind: str = DATA_KIND_TM,
    parser_id: str | None = PARSER_TM_CAN_YC,
    cfg_version: str | None = None,
) -> dict[str, Any]:
    data_sub = (data_sub or '').upper()
    src_kind = src_kind or infer_src_kind(src_param)
    parsed_json = {
        'name': name,
        'fields': fields,
        'dataKind': data_kind,
        'dataSub': data_sub,
        'srcKind': src_kind,
        'srcParam': src_param,
        'parserId': parser_id,
    }
    return {
        'data_kind': data_kind,
        'data_sub': data_sub,
        'src_kind': src_kind,
        'src_param': src_param,
        'parser_id': parser_id,
        'ts_ms': ts_ms,
        'raw_hex': raw_hex,
        'parsed_json': parsed_json,
        'field_count': len(fields),
        'cfg_version': cfg_version,
        'numeric_fields': _numeric_fields_from_parsed(fields),
    }


class PayloadTelemetryArchiveService:
    _worker_task: asyncio.Task | None = None
    _stop_event: asyncio.Event | None = None

    @classmethod
    def enqueue_sync(cls, redis_client: Any, event: dict[str, Any]) -> None:
        redis_client.lpush(rk.archive_queue_key(), json.dumps(event, ensure_ascii=False))

    @classmethod
    async def enqueue(cls, redis: aioredis.Redis, event: dict[str, Any]) -> None:
        await redis.lpush(rk.archive_queue_key(), json.dumps(event, ensure_ascii=False))

    @classmethod
    async def _persist_batch(cls, db: AsyncSession, events: list[dict[str, Any]]) -> None:
        frame_rows: list[PayloadTmFrame] = []
        field_rows: list[PayloadTmFieldNum] = []
        for ev in events:
            data_sub = (ev.get('data_sub') or '').upper()
            src_param = ev.get('src_param') or ''
            src_kind = ev.get('src_kind') or infer_src_kind(src_param)
            frame = PayloadTmFrame(
                data_kind=ev.get('data_kind') or DATA_KIND_TM,
                data_sub=data_sub,
                src_kind=src_kind,
                src_param=src_param,
                parser_id=ev.get('parser_id'),
                ts_ms=int(ev['ts_ms']),
                raw_hex=ev.get('raw_hex') or '',
                parsed_json=ev.get('parsed_json') or {},
                field_count=int(ev.get('field_count') or 0),
                cfg_version=ev.get('cfg_version'),
                created_at=datetime.now(),
            )
            frame_rows.append(frame)
        db.add_all(frame_rows)
        await db.flush()

        for frame, ev in zip(frame_rows, events, strict=True):
            frame_id = frame.id
            data_sub = frame.data_sub
            src_param = frame.src_param
            for nf in ev.get('numeric_fields') or []:
                field_rows.append(
                    PayloadTmFieldNum(
                        src_param=src_param,
                        data_sub=data_sub,
                        field_id=nf['field_id'],
                        ts_ms=int(ev['ts_ms']),
                        value_num=float(nf['value_num']),
                        frame_id=frame_id,
                    )
                )
        if field_rows:
            db.add_all(field_rows)
        await db.commit()

    @classmethod
    async def flush_events(cls, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        async with AsyncSessionLocal() as db:
            try:
                await cls._persist_batch(db, events)
            except Exception:
                await db.rollback()
                logger.exception('遥测归档批量写入失败 count=%s', len(events))
                raise

    @classmethod
    async def flush_tx_events(cls, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        rows = [
            PayloadTxLog(
                ts_ms=int(ev['ts_ms']),
                src_kind=ev.get('src_kind') or 'can',
                src_param=ev.get('src_param') or '',
                cmd_name=ev.get('cmd_name') or None,
                order_id=ev.get('order_id') or None,
                raw_hex=ev.get('raw_hex') or '',
                success=int(ev.get('success', 1)),
                message=ev.get('message') or None,
                operator=ev.get('operator') or None,
                created_at=datetime.now(),
            )
            for ev in events
        ]
        async with AsyncSessionLocal() as db:
            try:
                db.add_all(rows)
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception('遥控发送记录写入失败 count=%s', len(events))
                raise

    @classmethod
    async def _drain_tx_queue(cls, redis: aioredis.Redis) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for _ in range(TX_BATCH_SIZE):
            raw = await redis.lpop(rk.tx_queue_key())
            if not raw:
                break
            text = raw.decode() if isinstance(raw, bytes) else str(raw)
            out.append(json.loads(text))
        return out

    @classmethod
    async def _worker_loop(cls, redis: aioredis.Redis) -> None:
        assert cls._stop_event is not None
        pending: list[dict[str, Any]] = []
        last_flush = time.monotonic()
        while not cls._stop_event.is_set():
            try:
                item = await redis.brpop(rk.archive_queue_key(), timeout=1)
                if item:
                    pending.append(json.loads(item[1]))
            except asyncio.CancelledError:
                raise
            except (RedisConnectionError, RedisTimeoutError, ConnectionError, OSError) as exc:
                # 休眠唤醒 / 网络抖动时常见，降噪并退避重试
                logger.warning('遥测归档队列 Redis 连接异常，稍后重试: %s', exc)
                await asyncio.sleep(2)
            except Exception:
                logger.exception('遥测归档队列读取失败')
                await asyncio.sleep(1)

            try:
                tx_batch = await cls._drain_tx_queue(redis)
                if tx_batch:
                    await cls.flush_tx_events(tx_batch)
            except Exception:
                logger.exception('遥控发送队列刷写失败')

            now = time.monotonic()
            should_flush = len(pending) >= ARCHIVE_BATCH_SIZE or (
                pending and now - last_flush >= ARCHIVE_FLUSH_INTERVAL_S
            )
            if should_flush:
                batch = pending
                pending = []
                last_flush = now
                try:
                    await cls.flush_events(batch)
                except Exception:
                    for ev in reversed(batch):
                        try:
                            await cls.enqueue(redis, ev)
                        except Exception:
                            logger.exception('遥测归档失败重入队丢弃 src=%s', ev.get('src_param'))
                            break

        if pending:
            try:
                await cls.flush_events(pending)
            except Exception:
                logger.exception('遥测归档停止前刷新失败 count=%s', len(pending))

    @classmethod
    async def start_worker(cls, redis: aioredis.Redis) -> None:
        if cls._worker_task is not None:
            return
        cls._stop_event = asyncio.Event()
        cls._worker_task = asyncio.create_task(cls._worker_loop(redis))
        logger.info('遥测归档 worker 已启动 db=%s', DataBaseConfig.db_type)

    @classmethod
    async def stop_worker(cls) -> None:
        if cls._worker_task is None:
            return
        assert cls._stop_event is not None
        cls._stop_event.set()
        cls._worker_task.cancel()
        try:
            await cls._worker_task
        except asyncio.CancelledError:
            pass
        cls._worker_task = None
        cls._stop_event = None
        logger.info('遥测归档 worker 已停止')

    @classmethod
    async def get_history_curve_data(
        cls,
        db: AsyncSession,
        data_sub: str,
        field: str,
        start_t: int,
        end_t: int,
        limit: int = 50000,
        src_param: str | None = None,
    ) -> dict[str, Any]:
        from module_payload.service.payload_config_service import PayloadConfigService

        table_def = PayloadConfigService.get_telemetry_table_def(data_sub)
        name = field
        unit = ''
        for r in table_def.get('row', []):
            if r.get('id') == field:
                name = r.get('name', field)
                unit = r.get('unit', '')
                break
        raw_points = await PayloadTmArchiveDao.query_field_points(
            db, data_sub, field, start_t, end_t, limit, src_param=src_param or None
        )
        points = [{'t': ts, 'v': val} for ts, val in raw_points]
        return {
            'type': (data_sub or '').upper(),
            'field': field,
            'name': name,
            'unit': unit,
            'points': points,
        }

    @classmethod
    async def get_history_curve_data_batch(
        cls, db: AsyncSession, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for item in items:
            results.append(
                await cls.get_history_curve_data(
                    db,
                    item['type'],
                    item['field'],
                    item['start_t'],
                    item['end_t'],
                    item.get('limit', 50000),
                    src_param=item.get('src_param') or None,
                )
            )
        return results
