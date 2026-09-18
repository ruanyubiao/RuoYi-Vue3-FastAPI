"""历史文件上传 / 浏览 / 解析 / 取帧（独立 Redis，不写实时遥测）。

history / curve 各一个解析进程、一套 key。API 只 LPUSH 命令。
parse 立即返回；前端轮询 ``/file/status``。取帧未命中时最多等 FRAME_WAIT_S。
会话失效返回 sessionGone，不假装「尚未解析完成」。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from redis import asyncio as aioredis

from config.paths import get_upload_log_data_dir
from module_payload import redis_keys as rk
from module_payload.fileplay import store
from module_payload.fileplay.engine import parse_force
from module_payload.fileplay.manager import FilePlayManager
from module_payload.fileplay.paths import list_dir, locate_play_file, resolve_play_path


def _loads(text: str | None) -> Any:
    """Redis 字符串 → JSON；空/坏数据当 None。"""
    return store.loads(text)


def _safe_filename(name: str) -> str:
    """只取 basename，拒绝空名与 ``.`` / ``..``，避免上传路径穿越。"""
    base = Path(name or '').name
    if not base or base in ('.', '..'):
        raise ValueError('文件名无效')
    return base


class PayloadFilePlayService:
    """历史文件回放：上传到 log_data、浏览、解析子进程、取帧。"""

    FRAME_WAIT_S = 1.0  # 单帧补解析上限
    CURVE_WAIT_S = 60.0  # 等 job 标记后按序号 HMGET 点列

    @classmethod
    async def upload_chunk(
        cls,
        file: UploadFile,
        filename: str,
        chunk_index: int = 0,
        total_chunks: int = 1,
    ) -> dict[str, Any]:
        """分片写入 ``{UPLOAD_PATH}/log_data``，同名覆盖。

        多分片时先写 ``*.part``，最后一片到位再 replace 成正式文件。
        """
        name = _safe_filename(filename or file.filename or '')
        dest_dir = get_upload_log_data_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / name
        total = max(1, int(total_chunks or 1))
        index = max(0, int(chunk_index or 0))
        part = dest if total == 1 else dest.with_name(dest.name + '.part')
        mode = 'wb' if index == 0 else 'ab'
        with part.open(mode) as fp:
            while True:
                buf = await file.read(1024 * 1024)
                if not buf:
                    break
                fp.write(buf)
        done = index + 1 >= total
        if done and part != dest:
            dest.unlink(missing_ok=True)
            part.replace(dest)
        return {
            'path': str(dest if done else part),
            'filename': name,
            'chunkIndex': index,
            'totalChunks': total,
            'done': done,
        }

    @classmethod
    def browse(cls, root: str, rel: str = '') -> dict[str, Any]:
        """列出上传目录或本地日志（仅 ``_recv`` 文件可选）。"""
        return list_dir(root, rel)

    @classmethod
    def locate(cls, path: str) -> dict[str, Any]:
        """把已填路径定位到浏览目录；越界或不存在则 found=false。"""
        return locate_play_file(path)

    @classmethod
    def _status_payload(
        cls,
        table_type: str,
        resolved: Path,
        path_hash: str,
        meta: dict[str, Any],
        frame: Any = None,
    ) -> dict[str, Any]:
        """组装 parse/status 共用字段。"""
        status = str(meta.get('status') or 'parsing')
        frame_count = int(meta.get('frameCount') or 0)
        complete = bool(meta.get('frameCountExact'))
        has_data = frame_count > 0 or frame is not None
        ch = str(meta.get('channel') or '')
        out: dict[str, Any] = {
            'path': str(resolved),
            'pathHash': path_hash,
            'channel': ch,
            'status': status,
            'type': meta.get('type') or table_type,
            'frameCount': frame_count,
            'frameCountExact': complete,
            'hasData': has_data,
            'complete': complete,
            'hasTimestamp': bool(meta.get('hasTimestamp')),
            'startTsMs': int(meta.get('startTsMs') or 0),
            'kind': meta.get('kind') or '',
            'workerAlive': bool(meta.get('workerAlive')),
            'sessionGone': bool(meta.get('sessionGone')),
            'alreadyParsing': bool(meta.get('alreadyParsing')),
            'alreadyComplete': bool(meta.get('alreadyComplete')),
        }
        if status == 'error':
            out['error'] = meta.get('error') or '解析失败'
        if frame is not None:
            out['frame'] = frame
        return out

    @classmethod
    async def _worker_alive(cls, redis: aioredis.Redis, channel: str) -> bool:
        try:
            raw = await redis.get(rk.fileplay_worker_status_key(channel))
        except Exception:
            return False
        return bool(raw)

    @classmethod
    async def _channel_meta(cls, redis: aioredis.Redis, channel: str) -> dict[str, Any]:
        raw = await redis.get(rk.fileplay_meta_key(channel))
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode('utf-8', errors='ignore')
        return _loads(raw) or {}

    @classmethod
    async def parse(
        cls,
        redis: aioredis.Redis,
        table_type: str,
        path: str,
        channel: str = 'history',
        force: Any = 0,
    ) -> dict[str, Any]:
        """通知该频道解析进程拆帧；立即返回当前 status。

        同一文件（扫描中或已完成）无 force 不重复推 parse。force=1 仅来自确认弹窗。
        """
        ch = rk.fileplay_channel(channel)
        resolved = resolve_play_path(path)
        path_hash = rk.fileplay_path_hash(str(resolved))
        table = (table_type or '').upper()
        want_force = parse_force(force)
        meta = await cls._channel_meta(redis, ch)
        alive = await cls._worker_alive(redis, ch)
        same = (
            str(meta.get('pathHash') or '').strip().lower() == path_hash
            and str(meta.get('type') or '').upper() == table
        )
        complete = bool(meta.get('frameCountExact'))
        skip = (
            not want_force
            and same
            and alive
            and str(meta.get('status') or '') != 'error'
        )
        if not skip:
            FilePlayManager.instance(ch).parse(table, str(resolved), force=want_force)
            meta = await cls._channel_meta(redis, ch)
        frame = None
        if meta.get('status') == 'ready' or int(meta.get('frameCount') or 0) > 0:
            frame = _loads(
                await redis.hget(rk.fileplay_hash_key(path_hash, ch), store.frame_field(1))
            )
        meta = {
            **meta,
            'workerAlive': await cls._worker_alive(redis, ch),
            'sessionGone': False,
            'channel': ch,
            'alreadyParsing': skip and not complete,
            'alreadyComplete': skip and complete,
        }
        return cls._status_payload(table, resolved, path_hash, meta, frame)

    @classmethod
    async def get_status(
        cls,
        redis: aioredis.Redis,
        path: str = '',
        path_hash: str = '',
        channel: str = 'history',
    ) -> dict[str, Any]:
        """读该频道当前解析会话。优先 pathHash。"""
        ch = rk.fileplay_channel(channel)
        alive = await cls._worker_alive(redis, ch)
        h = (path_hash or '').strip().lower()
        if not h and path:
            resolved = resolve_play_path(path)
            h = rk.fileplay_path_hash(str(resolved))
        meta = await cls._channel_meta(redis, ch)
        current = str(meta.get('pathHash') or '').strip().lower()
        hash_mismatch = bool(h) and bool(current) and h != current
        if not meta or hash_mismatch:
            resolved = Path(str(meta.get('path') or path or ''))
            empty = {
                'status': 'parsing' if alive else 'idle',
                'channel': ch,
                'workerAlive': alive,
                # 进程还在时可能是切文件后 meta 尚未刷新，不要误报会话已失效
                'sessionGone': (not alive) and bool(h),
                'frameCount': 0,
                'frameCountExact': False,
                'path': str(resolved),
                'type': '',
            }
            return cls._status_payload('', resolved, h, empty)
        resolved = Path(str(meta.get('path') or path or ''))
        use_h = current or h
        frame = None
        if meta.get('status') == 'ready' or int(meta.get('frameCount') or 0) > 0:
            frame = _loads(await redis.hget(rk.fileplay_hash_key(use_h, ch), store.frame_field(1)))
        meta = {**meta, 'workerAlive': alive, 'sessionGone': False, 'channel': ch}
        if meta.get('status') == 'error':
            return cls._status_payload(str(meta.get('type') or ''), resolved, use_h, meta)
        return cls._status_payload(str(meta.get('type') or ''), resolved, use_h, meta, frame)

    @classmethod
    async def get_frame(
        cls,
        redis: aioredis.Redis,
        path: str = '',
        index: int = 1,
        path_hash: str = '',
        channel: str = 'history',
    ) -> dict[str, Any]:
        """取第 N 帧。会话失效时 sessionGone，不假装「尚未解析完成」。"""
        ch = rk.fileplay_channel(channel)
        alive = await cls._worker_alive(redis, ch)
        h = (path_hash or '').strip().lower()
        if not h:
            resolved = resolve_play_path(path)
            h = rk.fileplay_path_hash(str(resolved))
            resolved_s = str(resolved)
        else:
            resolved_s = path
        key = rk.fileplay_hash_key(h, ch)
        store.assert_not_live_tm_key(key)
        meta = await cls._channel_meta(redis, ch)
        current = str(meta.get('pathHash') or '').strip().lower()
        session_gone = (not meta) or (current and current != h)
        idx = max(1, int(index or 1))
        frame = None if session_gone else _loads(await redis.hget(key, store.frame_field(idx)))
        if frame is None and not session_gone:
            FilePlayManager.instance(ch).ensure_frame(h, idx)
            deadline = time.monotonic() + cls.FRAME_WAIT_S
            while time.monotonic() < deadline:
                frame = _loads(await redis.hget(key, store.frame_field(idx)))
                if frame is not None:
                    break
                await asyncio.sleep(0.05)
            meta = await cls._channel_meta(redis, ch)
            alive = await cls._worker_alive(redis, ch)
        return {
            'frame': frame,
            'frameCount': int(meta.get('frameCount') or 0),
            'frameCountExact': bool(meta.get('frameCountExact')),
            'hasData': int(meta.get('frameCount') or 0) > 0 or frame is not None,
            'complete': bool(meta.get('frameCountExact')),
            'hasTimestamp': bool(meta.get('hasTimestamp')),
            'type': meta.get('type') or '',
            'path': meta.get('path') or resolved_s,
            'pathHash': h,
            'channel': ch,
            'workerAlive': alive,
            'sessionGone': session_gone,
        }

    @classmethod
    async def get_curve(cls, redis: aioredis.Redis, body: dict[str, Any]) -> dict[str, Any]:
        """按块取点；只返回客户端还没有的块。必须带 pathHash，不用 path。"""
        ch = rk.fileplay_channel(body.get('channel') or 'curve')
        alive = await cls._worker_alive(redis, ch)
        h = str(body.get('pathHash') or body.get('path_hash') or '').strip().lower()
        items = body.get('items') or []
        fields = [str(i.get('field') or i.get('Field') or '') for i in items if i]
        fields = [f for f in fields if f]
        meta = await cls._channel_meta(redis, ch) if h else {}
        current = str(meta.get('pathHash') or '').strip().lower()
        session_gone = bool(h) and ((not meta) or (bool(current) and current != h))

        def _out(
            points_by: dict[str, list],
            *,
            gone: bool,
            worker: bool,
            error: str = '',
            pending: list[int] | None = None,
            chunk_points_by: dict[str, dict[str, list]] | None = None,
            ready_by: dict[str, list[int]] | None = None,
        ) -> dict[str, Any]:
            table_type = meta.get('type') or ''
            out_items = []
            for it in items:
                fid = str(it.get('field') or it.get('Field') or '')
                if not fid:
                    continue
                key = store.curve_field(fid)
                out_items.append(
                    {
                        'type': table_type,
                        'field': fid,
                        'name': fid,
                        'unit': '',
                        'points': points_by.get(fid) or points_by.get(key) or [],
                        'chunkPoints': (chunk_points_by or {}).get(key) or (chunk_points_by or {}).get(fid) or {},
                        'readyChunks': (ready_by or {}).get(key) or (ready_by or {}).get(fid) or [],
                    }
                )
            payload: dict[str, Any] = {
                'items': out_items,
                'frameCount': int(meta.get('frameCount') or 0),
                'frameCountExact': bool(meta.get('frameCountExact')),
                'chunkCount': store.curve_chunk_count(int(meta.get('frameCount') or 0)),
                'hasData': int(meta.get('frameCount') or 0) > 0,
                'complete': bool(meta.get('frameCountExact')),
                'hasTimestamp': bool(meta.get('hasTimestamp')),
                'pathHash': h,
                'channel': ch,
                'workerAlive': worker,
                'sessionGone': gone,
                'pendingChunks': list(pending or []),
            }
            if error:
                payload['error'] = error
            return payload

        if not fields:
            return _out({}, gone=session_gone, worker=alive)
        if not h:
            return _out({}, gone=False, worker=alive, error='缺少 pathHash')
        if session_gone:
            return _out({}, gone=True, worker=alive, error='该文件会话已失效，请重新解析')
        if not alive:
            # 进程已死则立刻失败，不能 LPUSH 再空等 60s（还会误拉起 worker 把残余清掉）
            return _out({}, gone=False, worker=False, error='曲线解析进程未运行，请重新解析')
        frame_count = int(meta.get('frameCount') or 0)
        chunks = store.curve_chunks_requested(body, frame_count)
        want = [store.curve_field(f) for f in fields]

        async def _hmget(key: str, fields_: list[str]) -> list[Any]:
            if not fields_:
                return []
            hmget = getattr(redis, 'hmget', None)
            if callable(hmget):
                try:
                    raws = await hmget(key, *fields_)
                    if isinstance(raws, (list, tuple)) and len(raws) == len(fields_):
                        return list(raws)
                except Exception:
                    pass
            out: list[Any] = []
            for fid in fields_:
                out.append(await redis.hget(key, fid))
            return out

        points_by: dict[str, list] = {fid: [] for fid in want}
        chunk_points_by: dict[str, dict[str, list]] = {fid: {} for fid in want}
        ready_by: dict[str, list[int]] = {fid: [] for fid in want}
        missing: list[int] = []
        default_have = {
            int(x)
            for x in (body.get('haveChunks') or body.get('have_chunks') or [])
            if str(x).lstrip('-').isdigit()
        }

        def _have_set(it: dict) -> set[int]:
            raw = it.get('haveChunks') if isinstance(it, dict) else None
            if raw is None and isinstance(it, dict):
                raw = it.get('have_chunks')
            if not raw:
                return set(default_have)
            return {int(x) for x in raw if str(x).lstrip('-').isdigit()}

        item_by_field = {}
        for it in items:
            fid = str(it.get('field') or it.get('Field') or '')
            if fid:
                item_by_field[store.curve_field(fid)] = it

        for fid, orig in zip(want, fields):
            pkey = rk.fileplay_points_key(h, fid, ch)
            raws = await _hmget(pkey, [store.curve_chunk_field(c) for c in chunks])
            have = _have_set(item_by_field.get(fid) or {})
            pts: list = []
            new_chunks: dict[str, list] = {}
            ready: list[int] = []
            for c, raw in zip(chunks, raws):
                if raw is None:
                    if c not in missing:
                        missing.append(c)
                    continue
                ready.append(c)
                if c in have:
                    continue
                pt = _loads(raw)
                if not isinstance(pt, list):
                    pt = []
                new_chunks[str(c)] = pt
                pts.extend(pt)
            points_by[fid] = pts
            points_by[orig] = pts
            chunk_points_by[fid] = new_chunks
            ready_by[fid] = ready
        pending = missing
        if missing:
            FilePlayManager.instance(ch).send(
                {
                    'op': 'curve',
                    'pathHash': h,
                    'fields': want,
                    'chunks': missing,
                    'startIndex': missing[0],
                    'endIndex': missing[-1] + 1,
                    'channel': ch,
                }
            )
        meta = await cls._channel_meta(redis, ch)
        alive = await cls._worker_alive(redis, ch)
        if not alive:
            return _out(
                points_by,
                gone=False,
                worker=False,
                error='曲线解析进程已退出，请重新解析',
                pending=pending,
                chunk_points_by=chunk_points_by,
                ready_by=ready_by,
            )
        return _out(
            points_by,
            gone=False,
            worker=True,
            pending=pending,
            chunk_points_by=chunk_points_by,
            ready_by=ready_by,
        )
