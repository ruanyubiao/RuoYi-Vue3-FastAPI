"""
遥测入库分三条互不阻塞的路径：

1. 表格 latest：独立线程每 0.5s ``parse`` 一帧写 Redis（前端轮询看不过更快）
2. 曲线：独立线程逐帧 ``parse_calc``，批量 pipeline 写 Redis，时间戳毫秒唯一
3. 原始流：采集线程只入队，``ConnectionTransferLogger`` 写盘线程落文件
MySQL ``payload_tm_frame`` 仅接收 CAN 遥测（含 HTTP 注入的 CAN 解释器）。
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from module_payload.constants import (
    CURVE_MAX_POINTS,
    DATA_KIND_TM,
    TM_FLUSH_INTERVAL_S,
    TM_LATEST_INTERVAL_S,
    should_archive_tm_mysql,
    tm_parse_key,
)
from module_payload import redis_keys as rk
from module_payload.store.archive_queue import build_archive_event, enqueue, enqueue_sync
from module_payload.store.jsonutil import dumps_json

FLUSH_INTERVAL_S = TM_FLUSH_INTERVAL_S
# 满这么多帧就交给曲线线程，避免采集侧缓冲无限涨
MAX_BATCH_PER_TYPE = 200
# 表格 latest 与曲线刷写同周期；不再在采集线程 parse
LATEST_INTERVAL_S = TM_LATEST_INTERVAL_S
# 单次 pipeline 命令上限，避免一帧字段极多时撑爆
_CURVE_PIPE_MAX_OPS = 800


@dataclass(slots=True)
class PreparedTmFrame:
    """校验拆帧后、尚未做 TeleMetry 字段解析的一帧。"""

    table_key: str  # Redis/归档存储键，总线为 BIU:FF / XL:FF
    name: str  # 遥测表显示名
    payload: bytes  # 交给 TeleMetryParser 的数据区
    raw_frame: bytes  # 含帧头的完整原始帧
    src_param: str  # 采集源（串口号 / CAN 通道等）
    src_kind: str  # serial / can / http / udp
    parser_id: str  # 解释器 id
    mgr: Any  # TeleMetryCfgManager
    data_kind: str = DATA_KIND_TM
    ts_ms: int = 0  # 曲线/归档毫秒时间戳；0 表示入队时再填
    parse_key: str = ''  # TeleMetryCfg 文件内本地 key；空则从 table_key 拆
    extra: dict[str, Any] | None = None  # 写入 latest 的附加字段（源/目的地址等）

    def cfg_parse_key(self) -> str:
        """TeleMetryCfg 内本地 key：有 parse_key 用它，否则从 table_key 拆。"""
        return self.parse_key or tm_parse_key(self.table_key)


def _now_ts() -> tuple[str, int]:
    """当前墙钟：显示字符串（毫秒）+ 曲线/归档用毫秒时间戳。"""
    now = datetime.now()
    ts = now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    ts_ms = int(now.timestamp() * 1000)
    return ts, ts_ms


def _normalize_points(points: dict[str, Any] | None) -> dict[str, float]:
    """曲线点清洗：丢掉空 id / 无法转 float 的值。"""
    if not points:
        return {}
    out: dict[str, float] = {}
    for fid, val in points.items():
        if not fid or val is None:
            continue
        try:
            out[str(fid)] = float(val)
        except (TypeError, ValueError):
            continue
    return out


def assign_unique_ts_ms(frames: list[PreparedTmFrame], last_ts: dict[str, int] | None = None) -> dict[str, int]:
    """同一毫秒内的帧依次 +1，保证 Redis ZSET score / 曲线横轴不撞车。"""
    clock: dict[str, int] = last_ts if last_ts is not None else {}
    now_ms = int(time.time() * 1000)
    for frame in frames:
        key = (frame.table_key or '').upper()
        wall = int(frame.ts_ms) if frame.ts_ms else now_ms
        prev = clock.get(key, 0)
        ts = wall if wall > prev else prev + 1
        frame.ts_ms = ts
        clock[key] = ts
    return clock


def _write_curves_batch(redis_client: Any, rows: list[tuple[str, dict[str, float], int]]) -> None:
    """一批曲线点一次（或分段）pipeline，各点 ts_ms 必须已经互不相同。"""
    if not rows:
        return
    prefix = f'{rk.PREFIX}:tm:'
    pipe = redis_client.pipeline(transaction=False)
    ops = 0
    for tkey, points, ts_ms in rows:
        if not points:
            continue
        base = f'{prefix}{tkey}:curve:'
        for fid, val in points.items():
            lkey = f'{base}{fid}'
            pipe.zadd(lkey, {f'{ts_ms}|{val}': ts_ms})
            pipe.zremrangebyrank(lkey, 0, -(CURVE_MAX_POINTS + 1))
            ops += 2
            if ops >= _CURVE_PIPE_MAX_OPS:
                pipe.execute()
                pipe = redis_client.pipeline(transaction=False)
                ops = 0
    if ops:
        pipe.execute()


def _write_curves_sync(redis_client: Any, table_key: str, points: dict[str, float], ts_ms: int) -> None:
    """单帧曲线点包装成一批写 Redis。"""
    _write_curves_batch(redis_client, [((table_key or '').upper(), points, ts_ms)])


def _write_latest_sync(
    redis_client: Any,
    frame: PreparedTmFrame,
    fields: list[dict[str, Any]],
    *,
    ts: str,
    ts_ms: int,
) -> dict[str, Any]:
    """表格 latest：pipeline 写 payload 与时间戳，给前端轮询。"""
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
    pipe = getattr(redis_client, 'pipeline', None)
    if callable(pipe):
        p = pipe(transaction=False)
        p.set(rk.telemetry_latest_key(tkey), dumped)
        p.set(rk.telemetry_latest_ts_key(tkey), ts)
        p.execute()
    else:
        redis_client.set(rk.telemetry_latest_key(tkey), dumped)
        redis_client.set(rk.telemetry_latest_ts_key(tkey), ts)
    return payload


def _ts_str_from_ms(ts_ms: int) -> str:
    """毫秒时间戳转表格显示字符串；异常则退回当前时间。"""
    try:
        return datetime.fromtimestamp(ts_ms / 1000.0).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    except Exception:
        return _now_ts()[0]


def _write_latest_from_frame(
    redis_client: Any,
    frame: PreparedTmFrame,
    *,
    ts_ms: int | None = None,
) -> dict[str, Any]:
    """对一帧做 TeleMetryParser.parse，再写 Redis latest。

    ``ts_ms`` 可传入队快照，避免曲线线程随后改写 ``frame.ts_ms`` 影响表格 dataId。
    """
    use_ms = int(ts_ms) if ts_ms else int(frame.ts_ms or 0)
    if not use_ms:
        _, use_ms = _now_ts()
    # TeleMetryParser：全量字段（表格展示）
    fields = frame.mgr.parse(frame.cfg_parse_key(), frame.payload) or []
    return _write_latest_sync(
        redis_client,
        frame,
        fields,
        ts=_ts_str_from_ms(use_ms),
        ts_ms=use_ms,
    )


def _collect_curve_and_archive_rows(
    frames: list[PreparedTmFrame],
) -> tuple[list[tuple[str, dict[str, float], int]], PreparedTmFrame, list[dict[str, Any]]]:
    """逐帧 parse_calc，得到曲线行与符合条件的归档事件；latest 为最后一帧。"""
    curve_rows: list[tuple[str, dict[str, float], int]] = []
    archive_events: list[dict[str, Any]] = []
    latest: PreparedTmFrame | None = None
    for frame in frames:
        pkey = frame.cfg_parse_key()
        points = _normalize_points(frame.mgr.parse_calc(pkey, frame.payload))
        tkey = (frame.table_key or '').upper()
        curve_rows.append((tkey, points, frame.ts_ms))
        if should_archive_tm_mysql(frame.src_kind, frame.src_param, frame.parser_id):
            archive_events.append(
                build_archive_event(
                    ts_ms=frame.ts_ms,
                    raw_frame=frame.raw_frame,
                    points=points,
                    data_sub=tkey,
                    src_param=frame.src_param,
                    name=frame.name,
                    src_kind=frame.src_kind,
                    data_kind=frame.data_kind,
                    parser_id=frame.parser_id,
                )
            )
        latest = frame
    assert latest is not None
    return curve_rows, latest, archive_events


def process_prepared_sync(
    redis_client: Any,
    frames: list[PreparedTmFrame],
    *,
    write_latest: bool = False,
    ts_clock: dict[str, int] | None = None,
) -> dict[str, Any] | None:
    """曲线逐帧 parse_calc + 批量 Redis；仅 CAN 遥测入 MySQL 归档队。"""
    if not frames:
        return None

    assign_unique_ts_ms(frames, ts_clock)
    curve_rows, latest, archive_events = _collect_curve_and_archive_rows(frames)
    for event in archive_events:
        enqueue_sync(redis_client, event)

    _write_curves_batch(redis_client, curve_rows)
    if not write_latest:
        return None
    return _write_latest_from_frame(redis_client, latest)


async def process_prepared_async(redis: Any, frames: list[PreparedTmFrame]) -> dict[str, Any] | None:
    """异步处理同一类型一批帧（FastAPI，通常 immediate 单帧）。"""
    if not frames:
        return None

    from module_payload.redis_store import set_telemetry

    assign_unique_ts_ms(frames)
    curve_rows, latest, archive_events = _collect_curve_and_archive_rows(frames)
    for event in archive_events:
        await enqueue(redis, event)

    if curve_rows:
        pipe = redis.pipeline(transaction=False)
        ops = 0
        for tkey, points, ts_ms in curve_rows:
            if not points:
                continue
            for fid, val in points.items():
                lkey = rk.curve_latest_key(tkey, fid)
                pipe.zadd(lkey, {f'{ts_ms}|{val}': ts_ms})
                pipe.zremrangebyrank(lkey, 0, -(CURVE_MAX_POINTS + 1))
                ops += 2
                if ops >= _CURVE_PIPE_MAX_OPS:
                    await pipe.execute()
                    pipe = redis.pipeline(transaction=False)
                    ops = 0
        if ops:
            await pipe.execute()

    # TeleMetryParser：表格 latest 全量字段
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
        merged = dict(stored)
        merged.update(latest.extra)
        await redis.set(rk.telemetry_latest_key(latest.table_key), dumps_json(merged))
        stored = merged
    return stored


class TmIngestBatcher:
    """采集线程只入队；曲线线程 parse_calc+Redis；latest 线程 0.5s parse 一帧。"""

    def __init__(self) -> None:
        """采集侧缓冲 + 曲线/latest 两个后台线程。"""
        self._lock = threading.Lock()  # 保护 _bufs / _last_frame / _redis
        self._bufs: dict[str, list[PreparedTmFrame]] = {}  # table_key → 待刷曲线帧
        self._timers: dict[str, threading.Timer] = {}  # 按类型 0.5s 刷写定时器
        self._redis: Any = None  # 最近一次 push 的 Redis 客户端
        self._last_frame: dict[str, PreparedTmFrame] = {}  # 各类型最新一帧（表格 latest）
        self._latest_snap: dict[str, tuple[int, int]] = {}  # key → (id(frame), ts_ms 入队快照)
        self._latest_written_id: dict[str, int] = {}  # 已写入 latest 的 frame id，防曲线改 ts 后假 changed
        self._curve_ts_clock: dict[str, int] = {}  # 曲线毫秒唯一时钟
        self._flush_q: queue.SimpleQueue = queue.SimpleQueue()  # 曲线线程入队
        self._flush_thread: threading.Thread | None = None
        self._flush_thread_lock = threading.Lock()
        self._latest_thread: threading.Thread | None = None
        self._latest_thread_lock = threading.Lock()
        self._latest_stop = threading.Event()
        self._curve_io_lock = threading.Lock()  # 曲线 Redis 写互斥（immediate 与刷写线程）

    @staticmethod
    def _buf_key(frame: PreparedTmFrame) -> str:
        """缓冲分组键：table_key 大写。"""
        return (frame.table_key or '').upper()

    def _ensure_flush_worker(self) -> None:
        """懒启动曲线刷写守护线程。"""
        with self._flush_thread_lock:
            if self._flush_thread is not None and self._flush_thread.is_alive():
                return
            t = threading.Thread(target=self._flush_loop, name='tm-curve-flush', daemon=True)
            t.start()
            self._flush_thread = t

    def _flush_loop(self) -> None:
        """曲线线程：出队后 parse_calc + Redis，不写表格 latest。"""
        while True:
            redis, batch, key = self._flush_q.get()
            if not batch or redis is None:
                continue
            try:
                with self._curve_io_lock:
                    process_prepared_sync(redis, batch, write_latest=False, ts_clock=self._curve_ts_clock)
            except Exception:
                from utils.log_util import logger

                logger.exception('遥测批处理刷写失败 type=%s count=%s', key, len(batch))

    def _ensure_latest_worker(self) -> None:
        """懒启动表格 latest 守护线程（0.5s 一拍）。"""
        with self._latest_thread_lock:
            if self._latest_thread is not None and self._latest_thread.is_alive():
                return
            self._latest_stop.clear()
            t = threading.Thread(target=self._latest_loop, name='tm-table-latest', daemon=True)
            t.start()
            self._latest_thread = t

    def _latest_loop(self) -> None:
        """每 0.5s 对各类型最新一帧做 parse 写 Redis latest。

        同一帧对象只写一次：曲线线程的 ``assign_unique_ts_ms`` 会就地改 ``ts_ms``，
        若重复写会导致 dataId 漂移、前端误判「又来了一帧」。
        """
        while not self._latest_stop.wait(LATEST_INTERVAL_S):
            with self._lock:
                redis = self._redis
                snaps = [
                    (key, frame, self._latest_snap.get(key))
                    for key, frame in self._last_frame.items()
                ]
            if redis is None:
                continue
            for key, frame, snap in snaps:
                if snap is None:
                    continue
                fid, ts_ms = snap
                if self._latest_written_id.get(key) == fid:
                    continue
                try:
                    _write_latest_from_frame(redis, frame, ts_ms=ts_ms)
                    self._latest_written_id[key] = fid
                except Exception:
                    from utils.log_util import logger

                    logger.exception('遥测表格 latest 写入失败 type=%s', key)

    def _submit_flush(self, redis: Any, batch: list[PreparedTmFrame], key: str) -> None:
        """把一批帧交给曲线线程（采集侧不 parse）。"""
        if not batch or redis is None:
            return
        self._ensure_flush_worker()
        self._flush_q.put((redis, batch, key))

    def push(self, redis_client: Any, frame: PreparedTmFrame, *, immediate: bool = False) -> dict[str, Any] | None:
        """采集入队：默认只缓冲；满批或定时再交给曲线线程。immediate 则本帧同步处理。"""
        if not frame.ts_ms:
            frame.ts_ms = int(time.time() * 1000)
        if immediate:
            with self._curve_io_lock:
                return process_prepared_sync(
                    redis_client,
                    [frame],
                    write_latest=True,
                    ts_clock=self._curve_ts_clock,
                )

        key = self._buf_key(frame)
        overflow: list[PreparedTmFrame] | None = None
        with self._lock:
            self._redis = redis_client
            self._last_frame[key] = frame
            self._latest_snap[key] = (id(frame), int(frame.ts_ms))
            buf = self._bufs.setdefault(key, [])
            buf.append(frame)
            if len(buf) >= MAX_BATCH_PER_TYPE:
                overflow = buf
                self._bufs[key] = []
                self._cancel_timer_unlocked(key)
            else:
                self._arm_timer_unlocked(key)
        self._ensure_flush_worker()
        self._ensure_latest_worker()
        if overflow:
            self._submit_flush(redis_client, overflow, key)
        return None

    def push_many(
        self,
        redis_client: Any,
        frames: list[PreparedTmFrame],
        *,
        immediate: bool = False,
    ) -> dict[str, Any] | None:
        """多帧入队，规则同 push。"""
        if not frames:
            return None
        now_ms = int(time.time() * 1000)
        for frame in frames:
            if not frame.ts_ms:
                frame.ts_ms = now_ms
        if immediate:
            with self._curve_io_lock:
                return process_prepared_sync(
                    redis_client,
                    frames,
                    write_latest=True,
                    ts_clock=self._curve_ts_clock,
                )
        overflows: list[tuple[str, list[PreparedTmFrame]]] = []
        with self._lock:
            self._redis = redis_client
            for frame in frames:
                key = self._buf_key(frame)
                self._last_frame[key] = frame
                self._latest_snap[key] = (id(frame), int(frame.ts_ms))
                buf = self._bufs.setdefault(key, [])
                buf.append(frame)
                if len(buf) >= MAX_BATCH_PER_TYPE:
                    overflows.append((key, buf))
                    self._bufs[key] = []
                    self._cancel_timer_unlocked(key)
                else:
                    self._arm_timer_unlocked(key)
        self._ensure_flush_worker()
        self._ensure_latest_worker()
        for key, batch in overflows:
            self._submit_flush(redis_client, batch, key)
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
        with self._curve_io_lock:
            for batch in batches:
                if batch:
                    process_prepared_sync(redis, batch, write_latest=False, ts_clock=self._curve_ts_clock)

    def _arm_timer_unlocked(self, key: str) -> None:
        """为该类型启动一次 0.5s 刷写定时器（已有则不重置）。"""
        if key in self._timers:
            return
        timer = threading.Timer(FLUSH_INTERVAL_S, self._on_timer, args=(key,))
        timer.daemon = True
        self._timers[key] = timer
        timer.start()

    def _cancel_timer_unlocked(self, key: str) -> None:
        """取消该类型的刷写定时器。"""
        timer = self._timers.pop(key, None)
        if timer is not None:
            timer.cancel()

    def _on_timer(self, key: str) -> None:
        """定时到期：取出该类型缓冲交给曲线线程。"""
        with self._lock:
            batch = self._bufs.pop(key, [])
            self._timers.pop(key, None)
            redis = self._redis
        if batch and redis is not None:
            self._submit_flush(redis, batch, key)


_batcher = TmIngestBatcher()


def enqueue_prepared(
    redis_client: Any,
    frame: PreparedTmFrame,
    *,
    immediate: bool = False,
) -> dict[str, Any] | None:
    """单帧入批处理队列（采集热路径 Redis 入队）。"""
    return _batcher.push(redis_client, frame, immediate=immediate)


def enqueue_prepared_many(
    redis_client: Any,
    frames: list[PreparedTmFrame],
    *,
    immediate: bool = False,
) -> dict[str, Any] | None:
    """多帧入批处理队列。"""
    return _batcher.push_many(redis_client, frames, immediate=immediate)


def flush_pending(redis_client: Any | None = None, *, table_key: str | None = None) -> None:
    """强制刷写待处理缓冲（关采集 / 测试收尾）。"""
    _batcher.flush(redis_client, table_key=table_key)
