"""
遥测高帧率批处理：按 table_key 分缓存，各类型独立 0.5s 汇聚。

- 每种类型各自一条缓冲；刷写时该类型最新一帧 parse（表格）
- 缓冲内全部帧 parse_calc（曲线 + 归档）
- 归档 raw_hex = 完整复合帧 HEX（空格分隔），非仅有效载荷
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from module_payload.constants import CURVE_MAX_POINTS, DATA_KIND_TM, tm_parse_key
from module_payload import redis_keys as rk
from module_payload.service.payload_telemetry_archive_service import (
    PayloadTelemetryArchiveService,
    build_archive_event,
)

FLUSH_INTERVAL_S = 0.5
MAX_BATCH_PER_TYPE = 2000


@dataclass(slots=True)
class PreparedTmFrame:
    """校验拆帧后、尚未做 TeleMetry 字段解析的一帧。"""

    table_key: str  # Redis/归档存储键，总线为 BIU:FF / XL:FF
    name: str
    payload: bytes
    raw_frame: bytes
    src_param: str
    src_kind: str
    parser_id: str
    mgr: Any
    data_kind: str = DATA_KIND_TM
    ts_ms: int = 0
    parse_key: str = ''  # TeleMetryCfg 文件内本地 key；空则从 table_key 拆
    extra: dict[str, Any] = field(default_factory=dict)

    def cfg_parse_key(self) -> str:
        return self.parse_key or tm_parse_key(self.table_key)


def _now_ts() -> tuple[str, int]:
    now = datetime.now()
    ts = now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    ts_ms = int(now.timestamp() * 1000)
    return ts, ts_ms


def _normalize_points(points: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for fid, val in (points or {}).items():
        if not fid or val is None:
            continue
        try:
            out[str(fid)] = float(val)
        except (TypeError, ValueError):
            continue
    return out


def _write_curves_sync(redis_client: Any, table_key: str, points: dict[str, float], ts_ms: int) -> None:
    if not points:
        return
    tkey = (table_key or '').upper()
    pipe = redis_client.pipeline(transaction=False)
    for fid, val in points.items():
        lkey = rk.curve_latest_key(tkey, fid)
        pipe.zadd(lkey, {f'{ts_ms}|{val}': ts_ms})
        pipe.zremrangebyrank(lkey, 0, -(CURVE_MAX_POINTS + 1))
    pipe.execute()


def _write_latest_sync(
    redis_client: Any,
    frame: PreparedTmFrame,
    fields: list[dict[str, Any]],
    *,
    ts: str,
    ts_ms: int,
) -> dict[str, Any]:
    from module_payload.collectors.redis_sync import dumps_json

    tkey = frame.table_key
    payload: dict[str, Any] = {
        'type': tkey,
        'name': frame.name,
        'ts': ts,
        'dataId': ts_ms,
        'fields': fields,
        'dataKind': frame.data_kind,
        'dataSub': tkey,
        'srcKind': frame.src_kind,
        'srcParam': frame.src_param,
        'parserId': frame.parser_id,
    }
    payload.update(frame.extra or {})
    dumped = dumps_json(payload)
    redis_client.set(rk.telemetry_latest_key(tkey), dumped)
    redis_client.set(rk.telemetry_latest_ts_key(tkey), ts)
    return payload


def _ts_str_from_ms(ts_ms: int) -> str:
    try:
        return datetime.fromtimestamp(ts_ms / 1000.0).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    except Exception:
        return _now_ts()[0]


def process_prepared_sync(redis_client: Any, frames: list[PreparedTmFrame]) -> dict[str, Any] | None:
    """
    处理同一类型（同一 table_key）的一批帧：
    - 全部 parse_calc → 曲线 + 归档（raw_hex=完整复合帧）
    - 最新一帧 parse → Redis 表格
    """
    if not frames:
        return None

    latest: PreparedTmFrame | None = None
    for frame in frames:
        ts_ms = frame.ts_ms or _now_ts()[1]
        frame.ts_ms = ts_ms
        pkey = frame.cfg_parse_key()
        points = _normalize_points(frame.mgr.parse_calc(pkey, frame.payload))
        _write_curves_sync(redis_client, frame.table_key, points, ts_ms)
        PayloadTelemetryArchiveService.enqueue_sync(
            redis_client,
            build_archive_event(
                ts_ms=ts_ms,
                raw_frame=frame.raw_frame,
                points=points,
                data_sub=frame.table_key,
                src_param=frame.src_param,
                name=frame.name,
                src_kind=frame.src_kind,
                data_kind=frame.data_kind,
                parser_id=frame.parser_id,
            ),
        )
        latest = frame

    assert latest is not None
    fields = latest.mgr.parse(latest.cfg_parse_key(), latest.payload) or []
    use_ts_ms = latest.ts_ms or _now_ts()[1]
    return _write_latest_sync(
        redis_client,
        latest,
        fields,
        ts=_ts_str_from_ms(use_ts_ms),
        ts_ms=use_ts_ms,
    )


async def process_prepared_async(redis: Any, frames: list[PreparedTmFrame]) -> dict[str, Any] | None:
    """异步处理同一类型一批帧（FastAPI，通常 immediate 单帧）。"""
    if not frames:
        return None

    from module_payload.redis_store import set_telemetry

    latest: PreparedTmFrame | None = None
    for frame in frames:
        ts_ms = frame.ts_ms or _now_ts()[1]
        frame.ts_ms = ts_ms
        pkey = frame.cfg_parse_key()
        points = _normalize_points(frame.mgr.parse_calc(pkey, frame.payload))
        tkey = frame.table_key
        if points:
            pipe = redis.pipeline(transaction=False)
            for fid, val in points.items():
                lkey = rk.curve_latest_key(tkey, fid)
                pipe.zadd(lkey, {f'{ts_ms}|{val}': ts_ms})
                pipe.zremrangebyrank(lkey, 0, -(CURVE_MAX_POINTS + 1))
            await pipe.execute()
        await PayloadTelemetryArchiveService.enqueue(
            redis,
            build_archive_event(
                ts_ms=ts_ms,
                raw_frame=frame.raw_frame,
                points=points,
                data_sub=tkey,
                src_param=frame.src_param,
                name=frame.name,
                src_kind=frame.src_kind,
                data_kind=frame.data_kind,
                parser_id=frame.parser_id,
            ),
        )
        latest = frame

    assert latest is not None
    fields = latest.mgr.parse(latest.cfg_parse_key(), latest.payload) or []
    stored = await set_telemetry(
        redis,
        latest.table_key,
        fields,
        latest.name,
        src_kind=latest.src_kind,
        src_param=latest.src_param,
        parser_id=latest.parser_id,
        data_kind=latest.data_kind,
    )
    if latest.extra:
        from module_payload.collectors.redis_sync import dumps_json

        merged = dict(stored)
        merged.update(latest.extra)
        await redis.set(rk.telemetry_latest_key(latest.table_key), dumps_json(merged))
        stored = merged
    return stored


class TmIngestBatcher:
    """按 table_key 分缓存的 0.5s 批处理汇聚器（线程安全）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bufs: dict[str, list[PreparedTmFrame]] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._redis: Any = None

    @staticmethod
    def _buf_key(frame: PreparedTmFrame) -> str:
        return (frame.table_key or '').upper()

    def push(self, redis_client: Any, frame: PreparedTmFrame, *, immediate: bool = False) -> dict[str, Any] | None:
        if not frame.ts_ms:
            _, frame.ts_ms = _now_ts()
        if immediate:
            return process_prepared_sync(redis_client, [frame])

        key = self._buf_key(frame)
        with self._lock:
            self._redis = redis_client
            buf = self._bufs.setdefault(key, [])
            buf.append(frame)
            overflow = len(buf) >= MAX_BATCH_PER_TYPE
            self._arm_timer_unlocked(key)
            if overflow:
                batch = buf
                self._bufs[key] = []
                self._cancel_timer_unlocked(key)
            else:
                batch = None
        if batch:
            return process_prepared_sync(redis_client, batch)
        return None

    def flush(self, redis_client: Any | None = None, *, table_key: str | None = None) -> None:
        """刷写全部类型，或仅刷写指定 table_key。"""
        with self._lock:
            redis = redis_client or self._redis
            if table_key:
                key = table_key.upper()
                batch = self._bufs.pop(key, [])
                self._cancel_timer_unlocked(key)
                batches = [batch] if batch else []
            else:
                batches = list(self._bufs.values())
                self._bufs.clear()
                for key in list(self._timers):
                    self._cancel_timer_unlocked(key)
        if redis is None:
            return
        for batch in batches:
            if batch:
                process_prepared_sync(redis, batch)

    def _arm_timer_unlocked(self, key: str) -> None:
        if key in self._timers:
            return
        timer = threading.Timer(FLUSH_INTERVAL_S, self._on_timer, args=(key,))
        timer.daemon = True
        self._timers[key] = timer
        timer.start()

    def _cancel_timer_unlocked(self, key: str) -> None:
        timer = self._timers.pop(key, None)
        if timer is not None:
            timer.cancel()

    def _on_timer(self, key: str) -> None:
        with self._lock:
            batch = self._bufs.pop(key, [])
            self._timers.pop(key, None)
            redis = self._redis
        if batch and redis is not None:
            try:
                process_prepared_sync(redis, batch)
            except Exception:
                from utils.log_util import logger

                logger.exception('遥测批处理刷写失败 type=%s count=%s', key, len(batch))


_batcher = TmIngestBatcher()


def enqueue_prepared(
    redis_client: Any,
    frame: PreparedTmFrame,
    *,
    immediate: bool = False,
) -> dict[str, Any] | None:
    return _batcher.push(redis_client, frame, immediate=immediate)


def flush_pending(redis_client: Any | None = None, *, table_key: str | None = None) -> None:
    _batcher.flush(redis_client, table_key=table_key)
