"""文件回放会话引擎：解析、取帧、精确扫帧；写入独立 Hash。

一个 Engine 对应一条会话（当前文件）。切文件时 DEL 旧 Hash、取消进行中的精确扫描
（``_scan_gen`` 代次）。默认 ``force_estimate=True``：只定位首帧就 ready，避免大 recv
文本整文件精确拆帧卡住 API。
"""

from __future__ import annotations

import threading
from typing import Any

from module_payload import redis_keys as rk
from module_payload.fileplay import store
from module_payload.fileplay.detect import FileIndex, finalize_exact_index, frame_data_ts_ms, index_file
from module_payload.fileplay.parse_frame import parse_frame
from module_payload.fileplay.paths import resolve_play_path


class FilePlayEngine:
    """进程内单会话：切文件重置，不杀进程。"""

    def __init__(self, redis) -> None:
        self.redis = redis  # 同步客户端（worker / 进程内回退）
        self._lock = threading.RLock()
        self._idx: FileIndex | None = None  # 当前文件拆帧索引
        self._path_hash = ''  # 与 Redis Hash 名对应
        self._scan_thread: threading.Thread | None = None
        self._scan_gen = 0  # 每次 parse +1；旧扫描线程发现代次变化则放弃写回

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
        }

    def parse(self, table_type: str, path: str, *, force_estimate: bool = True) -> dict[str, Any]:
        """校验路径、先出第 1 帧（默认预估帧数），再后台精确扫帧。

        默认 ``force_estimate=True``：大 recv 日志若开局就精确拆帧，主进程等 meta
        会超过 60s 报解析超时。精确计数由 ``_scan_exact`` 覆盖同一 meta。
        """
        resolved = resolve_play_path(path)
        path_hash = rk.fileplay_path_hash(str(resolved))
        key = rk.fileplay_hash_key(path_hash)
        store.assert_not_live_tm_key(key)
        with self._lock:
            self._scan_gen += 1
            my_gen = self._scan_gen
            if self._path_hash and self._path_hash != path_hash:
                store.delete_session(self.redis, self._path_hash)
            store.delete_session(self.redis, path_hash)
            # 先写 parsing，API 轮询能区分「还在拆」和「子进程没起来」
            store.write_meta(
                self.redis,
                path_hash,
                {
                    'status': 'parsing',
                    'type': (table_type or '').upper(),
                    'path': str(resolved),
                    'frameCount': 0,
                    'frameCountExact': False,
                    'error': '',
                },
            )
            idx = index_file(resolved, table_type, force_estimate=force_estimate)
            self._idx = idx
            self._path_hash = path_hash
            if idx.error:
                meta = self._meta_from_idx(idx, 'error')
                store.write_meta(self.redis, path_hash, meta)
                return meta
            meta = self._meta_from_idx(idx, 'ready')
            store.write_meta(self.redis, path_hash, meta)
            try:
                frame = parse_frame(idx, 1)
                store.write_frame(self.redis, path_hash, 1, frame)
            except Exception as e:
                meta = self._meta_from_idx(idx, 'error')
                meta['error'] = str(e)
                store.write_meta(self.redis, path_hash, meta)
                return {**meta, 'pathHash': path_hash}
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
            return {**meta, 'frame': frame, 'pathHash': path_hash}

    def _scan_exact(self, gen: int, path_hash: str) -> None:
        """后台把预估 frameCount 改成精确值（同一 meta 字段 HSET）。

        切文件会增加 ``_scan_gen``；本线程发现代次变化则既不扫完也不写回，避免脏数据。
        """
        with self._lock:
            if gen != self._scan_gen or self._idx is None:
                return
            idx = self._idx
        finalize_exact_index(idx)
        with self._lock:
            if gen != self._scan_gen or self._idx is not idx:
                return
            meta = self._meta_from_idx(idx, 'ready')
            store.write_meta(self.redis, path_hash, meta)

    def ensure_frame(self, path_hash: str, index: int) -> dict[str, Any] | None:
        """若未解析则当场解析并写入 Hash。

        精确扫描未完成时 ``idx.frames`` 可能只有首帧，``index`` 超出则返回 None
        （前端提示「该帧尚未解析完成」）。
        """
        cached = store.read_frame(self.redis, path_hash, index)
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
            store.write_frame(self.redis, path_hash, index, frame)
            return frame

    def meta(self, path_hash: str) -> dict[str, Any] | None:
        """读 Hash.meta；不存在返回 None。"""
        return store.read_meta(self.redis, path_hash)

    def curve_points(
        self,
        path_hash: str,
        field_ids: list[str],
        *,
        start_index: int = 1,
        end_index: int | None = None,
    ) -> dict[str, list[list[float | int]]]:
        """从已解析（不足则补解析）帧抽取字段序列。

        点列为 ``[[tsMs, 数值], ...]``。有文件名起始时间则用 start+(n-1)*1s，
        与表格数据时间一致；写入 Hash 子字段 ``c:{fieldId}`` 供曲线页轮询。
        """
        with self._lock:
            idx = self._idx
            if not idx or self._path_hash != path_hash:
                return {fid: [] for fid in field_ids}
            total = len(idx.frames) if idx.frame_count_exact else min(idx.frame_count, len(idx.frames))
            end = min(end_index or total, total)
            start = max(1, start_index)
            out: dict[str, list[list[float | int]]] = {fid: [] for fid in field_ids}
            for i in range(start, end + 1):
                snap = store.read_frame(self.redis, path_hash, i) or self.ensure_frame(path_hash, i)
                if not snap:
                    continue
                x = snap.get('tsMs') or frame_data_ts_ms(idx, i)
                if not x:
                    continue
                by_id = {str(r.get('id') or '').upper(): r for r in (snap.get('rows') or [])}
                for fid in field_ids:
                    row = by_id.get(str(fid).upper())
                    if not row:
                        continue
                    val = row.get('value', row.get('show', ''))
                    try:
                        y = float(val)
                    except (TypeError, ValueError):
                        continue
                    out[fid].append([x, y])
            key = rk.fileplay_hash_key(path_hash)
            for fid, pts in out.items():
                self.redis.hset(key, f'c:{fid}', store.dumps(pts))
            return out
