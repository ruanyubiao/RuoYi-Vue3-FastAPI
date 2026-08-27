"""遥测归档与遥控发送记录：Redis 队列 → MySQL 批量刷写。"""

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
from module_payload.constants import DATA_KIND_TM, infer_src_kind, should_archive_tm_mysql
from module_payload.dao.payload_tm_archive_dao import PayloadTmArchiveDao
from module_payload.entity.do.payload_tm_frame_do import PayloadTmFrame
from module_payload.entity.do.payload_tx_log_do import PayloadTxLog
from module_payload import redis_keys as rk
from module_payload.store.archive_queue import (
    bytes_to_raw_hex,
    build_archive_event,
    enqueue as enqueue_archive,
    enqueue_sync as enqueue_archive_sync,
)
from utils.log_util import logger

ARCHIVE_BATCH_SIZE = 50  # 遥测归档每批条数
ARCHIVE_FLUSH_INTERVAL_S = 0.5  # 未满批时最长等待（秒）
TX_BATCH_SIZE = 50  # 遥控发送记录每批条数


class PayloadTelemetryArchiveService:
    """后台 worker：BRPOP 归档队列、LPOP 发送队列，批量写入 MySQL。"""

    _worker_task: asyncio.Task | None = None  # 归档后台任务
    _stop_event: asyncio.Event | None = None  # 停止信号

    @classmethod
    def enqueue_sync(cls, redis_client: Any, event: dict[str, Any]) -> None:
        """符合条件的遥测事件同步 LPUSH 到 Redis 归档队列。"""
        enqueue_archive_sync(redis_client, event)

    @classmethod
    async def enqueue(cls, redis: aioredis.Redis, event: dict[str, Any]) -> None:
        """符合条件的遥测事件异步入 Redis 归档队列。"""
        await enqueue_archive(redis, event)

    @classmethod
    def enqueue_tx_sync(cls, redis_client: Any, event: dict[str, Any]) -> None:
        """遥控发送记录同步入 Redis tx 队列（不经过遥测过滤）。"""
        redis_client.lpush(rk.tx_queue_key(), json.dumps(event, ensure_ascii=False))

    @classmethod
    async def enqueue_tx(cls, redis: aioredis.Redis, event: dict[str, Any]) -> None:
        """遥控发送记录异步入 Redis tx 队列。"""
        await redis.lpush(rk.tx_queue_key(), json.dumps(event, ensure_ascii=False))

    @classmethod
    async def _requeue_tx_batch(cls, redis: aioredis.Redis, events: list[dict[str, Any]]) -> None:
        """刷写失败时按原顺序重入队（reversed + LPUSH ≈ 保持队头旧→新）。"""
        for ev in reversed(events):
            try:
                await cls.enqueue_tx(redis, ev)
            except Exception:
                logger.exception('遥控发送记录失败重入队丢弃 src=%s', ev.get('src_param'))
                break

    @classmethod
    def _raw_hex_from_event(cls, ev: dict[str, Any]) -> str:
        """队列事件 → 入库 HEX；兼容旧 base64 字段。"""
        raw_hex = (ev.get('raw_hex') or '').strip()
        if raw_hex:
            return raw_hex
        b64 = ev.get('raw_bin_b64')
        if b64:
            try:
                import base64

                return bytes_to_raw_hex(base64.b64decode(b64))
            except Exception:
                return ''
        return ''

    @classmethod
    async def _persist_batch(cls, db: AsyncSession, events: list[dict[str, Any]]) -> None:
        """将归档事件转为 PayloadTmFrame 并提交；跳过不应入库的源。"""
        frame_rows: list[PayloadTmFrame] = []
        for ev in events:
            src_param = ev.get('src_param') or ''
            src_kind = ev.get('src_kind') or infer_src_kind(src_param, fallback='')
            parser_id = ev.get('parser_id')
            if not should_archive_tm_mysql(src_kind, src_param, parser_id):
                continue
            data_sub = (ev.get('data_sub') or '').upper()
            points = ev.get('points') or {}
            if not isinstance(points, dict):
                points = {}
            # 兼容旧事件：从 numeric_fields / parsed_json.fields 回填
            if not points:
                for nf in ev.get('numeric_fields') or []:
                    fid = nf.get('field_id')
                    if fid is None:
                        continue
                    try:
                        points[str(fid)] = float(nf['value_num'])
                    except (KeyError, TypeError, ValueError):
                        continue
            if not points:
                fields = (ev.get('parsed_json') or {}).get('fields') or []
                from module_payload.parsers.tm_field_util import curve_numeric

                for row in fields:
                    fid = row.get('id')
                    if not fid:
                        continue
                    val = curve_numeric(row)
                    if val is None:
                        continue
                    points[str(fid)] = val

            frame = PayloadTmFrame(
                data_kind=ev.get('data_kind') or DATA_KIND_TM,
                data_sub=data_sub,
                src_kind=src_kind,
                src_param=src_param,
                parser_id=ev.get('parser_id'),
                ts_ms=int(ev['ts_ms']),
                raw_hex=cls._raw_hex_from_event(ev),
                points_json=points,
                parsed_json=ev.get('parsed_json') or {},
                field_count=int(ev.get('field_count') or len(points)),
                cfg_version=ev.get('cfg_version'),
                created_at=datetime.now(),
            )
            frame_rows.append(frame)
        db.add_all(frame_rows)
        await db.commit()

    @classmethod
    async def flush_events(cls, events: list[dict[str, Any]]) -> None:
        """开独立 DB session 批量写遥测归档；失败回滚并上抛。"""
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
        """批量写遥控发送记录到 payload_tx_log。"""
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
        """从 Redis tx 队列最多弹出 TX_BATCH_SIZE 条。"""
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
        """循环：BRPOP 遥测归档 + 排空 tx 队列，按批量/间隔刷 MySQL。"""
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
                logger.warning('遥测归档队列 Redis 连接异常，稍后重试: %s', exc)
                await asyncio.sleep(2)
            except Exception:
                logger.exception('遥测归档队列读取失败')
                await asyncio.sleep(1)

            try:
                tx_batch = await cls._drain_tx_queue(redis)
                if tx_batch:
                    try:
                        await cls.flush_tx_events(tx_batch)
                    except Exception:
                        logger.exception('遥控发送队列刷写失败 count=%s', len(tx_batch))
                        await cls._requeue_tx_batch(redis, tx_batch)
            except Exception:
                logger.exception('遥控发送队列读取失败')

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
        """启动归档 worker（幂等）；FastAPI 生命周期调用。"""
        if cls._worker_task is not None:
            return
        cls._stop_event = asyncio.Event()
        cls._worker_task = asyncio.create_task(cls._worker_loop(redis))
        logger.info('遥测归档 worker 已启动 db=%s', DataBaseConfig.db_type)

    @classmethod
    async def stop_worker(cls) -> None:
        """停止归档 worker 并取消任务。"""
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
        """从 MySQL 查历史曲线点（含字段名/单位）。"""
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
        """批量查多条历史曲线。"""
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
