"""文件回放会话引擎：解析、取帧、精确扫帧；写入独立 Hash。

一个 Engine 绑定一个 pathHash。force 时只 DEL 自己的 Hash。默认
``force_estimate=True``：只定位首帧就 ready，精确计数由后台扫描覆盖。
"""

from __future__ import annotations

import threading
import time
from typing import Any

from module_payload import redis_keys as rk
from module_payload.fileplay import store
from module_payload.fileplay.detect import FileIndex, finalize_exact_index, frame_data_ts_ms, index_file
from module_payload.fileplay.parse_frame import parse_frame
from module_payload.fileplay.paths import resolve_play_path


# 与后台补帧一批的长度相同。跳转只插这 64 帧，不另定长度。
PRIORITY_BATCH = 64


def priority_block(index: int, total: int, batch: int = PRIORITY_BATCH) -> tuple[int, int] | None:
    """跳转帧所在的一批（1-based，按 batch 对齐）。60004、总帧足够时为 59969–60032。"""
    n = int(index or 0)
    count = int(total or 0)
    size = int(batch or 0)
    if n < 1 or count < 1 or size < 1 or n > count:
        return None
    start = ((n - 1) // size) * size + 1
    end = min(start + size - 1, count)
    return start, end


def priority_order(index: int, start: int, end: int) -> list[int]:
    """目标帧先解，同批其余帧按序号跟在后面。"""
    n = int(index)
    return [n] + [i for i in range(int(start), int(end) + 1) if i != n]


def parse_force(value: Any) -> bool:
    """仅弹窗确认后的 force=1 / true 才算强制重解析。"""
    if value is True or value == 1:
        return True
    if isinstance(value, str) and value.strip().lower() in ('1', 'true', 'yes'):
        return True
    return False


class FilePlayEngine:
    """单进程单文件：history / curve 各用各的 Redis，不删其它 pathHash。"""

    def __init__(self, redis, channel: str = 'history') -> None:
        self.redis = redis  # 同步客户端（worker / 进程内回退）
        self.channel = rk.fileplay_channel(channel)
        self._lock = threading.RLock()
        self._idx: FileIndex | None = None  # 当前文件拆帧索引
        self._path_hash = ''  # 与 Redis Hash 名对应
        self._scan_thread: threading.Thread | None = None
        self._scan_gen = 0  # 每次 parse +1；旧扫描线程发现代次变化则放弃写回
        self._parse_id = ''  # 主进程等 meta.parseId 判断子进程是否已接到命令
        self._jump_index = 0  # 最新跳转帧；0 表示没有插队。下一批补帧先解它所在的 64 帧

    def index_exact(self) -> bool:
        """精确帧数已固定（只点名条目，不等于遥测已全部解码）。"""
        return bool(self._idx and self._idx.frame_count_exact)

    def all_frames_parsed(self) -> bool:
        """history：每一帧都已写入 Redis。curve：万帧压缩块已覆盖全部精确帧。"""
        if not self.index_exact() or not self._path_hash:
            return False
        total = int(self._idx.frame_count or 0)
        if total <= 0:
            return False
        if self.channel == 'curve':
            return store.curve_all_chunks_ready(self.redis, self._path_hash, total, channel=self.channel)
        return store.stored_frame_count(self.redis, self._path_hash, channel=self.channel) >= total

    def _meta_from_idx(self, idx: FileIndex, status: str, *, path_hash: str = '') -> dict[str, Any]:
        """Hash.meta JSON：前端滑块用 frameCount / frameCountExact。parsedDone 仅表示帧已全部解码。"""
        h = path_hash or self._path_hash
        prev = store.read_meta(self.redis, h, channel=self.channel) or {} if h else {}
        exact = bool(idx.frame_count_exact)
        done = bool(prev.get('parsedDone'))
        if exact and self.channel != 'curve' and h:
            total = int(idx.frame_count or 0)
            if total > 0 and store.stored_frame_count(self.redis, h, channel=self.channel) >= total:
                done = True
        try:
            started = int(prev.get('startedAt') or time.time())
        except (TypeError, ValueError):
            started = int(time.time())
        meta = {
            'frameCount': idx.frame_count,
            'frameCountExact': exact,
            'parsedDone': done,
            'startedAt': started,
            'type': idx.table_type,
            'path': idx.path,
            'status': status,
            'kind': idx.kind,
            'hasTimestamp': bool(idx.start_ts_ms or idx.has_timestamp),
            'startTsMs': int(idx.start_ts_ms or 0),
            'error': idx.error or '',
            'parseId': self._parse_id,
        }
        if prev.get('jumpFailedIndex'):
            meta['jumpFailedIndex'] = prev.get('jumpFailedIndex')
            meta['jumpFailedError'] = prev.get('jumpFailedError') or ''
        return meta

    def _same_file_scanning(self, path_hash: str, table_type: str) -> bool:
        """同一文件、同一遥测表，精确扫描尚未结束。"""
        if not self._idx or self._path_hash != path_hash:
            return False
        if (self._idx.table_type or '').upper() != (table_type or '').upper():
            return False
        if self._idx.error or self._idx.frame_count_exact:
            return False
        return True

    def bind_existing(self, path_hash: str, path: str, table_type: str) -> bool:
        """worker 再拉起时重建内存索引，不删 Redis 缓存。只认帧、不解码遥测。"""
        h = (path_hash or '').strip().lower()
        if not path:
            return False
        resolved = resolve_play_path(path)
        table = (table_type or '').upper()
        if not h:
            h = rk.fileplay_path_hash(str(resolved))
        with self._lock:
            if self._idx and self._path_hash == h and not self._idx.error:
                return True
            idx = index_file(resolved, table, force_estimate=False)
            self._idx = idx
            self._path_hash = h
            return not bool(idx.error)

    def parse(
        self,
        table_type: str,
        path: str,
        *,
        force_estimate: bool = True,
        force: bool = False,
        parse_id: str = '',
    ) -> dict[str, Any]:
        """校验路径、先出已找到的帧（通常 1），再后台精确扫帧。

        默认 ``force_estimate=True``：大 recv 日志若开局就精确拆帧，主进程等 meta
        会超过 60s 报解析超时。精确计数由 ``_scan_exact`` 覆盖同一 meta。
        同一文件扫描中或已完成再次 parse 直接返回；``force`` 除外。
        不删除其它 pathHash 的缓存。
        """
        resolved = resolve_play_path(path)
        path_hash = rk.fileplay_path_hash(str(resolved))
        key = rk.fileplay_hash_key(path_hash, self.channel)
        store.assert_not_live_tm_key(key)
        table = (table_type or '').upper()
        with self._lock:
            if not force and self._same_file_scanning(path_hash, table):
                status = 'ready' if self._idx.frame_count else 'parsing'
                meta = self._meta_from_idx(self._idx, status)
                frame = None
                if self.channel != 'curve' and self._idx.frame_count:
                    frame = store.read_frame(self.redis, path_hash, 1, channel=self.channel)
                    if frame is None:
                        try:
                            frame = parse_frame(self._idx, 1)
                        except Exception:
                            frame = None
                return {**meta, 'frame': frame, 'pathHash': path_hash, 'channel': self.channel, 'alreadyParsing': True}
            self._scan_gen += 1
            my_gen = self._scan_gen
            self._parse_id = str(parse_id or '')
            self._jump_index = 0
            store.delete_session(self.redis, path_hash, channel=self.channel)
            # 先写 parsing，API 轮询能区分「还在拆」和「子进程没起来」
            store.write_meta(
                self.redis,
                path_hash,
                {
                    'status': 'parsing',
                    'type': table,
                    'path': str(resolved),
                    'frameCount': 0,
                    'frameCountExact': False,
                    'parsedDone': False,
                    'startedAt': int(time.time()),
                    'error': '',
                    'parseId': self._parse_id,
                },
                channel=self.channel,
            )
            idx = index_file(resolved, table, force_estimate=force_estimate)
            self._idx = idx
            self._path_hash = path_hash
            if idx.error:
                meta = self._meta_from_idx(idx, 'error')
                store.write_meta(self.redis, path_hash, meta, channel=self.channel)
                return {**meta, 'pathHash': path_hash, 'channel': self.channel}
            meta = self._meta_from_idx(idx, 'ready')
            store.write_meta(self.redis, path_hash, meta, channel=self.channel)
            frame = None
            try:
                frame = parse_frame(idx, 1)
            except Exception as e:
                meta = self._meta_from_idx(idx, 'error')
                meta['error'] = str(e)
                store.write_meta(self.redis, path_hash, meta, channel=self.channel)
                return {**meta, 'pathHash': path_hash, 'channel': self.channel}
            # 曲线频道只拆帧索引，点列按字段写到独立 Hash，不落表格快照
            if self.channel != 'curve' and frame is not None:
                store.write_frame(self.redis, path_hash, 1, frame, channel=self.channel)
            if not idx.frame_count_exact:
                t = threading.Thread(
                    target=self._scan_exact,
                    args=(my_gen, path_hash),
                    name='fileplay-exact-scan',
                    daemon=True,
                )
                self._scan_thread = t
                t.start()
            elif self.channel != 'curve':
                t = threading.Thread(
                    target=self._fill_all_frames,
                    args=(my_gen, path_hash),
                    name='fileplay-fill-frames',
                    daemon=True,
                )
                self._scan_thread = t
                t.start()
            return {**meta, 'frame': frame, 'pathHash': path_hash, 'channel': self.channel}

    def _scan_exact(self, gen: int, path_hash: str) -> None:
        """后台把已找到的 frameCount 扫成精确值（同一 meta 字段）。

        扫描中持续覆盖已找到的帧数；force 重解析会增加 ``_scan_gen``，旧线程不再写回。
        """
        with self._lock:
            if gen != self._scan_gen or self._idx is None:
                return
            idx = self._idx

        def progress(_idx) -> None:
            with self._lock:
                if gen != self._scan_gen or self._idx is not idx:
                    return
                store.write_meta(
                    self.redis, path_hash, self._meta_from_idx(self._idx, 'ready'), channel=self.channel
                )

        def should_stop() -> bool:
            return gen != self._scan_gen

        finalize_exact_index(idx, on_progress=progress, should_stop=should_stop)
        with self._lock:
            if gen != self._scan_gen or self._idx is not idx:
                return
            store.write_meta(
                self.redis, path_hash, self._meta_from_idx(self._idx, 'ready', path_hash=path_hash), channel=self.channel
            )
        if self.channel != 'curve':
            self._fill_all_frames(gen, path_hash)

    def request_jump(self, path_hash: str, index: int) -> None:
        """记下最新跳转。已经开始的那一批照旧做完，下一批再插队。连续跳转只保留最后一次。"""
        h = (path_hash or '').strip().lower()
        n = int(index or 0)
        with self._lock:
            if self._path_hash and h and self._path_hash != h:
                return
            if n < 1:
                return
            self._jump_index = n
            self._write_jump_failed(h or self._path_hash, 0, '')

    def _write_jump_failed(self, path_hash: str, index: int, error: str) -> None:
        """目标帧解析失败时写入 meta，供取帧接口停止等待。index 为 0 则清掉。"""
        h = (path_hash or '').strip().lower()
        if not h:
            return
        meta = store.read_meta(self.redis, h, channel=self.channel) or {}
        if index < 1:
            if not meta.get('jumpFailedIndex') and not meta.get('jumpFailedError'):
                return
            meta.pop('jumpFailedIndex', None)
            meta.pop('jumpFailedError', None)
        else:
            meta['jumpFailedIndex'] = int(index)
            meta['jumpFailedError'] = error or '该帧解析失败'
        store.write_meta(self.redis, h, meta, channel=self.channel)

    def _fill_indexes(self, path_hash: str, indexes: list[int], limit: int, *, jump: int) -> tuple[int, bool]:
        """按给定顺序解码，最多 limit 帧。返回 (写入数, 是否把列表走完)。"""
        wrote = 0
        for i in indexes:
            if wrote >= limit:
                return wrote, False
            if store.read_frame(self.redis, path_hash, i, channel=self.channel):
                continue
            if self.ensure_frame(path_hash, i):
                wrote += 1
                continue
            if i == jump:
                self._write_jump_failed(path_hash, i, '该帧解析失败')
        return wrote, True

    def fill_missing_frames(self, path_hash: str, limit: int = 32) -> int:
        """解码尚未写入的帧，每轮最多 limit 帧。返回本轮写入数。

        有跳转时，本轮先解目标帧所在的 64 帧（目标帧在前），这段做完再从第 1 帧继续。
        本轮开始时才读取跳转目标，所以正在进行的那一批不会被改道。
        """
        if self.channel == 'curve':
            return 0
        cap = max(0, int(limit or 0))
        if cap <= 0:
            return 0
        with self._lock:
            idx = self._idx
            if not idx or self._path_hash != path_hash or not idx.frame_count_exact:
                return 0
            total = len(idx.frames)
            jump = int(self._jump_index or 0)
        wrote = 0
        if jump:
            block = priority_block(jump, total)
            if block is None:
                with self._lock:
                    if self._jump_index == jump:
                        self._jump_index = 0
                self._write_jump_failed(path_hash, jump, '该帧不在文件中')
            else:
                start, end = block
                n, done = self._fill_indexes(path_hash, priority_order(jump, start, end), cap, jump=jump)
                wrote += n
                if not done:
                    return wrote
                with self._lock:
                    if self._jump_index == jump:
                        self._jump_index = 0
        if wrote >= cap:
            return wrote
        for i in range(1, total + 1):
            if wrote >= cap:
                break
            if store.read_frame(self.redis, path_hash, i, channel=self.channel):
                continue
            if self.ensure_frame(path_hash, i):
                wrote += 1
        return wrote

    def _fill_all_frames(self, gen: int, path_hash: str) -> None:
        """索引精确后把剩余帧全部解码进 Redis。"""
        while True:
            with self._lock:
                if gen != self._scan_gen:
                    return
            wrote = self.fill_missing_frames(path_hash, limit=64)
            if self.all_frames_parsed():
                with self._lock:
                    if gen != self._scan_gen or self._idx is None:
                        return
                    store.write_meta(
                        self.redis,
                        path_hash,
                        self._meta_from_idx(self._idx, 'ready', path_hash=path_hash),
                        channel=self.channel,
                    )
                return
            if wrote == 0:
                return

    def ensure_frame(self, path_hash: str, index: int) -> dict[str, Any] | None:
        """若未解析则当场解析并写入 Hash。

        精确扫描未完成时 ``idx.frames`` 可能只有首帧，``index`` 超出则返回 None
        （前端提示「该帧尚未解析完成」）。
        """
        cached = store.read_frame(self.redis, path_hash, index, channel=self.channel)
        if cached:
            return cached
        with self._lock:
            idx = self._idx
            if not idx or self._path_hash != path_hash:
                return None
            if index < 1:
                return None
            if index > len(idx.frames):
                return None
            try:
                frame = parse_frame(idx, index)
            except Exception:
                return None
            if self.channel != 'curve':
                store.write_frame(self.redis, path_hash, index, frame, channel=self.channel)
            return frame

    def meta(self, path_hash: str) -> dict[str, Any] | None:
        """读该文件会话 meta。"""
        return store.read_meta(self.redis, path_hash, channel=self.channel)

    def _snap_xy(self, snap: dict[str, Any], frame_index: int, idx: FileIndex) -> tuple[int, dict[str, float]] | None:
        x = snap.get('tsMs') or frame_data_ts_ms(idx, frame_index)
        if not x:
            return None
        xy: dict[str, float] = {}
        for row in snap.get('rows') or []:
            rid = str(row.get('id') or '').upper()
            if not rid:
                continue
            val = row.get('value', row.get('show', ''))
            try:
                xy[rid] = float(val)
            except (TypeError, ValueError):
                continue
        return int(x), xy

    def _chunk_ready(self, path_hash: str, chunk: int) -> bool:
        return store.curve_chunk_ready(self.redis, path_hash, chunk, channel=self.channel)

    def curve_points(
        self,
        path_hash: str,
        field_ids: list[str],
        *,
        chunks: list[int] | None = None,
        start_index: int = 0,
        end_index: int | None = None,
        job_id: str = '',
    ) -> dict[str, list[list[float | int]]]:
        """按万帧块抽点，写入 ``payload:play:file:curve:{hash}:data`` 的压缩块字段。

        块字段存在即已解析（整表字段打成一包）。
        """
        del job_id
        want = [store.curve_field(f) for f in field_ids if store.curve_field(f)]
        with self._lock:
            idx = self._idx
            if not idx or self._path_hash != path_hash:
                return {fid: [] for fid in want}
            gen = self._scan_gen
            total = len(idx.frames) if idx.frame_count_exact else min(idx.frame_count, len(idx.frames))
        body = {'chunks': chunks, 'startIndex': start_index, 'endIndex': end_index}
        need = store.curve_chunks_requested(body, total)
        beat_key = rk.fileplay_worker_status_key(path_hash, self.channel)
        last_beat = 0.0

        def _beat(op: str, index: int) -> None:
            nonlocal last_beat
            now = time.monotonic()
            if now - last_beat < 1.0:
                return
            try:
                self.redis.set(
                    beat_key,
                    store.dumps({'ts': time.time(), 'alive': True, 'op': op, 'index': index}),
                    ex=15,
                )
            except Exception:
                pass
            last_beat = now

        for chunk in need:
            with self._lock:
                if gen != self._scan_gen or self._path_hash != path_hash:
                    break
            if self._chunk_ready(path_hash, chunk):
                continue
            bounds = store.curve_chunk_frames(chunk, total)
            if not bounds:
                store.write_curve_chunk(self.redis, path_hash, chunk, [], channel=self.channel)
                continue
            start_f, end_f = bounds
            rows: list[tuple[int | float, dict[str, float]]] = []
            for i in range(start_f, end_f + 1):
                if i % 64 == 1:
                    with self._lock:
                        if gen != self._scan_gen or self._path_hash != path_hash:
                            rows = []
                            break
                try:
                    snap = parse_frame(idx, i)
                except Exception:
                    continue
                if not snap:
                    continue
                xy = self._snap_xy(snap, i, idx)
                if not xy:
                    continue
                rows.append(xy)
                _beat('curve', i)
            store.write_curve_chunk(self.redis, path_hash, chunk, rows, channel=self.channel)

        out: dict[str, list[list[float | int]]] = {}
        for fid in want:
            pts: list[list[float | int]] = []
            for chunk in need:
                raw = store.read_curve_chunk(self.redis, path_hash, fid, chunk, channel=self.channel)
                if isinstance(raw, list):
                    pts.extend(raw)
            out[fid] = pts
        if idx.frame_count_exact and store.curve_all_chunks_ready(
            self.redis, path_hash, int(idx.frame_count or 0), channel=self.channel
        ):
            meta = store.read_meta(self.redis, path_hash, channel=self.channel) or {}
            if str(meta.get('status') or '') != 'error' and not meta.get('parsedDone'):
                meta['parsedDone'] = True
                store.write_meta(self.redis, path_hash, meta, channel=self.channel)
        return out
