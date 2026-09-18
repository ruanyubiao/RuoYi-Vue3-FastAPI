"""文件回放会话引擎：解析、取帧、精确扫帧；写入独立 Hash。

一个 Engine 对应一条会话（当前文件）。切文件时 DEL 旧 Hash、取消进行中的精确扫描
（``_scan_gen`` 代次）。同一文件扫描中重复 parse 直接返回。默认 ``force_estimate=True``：
只定位首帧就 ready（frameCount=已找到数量），避免大 recv 整文件精确拆帧卡住 API。
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


def parse_force(value: Any) -> bool:
    """仅弹窗确认后的 force=1 / true 才算强制重解析。"""
    if value is True or value == 1:
        return True
    if isinstance(value, str) and value.strip().lower() in ('1', 'true', 'yes'):
        return True
    return False


class FilePlayEngine:
    """单频道单会话：history / curve 各用各的 Redis，切文件只删本频道。"""

    def __init__(self, redis, channel: str = 'history') -> None:
        self.redis = redis  # 同步客户端（worker / 进程内回退）
        self.channel = rk.fileplay_channel(channel)
        self._lock = threading.RLock()
        self._idx: FileIndex | None = None  # 当前文件拆帧索引
        self._path_hash = ''  # 与 Redis Hash 名对应
        self._scan_thread: threading.Thread | None = None
        self._scan_gen = 0  # 每次 parse +1；旧扫描线程发现代次变化则放弃写回
        self._parse_id = ''  # 主进程等 meta.parseId 判断子进程是否已接到命令

    def _meta_from_idx(self, idx: FileIndex, status: str) -> dict[str, Any]:
        """Hash.meta JSON：前端滑块用 frameCount / frameCountExact。"""
        return {
            'frameCount': idx.frame_count,
            'frameCountExact': bool(idx.frame_count_exact),
            'type': idx.table_type,
            'path': idx.path,
            'status': status,
            'kind': idx.kind,
            'hasTimestamp': bool(idx.start_ts_ms or idx.has_timestamp),
            'startTsMs': int(idx.start_ts_ms or 0),
            'error': idx.error or '',
            'parseId': self._parse_id,
        }

    def _same_file_scanning(self, path_hash: str, table_type: str) -> bool:
        """同一文件、同一遥测表，精确扫描尚未结束。"""
        if not self._idx or self._path_hash != path_hash:
            return False
        if (self._idx.table_type or '').upper() != (table_type or '').upper():
            return False
        if self._idx.error or self._idx.frame_count_exact:
            return False
        return True

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
        同一文件扫描中再次 parse 直接返回，不删会话、不取消后台扫描；``force`` 除外。
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
            if self._path_hash and self._path_hash != path_hash:
                store.delete_session(self.redis, self._path_hash, channel=self.channel)
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
                # 预估会话：后台扫完全部帧后覆盖 meta.frameCount
                t = threading.Thread(
                    target=self._scan_exact,
                    args=(my_gen, path_hash),
                    name='fileplay-exact-scan',
                    daemon=True,
                )
                self._scan_thread = t
                t.start()
            return {**meta, 'frame': frame, 'pathHash': path_hash, 'channel': self.channel}

    def _scan_exact(self, gen: int, path_hash: str) -> None:
        """后台把已找到的 frameCount 扫成精确值（同一 meta 字段）。

        扫描中持续覆盖已找到的帧数；切文件会增加 ``_scan_gen``，旧线程不再写回。
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
        """读频道当前会话 meta；pathHash 对不上则 None。"""
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

    def _chunk_ready(self, path_hash: str, field_id: str, chunk: int) -> bool:
        return store.curve_chunk_ready(self.redis, path_hash, field_id, chunk, channel=self.channel)

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
        """按万点块抽点，写入 ``payload:fileplay:curve:{hash}:{id}`` 的块字段。

        块字段存在即已解析，不再缓存到进程内存。先写请求字段，再写同帧其它字段。
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
        beat_key = rk.fileplay_worker_status_key(self.channel)
        last_beat = 0.0
        parsed: dict[int, list[tuple[int, dict[str, float]]]] = {}

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
            if want and all(self._chunk_ready(path_hash, fid, chunk) for fid in want):
                continue
            bounds = store.curve_chunk_frames(chunk, total)
            if not bounds:
                for fid in want:
                    if not self._chunk_ready(path_hash, fid, chunk):
                        store.write_curve_chunk(self.redis, path_hash, fid, chunk, [], channel=self.channel)
                continue
            start_f, end_f = bounds
            rows: list[tuple[int, dict[str, float]]] = []
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
            parsed[chunk] = rows
            for fid in want:
                if self._chunk_ready(path_hash, fid, chunk):
                    continue
                pts = [[x, ymap[fid]] for x, ymap in rows if fid in ymap]
                store.write_curve_chunk(self.redis, path_hash, fid, chunk, pts, channel=self.channel)

        extras: set[str] = set()
        for rows in parsed.values():
            for _x, ymap in rows:
                extras.update(ymap)
        extras -= set(want)
        for fid in sorted(extras):
            for chunk, rows in parsed.items():
                if self._chunk_ready(path_hash, fid, chunk):
                    continue
                pts = [[x, ymap[fid]] for x, ymap in rows if fid in ymap]
                store.write_curve_chunk(self.redis, path_hash, fid, chunk, pts, channel=self.channel)

        out: dict[str, list[list[float | int]]] = {}
        for fid in want:
            pts: list[list[float | int]] = []
            for chunk in need:
                raw = store.read_curve_chunk(self.redis, path_hash, fid, chunk, channel=self.channel)
                if isinstance(raw, list):
                    pts.extend(raw)
            out[fid] = pts
        return out
