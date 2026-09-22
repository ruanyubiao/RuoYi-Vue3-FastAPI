"""历史文件上传 / 浏览 / 解析 / 取帧（独立 Redis，不写实时遥测）。

history / curve 各最多 5 个解析进程，按 pathHash 隔离。API 只 LPUSH 命令。
parse 立即返回；前端轮询 ``/file/status``。取帧未命中时最多等 FRAME_WAIT_S。
该 hash 的缓存被 janitor 清掉才返回 sessionGone。
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
    """历史文件回放：上传到 upload_logs_data_raw、浏览、解析子进程、取帧。"""

    FRAME_WAIT_S = 1.0  # 单帧补解析上限
    CURVE_WAIT_S = 60.0  # 等 job 标记后按序号 HMGET 点列
    BUSY_ERROR = FilePlayManager.BUSY_ERROR

    @classmethod
    async def upload_chunk(
        cls,
        file: UploadFile,
        filename: str,
        chunk_index: int = 0,
        total_chunks: int = 1,
    ) -> dict[str, Any]:
        """分片写入 ``{UPLOAD_PATH}/upload_logs_data_raw``，同名覆盖。

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
    def upload_stat(cls, filename: str) -> dict[str, Any]:
        """上传目录里是否已有同名文件，以及字节大小。"""
        name = _safe_filename(filename)
        dest = get_upload_log_data_dir() / name
        if not dest.is_file():
            return {'filename': name, 'exists': False, 'size': 0}
        return {'filename': name, 'exists': True, 'size': int(dest.stat().st_size)}

    @classmethod
    def browse(cls, root: str, rel: str = '', *, show_all: bool = False) -> dict[str, Any]:
        """列出上传目录或本地日志。默认只含 ``.bin``，``show_all`` 时含全部文件。"""
        return list_dir(root, rel, show_all=show_all)

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
            'parsedDone': bool(meta.get('parsedDone')),
        }
        if status in ('error', 'busy'):
            out['error'] = meta.get('error') or ('解析失败' if status == 'error' else cls.BUSY_ERROR)
        if frame is not None:
            out['frame'] = frame
        return out

    @classmethod
    async def _worker_alive(cls, redis: aioredis.Redis, path_hash: str, channel: str) -> bool:
        h = (path_hash or '').strip().lower()
        if not h:
            return False
        try:
            raw = await redis.get(rk.fileplay_worker_status_key(h, channel))
        except Exception:
            return False
        return bool(raw)

    @classmethod
    async def _file_meta(cls, redis: aioredis.Redis, path_hash: str, channel: str) -> dict[str, Any]:
        h = (path_hash or '').strip().lower()
        if not h:
            return {}
        try:
            raw = await redis.get(rk.fileplay_meta_key(h, channel))
        except Exception:
            return {}
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode('utf-8', errors='ignore')
        return _loads(raw) or {}

    @classmethod
    async def _touch(cls, redis: aioredis.Redis, path_hash: str, channel: str) -> None:
        h = (path_hash or '').strip().lower()
        if not h:
            return
        try:
            await redis.set(rk.fileplay_touch_key(h, channel), str(int(time.time())))
        except Exception:
            pass

    @classmethod
    async def _history_preview_frame(
        cls, redis: aioredis.Redis, path_hash: str, channel: str, meta: dict[str, Any]
    ) -> Any:
        """history 才读第 1 帧 JSON。curve 的 data Hash 是 zstd 块，decode_responses 会炸 UTF-8。"""
        if rk.fileplay_channel(channel) == 'curve':
            return None
        if not (str(meta.get('status') or '') == 'ready' or int(meta.get('frameCount') or 0) > 0):
            return None
        try:
            raw = await redis.hget(rk.fileplay_hash_key(path_hash, channel), store.frame_field(1))
        except (UnicodeDecodeError, UnicodeError):
            return None
        return _loads(raw)

    @classmethod
    def _busy_payload(cls, table: str, resolved: Path, path_hash: str, channel: str) -> dict[str, Any]:
        return cls._status_payload(
            table,
            resolved,
            path_hash,
            {
                'status': 'busy',
                'error': cls.BUSY_ERROR,
                'channel': channel,
                'sessionGone': False,
                'workerAlive': False,
                'frameCount': 0,
                'frameCountExact': False,
            },
        )

    @classmethod
    async def parse(
        cls,
        redis: aioredis.Redis,
        table_type: str,
        path: str,
        channel: str = 'history',
        force: Any = 0,
    ) -> dict[str, Any]:
        """通知该文件解析进程拆帧；立即返回当前 status。

        同一文件已完成或扫描中无 force 不重复推 parse。第 6 个新文件返回 busy。
        """
        ch = rk.fileplay_channel(channel)
        resolved = resolve_play_path(path)
        path_hash = rk.fileplay_path_hash(str(resolved))
        table = (table_type or '').upper()
        want_force = parse_force(force)
        meta = await cls._file_meta(redis, path_hash, ch)
        same = str(meta.get('type') or '').upper() == table if meta else False
        complete = bool(meta.get('frameCountExact'))
        parsed_done = bool(meta.get('parsedDone'))
        status = str(meta.get('status') or '')
        has_data = int(meta.get('frameCount') or 0) > 0
        skip = bool(meta) and not want_force and same and status != 'error' and has_data
        if not skip:
            ok = FilePlayManager.instance(ch).parse(table, str(resolved), force=want_force)
            if ok is False:
                return cls._busy_payload(table, resolved, path_hash, ch)
            meta = await cls._file_meta(redis, path_hash, ch)
        await cls._touch(redis, path_hash, ch)
        frame = await cls._history_preview_frame(redis, path_hash, ch, meta)
        meta = {
            **meta,
            'workerAlive': await cls._worker_alive(redis, path_hash, ch),
            'sessionGone': False,
            'channel': ch,
            'alreadyParsing': skip and not parsed_done and not complete,
            'alreadyComplete': skip and (parsed_done or complete),
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
        """读该文件解析会话。优先 pathHash。"""
        ch = rk.fileplay_channel(channel)
        h = (path_hash or '').strip().lower()
        if not h and path:
            resolved = resolve_play_path(path)
            h = rk.fileplay_path_hash(str(resolved))
        alive = await cls._worker_alive(redis, h, ch)
        meta = await cls._file_meta(redis, h, ch)
        if not meta:
            resolved = Path(path or '')
            empty = {
                'status': 'idle',
                'channel': ch,
                'workerAlive': alive,
                'sessionGone': bool(h),
                'frameCount': 0,
                'frameCountExact': False,
                'path': str(resolved),
                'type': '',
            }
            return cls._status_payload('', resolved, h, empty)
        await cls._touch(redis, h, ch)
        resolved = Path(str(meta.get('path') or path or ''))
        frame = await cls._history_preview_frame(redis, h, ch, meta)
        meta = {**meta, 'workerAlive': alive, 'sessionGone': False, 'channel': ch}
        if meta.get('status') == 'error':
            return cls._status_payload(str(meta.get('type') or ''), resolved, h, meta)
        return cls._status_payload(str(meta.get('type') or ''), resolved, h, meta, frame)

    @classmethod
    async def get_frame(
        cls,
        redis: aioredis.Redis,
        path: str = '',
        index: int = 1,
        path_hash: str = '',
        channel: str = 'history',
    ) -> dict[str, Any]:
        """取第 N 帧。该 hash 无缓存时 sessionGone。"""
        ch = rk.fileplay_channel(channel)
        h = (path_hash or '').strip().lower()
        if not h:
            resolved = resolve_play_path(path)
            h = rk.fileplay_path_hash(str(resolved))
            resolved_s = str(resolved)
        else:
            resolved_s = path
        key = rk.fileplay_hash_key(h, ch)
        store.assert_not_live_tm_key(key)
        meta = await cls._file_meta(redis, h, ch)
        alive = await cls._worker_alive(redis, h, ch)
        session_gone = not bool(meta)
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
            meta = await cls._file_meta(redis, h, ch)
            alive = await cls._worker_alive(redis, h, ch)
        if meta:
            await cls._touch(redis, h, ch)
        return {
            'frame': frame,
            'frameCount': int(meta.get('frameCount') or 0),
            'frameCountExact': bool(meta.get('frameCountExact') or meta.get('parsedDone')),
            'hasData': int(meta.get('frameCount') or 0) > 0 or frame is not None,
            'complete': bool(meta.get('frameCountExact') or meta.get('parsedDone')),
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
        h = str(body.get('pathHash') or body.get('path_hash') or '').strip().lower()
        items = body.get('items') or []
        fields = [str(i.get('field') or i.get('Field') or '') for i in items if i]
        fields = [f for f in fields if f]
        meta = await cls._file_meta(redis, h, ch) if h else {}
        alive = await cls._worker_alive(redis, h, ch)
        session_gone = bool(h) and not bool(meta)

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
                'frameCountExact': bool(meta.get('frameCountExact') or meta.get('parsedDone')),
                'chunkCount': store.curve_chunk_count(int(meta.get('frameCount') or 0)),
                'hasData': int(meta.get('frameCount') or 0) > 0,
                'complete': bool(meta.get('frameCountExact') or meta.get('parsedDone')),
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
        await cls._touch(redis, h, ch)
        frame_count = int(meta.get('frameCount') or 0)
        chunks = store.curve_chunks_requested(body, frame_count)
        want = [store.curve_field(f) for f in fields]

        async def _hmget(key: str, fields_: list[str]) -> list[Any]:
            if not fields_:
                return []
            import inspect

            pool = getattr(redis, 'connection_pool', None)
            exec_cmd = getattr(redis, 'execute_command', None)
            if pool is not None and callable(exec_cmd):
                from redis.client import NEVER_DECODE

                raw = exec_cmd('HMGET', key, *fields_, **{NEVER_DECODE: []})
                if inspect.isawaitable(raw):
                    raw = await raw
                return list(raw or [])
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

        pkey = rk.fileplay_points_key(h, channel=ch)
        raws = await _hmget(pkey, [store.curve_chunk_field(c) for c in chunks])
        for c, raw in zip(chunks, raws):
            if raw is None and c not in missing:
                missing.append(c)

        for fid, orig in zip(want, fields):
            have = _have_set(item_by_field.get(fid) or {})
            pts: list = []
            new_chunks: dict[str, list] = {}
            ready: list[int] = []
            for c, raw in zip(chunks, raws):
                if raw is None:
                    continue
                ready.append(c)
                if c in have:
                    continue
                pt = store.points_from_chunk_value(raw, fid)
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
            sent = FilePlayManager.instance(ch).send(
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
            if sent is False:
                return _out(
                    points_by,
                    gone=False,
                    worker=alive,
                    error=cls.BUSY_ERROR,
                    pending=pending,
                    chunk_points_by=chunk_points_by,
                    ready_by=ready_by,
                )
        alive = await cls._worker_alive(redis, h, ch)
        return _out(
            points_by,
            gone=False,
            worker=alive,
            pending=pending,
            chunk_points_by=chunk_points_by,
            ready_by=ready_by,
        )

    @classmethod
    def _file_status(cls, meta: dict[str, Any], *, parsed_done: bool | None = None) -> str:
        if str(meta.get('status') or '') == 'error' or str(meta.get('error') or '').strip():
            return '解析错误'
        if parsed_done is None:
            parsed_done = bool(meta.get('parsedDone'))
        if parsed_done:
            return '已完成'
        return '解析中'

    @classmethod
    async def _parsed_done(cls, redis, path_hash: str, channel: str, meta: dict[str, Any]) -> bool:
        """meta.parsedDone，或曲线万帧块已覆盖精确总帧。"""
        if bool(meta.get('parsedDone')):
            return True
        if channel != 'curve' or not bool(meta.get('frameCountExact')):
            return False
        try:
            stored = int(await redis.hlen(rk.fileplay_hash_key(path_hash, channel)) or 0)
        except Exception:
            return False
        return store.curve_chunks_complete(int(meta.get('frameCount') or 0), stored)

    @classmethod
    def _proc_status(cls, *, alive: bool, parsed_done: bool) -> str:
        if not alive:
            return '已退出'
        if parsed_done:
            return '空闲'
        return '运行中'

    @classmethod
    async def list_sessions(cls, redis: aioredis.Redis, channel: str = 'history') -> dict[str, Any]:
        """缓存 ∪ 活进程，对得上合成一行。"""
        ch = rk.fileplay_channel(channel)
        hashes: set[str] = set()
        pattern = f'{rk.fileplay_channel_prefix(ch)}*:meta'
        cursor: int | str = 0
        while True:
            try:
                scan = getattr(redis, 'scan', None)
                if not callable(scan):
                    break
                cursor, keys = await scan(cursor=cursor, match=pattern, count=200)
            except Exception:
                break
            for key in keys or []:
                if isinstance(key, (bytes, bytearray)):
                    key = key.decode('utf-8', errors='ignore')
                h = rk.fileplay_hash_from_leaf_key(key)
                if h:
                    hashes.add(h)
            if cursor in (0, '0', b'0', None):
                break
        live_rows = FilePlayManager.instance(ch).list_live()
        live = {str(x.get('pathHash') or '').strip().lower(): x for x in live_rows}
        hashes |= {h for h in live if h}
        items: list[dict[str, Any]] = []
        for h in sorted(hashes):
            meta = await cls._file_meta(redis, h, ch)
            alive = bool(live.get(h)) or await cls._worker_alive(redis, h, ch)
            parsed_done = await cls._parsed_done(redis, h, ch, meta)
            last_access = 0
            try:
                raw = await redis.get(rk.fileplay_touch_key(h, ch))
                last_access = int(raw or 0)
            except (TypeError, ValueError):
                last_access = 0
            except Exception:
                last_access = 0
            started = int(meta.get('startedAt') or (live.get(h) or {}).get('startedAt') or 0)
            items.append(
                {
                    'pathHash': h,
                    'path': str(meta.get('path') or ''),
                    'channel': ch,
                    'startedAt': started,
                    'lastAccess': last_access,
                    'fileStatus': cls._file_status(meta, parsed_done=parsed_done),
                    'procStatus': cls._proc_status(alive=alive, parsed_done=parsed_done),
                    'workerAlive': alive,
                    'hasCache': bool(meta),
                    'parsedDone': parsed_done,
                    'frameCount': int(meta.get('frameCount') or 0),
                }
            )
        return {'channel': ch, 'items': items}

    @classmethod
    def close_session(cls, path_hash: str, channel: str = 'history') -> dict[str, Any]:
        """只杀进程，保留 Redis。"""
        ch = rk.fileplay_channel(channel)
        h = (path_hash or '').strip().lower()
        if h:
            FilePlayManager.instance(ch).kill(h)
        return {'ok': True, 'pathHash': h, 'channel': ch}

    @classmethod
    async def clear_session(cls, redis: aioredis.Redis, path_hash: str, channel: str = 'history') -> dict[str, Any]:
        """只删该文件 Redis，不杀进程。"""
        ch = rk.fileplay_channel(channel)
        h = (path_hash or '').strip().lower()
        if h:
            try:
                from module_payload.collectors.redis_sync import create_sync_redis

                r = create_sync_redis()
                try:
                    store.delete_session(r, h, channel=ch)
                finally:
                    r.close()
            except Exception:
                store.delete_session(redis, h, channel=ch)  # type: ignore[arg-type]
        return {'ok': True, 'pathHash': h, 'channel': ch}
