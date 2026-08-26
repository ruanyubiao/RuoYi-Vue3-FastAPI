"""历史文件上传 / 浏览 / 解析 / 取帧（独立 Redis Hash，不写实时遥测）。

API 只 LPUSH 命令；拆帧在 fileplay worker（或进程内回退引擎）里做。
parse 立即返回（status 多为 parsing），前端轮询 ``/file/status``；取帧未命中缓存时最多再等 FRAME_WAIT_S。
每次取帧都带回当前 frameCount，便于预估改精确后前端滑块跟着变。
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
    CURVE_WAIT_S = 60.0  # 等 c:{field} 点列写齐

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
        out: dict[str, Any] = {
            'path': str(resolved),
            'pathHash': path_hash,
            'status': status,
            'type': meta.get('type') or table_type,
            'frameCount': int(meta.get('frameCount') or 0),
            'frameCountExact': bool(meta.get('frameCountExact')),
            'hasTimestamp': bool(meta.get('hasTimestamp')),
            'startTsMs': int(meta.get('startTsMs') or 0),
            'kind': meta.get('kind') or '',
        }
        if status == 'error':
            out['error'] = meta.get('error') or '解析失败'
        if frame is not None:
            out['frame'] = frame
        return out

    @classmethod
    async def parse(cls, redis: aioredis.Redis, table_type: str, path: str) -> dict[str, Any]:
        """通知解析进程拆帧；立即返回当前 status（多为 parsing）。

        路径必须在 log_data / logs_data 白名单内。前端再轮询 ``get_status``。
        """
        resolved = resolve_play_path(path)
        path_hash = rk.fileplay_path_hash(str(resolved))
        FilePlayManager.instance().parse((table_type or '').upper(), str(resolved))
        meta = _loads(await redis.hget(rk.fileplay_hash_key(path_hash), store.META_FIELD)) or {}
        frame = None
        if meta.get('status') == 'ready':
            frame = _loads(await redis.hget(rk.fileplay_hash_key(path_hash), store.frame_field(1)))
        return cls._status_payload((table_type or '').upper(), resolved, path_hash, meta, frame)

    @classmethod
    async def get_status(cls, redis: aioredis.Redis, path: str) -> dict[str, Any]:
        """读当前解析会话：parsing / ready / error；ready 时带第 1 帧。"""
        resolved = resolve_play_path(path)
        path_hash = rk.fileplay_path_hash(str(resolved))
        meta = _loads(await redis.hget(rk.fileplay_hash_key(path_hash), store.META_FIELD)) or {}
        frame = None
        if meta.get('status') == 'ready':
            frame = _loads(await redis.hget(rk.fileplay_hash_key(path_hash), store.frame_field(1)))
        if meta.get('status') == 'error':
            return cls._status_payload('', resolved, path_hash, meta)
        return cls._status_payload(str(meta.get('type') or ''), resolved, path_hash, meta, frame)

    @classmethod
    async def get_frame(cls, redis: aioredis.Redis, path: str, index: int) -> dict[str, Any]:
        """取第 N 帧；未解析则通知进程，最多等 Redis 1s。每次带回当前总帧数。"""
        resolved = resolve_play_path(path)
        path_hash = rk.fileplay_path_hash(str(resolved))
        key = rk.fileplay_hash_key(path_hash)
        store.assert_not_live_tm_key(key)
        idx = max(1, int(index or 1))
        frame = _loads(await redis.hget(key, store.frame_field(idx)))
        if frame is None:
            FilePlayManager.instance().ensure_frame(path_hash, idx)
            deadline = time.monotonic() + cls.FRAME_WAIT_S
            while time.monotonic() < deadline:
                frame = _loads(await redis.hget(key, store.frame_field(idx)))
                if frame is not None:
                    break
                await asyncio.sleep(0.05)
        meta = _loads(await redis.hget(key, store.META_FIELD)) or {}
        return {
            'frame': frame,
            'frameCount': int(meta.get('frameCount') or 0),
            'frameCountExact': bool(meta.get('frameCountExact')),
            'hasTimestamp': bool(meta.get('hasTimestamp')),
            'type': meta.get('type') or '',
            'path': meta.get('path') or str(resolved),
        }

    @classmethod
    async def get_curve(cls, redis: aioredis.Redis, body: dict[str, Any]) -> dict[str, Any]:
        """从文件会话已解析帧抽取字段点列；不足则让进程补解析。"""
        path = str(body.get('path') or '')
        resolved = resolve_play_path(path)
        path_hash = rk.fileplay_path_hash(str(resolved))
        items = body.get('items') or []
        fields = [str(i.get('field') or i.get('Field') or '') for i in items if i]
        fields = [f for f in fields if f]
        if not fields:
            meta = _loads(await redis.hget(rk.fileplay_hash_key(path_hash), store.META_FIELD)) or {}
            return {
                'items': [],
                'frameCount': int(meta.get('frameCount') or 0),
                'frameCountExact': bool(meta.get('frameCountExact')),
                'hasTimestamp': bool(meta.get('hasTimestamp')),
            }
        FilePlayManager.instance().send(
            {
                'op': 'curve',
                'pathHash': path_hash,
                'fields': fields,
                'startIndex': body.get('startIndex') or body.get('start_index') or 1,
                'endIndex': body.get('endIndex') or body.get('end_index'),
            }
        )
        key = rk.fileplay_hash_key(path_hash)
        deadline = time.monotonic() + cls.CURVE_WAIT_S
        points_by: dict[str, list] = {}
        while time.monotonic() < deadline:
            ready = True
            for fid in fields:
                raw = await redis.hget(key, f'c:{fid}')
                if raw is None:
                    ready = False
                    break
                points_by[fid] = _loads(raw) or []
            if ready:
                break
            await asyncio.sleep(0.1)
        meta = _loads(await redis.hget(key, store.META_FIELD)) or {}
        table_type = meta.get('type') or ''
        out_items = []
        for it in items:
            fid = str(it.get('field') or it.get('Field') or '')
            out_items.append(
                {
                    'type': table_type,
                    'field': fid,
                    'name': fid,
                    'unit': '',
                    'points': points_by.get(fid) or [],
                }
            )
        return {
            'items': out_items,
            'frameCount': int(meta.get('frameCount') or 0),
            'frameCountExact': bool(meta.get('frameCountExact')),
            'hasTimestamp': bool(meta.get('hasTimestamp')),
        }
