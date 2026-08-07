"""设备会话：打开记录 + 解释器/组装器绑定（Redis）。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from redis import asyncio as aioredis

from module_payload import redis_keys as rk
from module_payload.assemblers import (
    list_assemblers,
    normalize_assembler_id,
    resolve_assembler_cls,
    validate_assembler_for_src,
)
from module_payload.constants import ASSEMBLER_PASSTHROUGH, infer_src_kind
from module_payload.demux import normalize_routes
from module_payload.parsers import list_parsers, resolve_parser


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _loads(text: str | bytes | None) -> dict[str, Any] | None:
    if not text:
        return None
    if isinstance(text, bytes):
        text = text.decode()
    return json.loads(text)


class PayloadSessionService:
    @classmethod
    def validate_routes(cls, routes: Any) -> list[dict[str, Any]]:
        """校验 routes；未知组装器/解释器抛 ValueError。"""
        normalized = normalize_routes(routes)
        for r in normalized:
            aid = normalize_assembler_id(r.get('assemblerId'))
            if resolve_assembler_cls(aid) is None:
                raise ValueError(f'未知组装器: {r.get("assemblerId")}')
            r['assemblerId'] = aid
            pid = (r.get('parserId') or '').strip()
            if pid and resolve_parser(pid) is None:
                raise ValueError(f'未知解释器: {pid}')
            r['parserId'] = pid
        return normalized

    @classmethod
    def open_session_sync(
        cls,
        redis_client: Any,
        *,
        src_param: str,
        src_kind: str | None = None,
        parser_id: str | None = None,
        assembler_id: str | None = None,
        routes: list[dict[str, Any]] | None = None,
        status: str = 'running',
        source: str | None = None,
    ) -> dict[str, Any]:
        src_kind = src_kind or infer_src_kind(src_param)
        if parser_id and resolve_parser(parser_id) is None:
            raise ValueError(f'未知解释器: {parser_id}')
        aid = validate_assembler_for_src(assembler_id, src_kind)
        prev = cls.get_session_sync(redis_client, src_param, src_kind) or {}
        src = (source or '').strip() or (prev.get('source') or '')
        if routes is not None:
            route_list = cls.validate_routes(routes)
        else:
            route_list = list(prev.get('routes') or [])
        session = {
            'srcKind': src_kind,
            'srcParam': src_param,
            'parserId': parser_id or '',
            'assemblerId': aid,
            'routes': route_list,
            'openedAt': prev.get('openedAt') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status': status,
            'source': src,
        }
        redis_client.set(rk.session_key(src_kind, src_param), _dumps(session))
        return session

    @classmethod
    def close_session_sync(cls, redis_client: Any, src_param: str, src_kind: str | None = None) -> None:
        src_kind = src_kind or infer_src_kind(src_param)
        redis_client.delete(rk.session_key(src_kind, src_param))

    @classmethod
    def get_session_sync(cls, redis_client: Any, src_param: str, src_kind: str | None = None) -> dict[str, Any] | None:
        src_kind = src_kind or infer_src_kind(src_param)
        return _loads(redis_client.get(rk.session_key(src_kind, src_param)))

    @classmethod
    def get_parser_id_sync(cls, redis_client: Any, src_param: str, src_kind: str | None = None) -> str | None:
        session = cls.get_session_sync(redis_client, src_param, src_kind)
        if not session:
            return None
        pid = (session.get('parserId') or '').strip()
        return pid or None

    @classmethod
    def get_assembler_id_sync(cls, redis_client: Any, src_param: str, src_kind: str | None = None) -> str:
        session = cls.get_session_sync(redis_client, src_param, src_kind)
        if not session:
            return ASSEMBLER_PASSTHROUGH
        return normalize_assembler_id(session.get('assemblerId'))

    @classmethod
    async def bind_parser(
        cls,
        redis: aioredis.Redis,
        *,
        src_param: str,
        parser_id: str | None,
        src_kind: str | None = None,
        assembler_id: str | None = None,
        update_assembler: bool = False,
        routes: list[dict[str, Any]] | None = None,
        update_routes: bool = False,
        source: str | None = None,
    ) -> dict[str, Any]:
        """更新解释器；可选同时更新组装器 / routes。"""
        src_kind = src_kind or infer_src_kind(src_param)
        key = rk.session_key(src_kind, src_param)
        session = _loads(await redis.get(key))
        if not session:
            session = {
                'srcKind': src_kind,
                'srcParam': src_param,
                'parserId': '',
                'assemblerId': ASSEMBLER_PASSTHROUGH,
                'routes': [],
                'openedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'status': 'running',
                'source': '',
            }
        pid = (parser_id or '').strip()
        if pid and resolve_parser(pid) is None:
            from exceptions.exception import ServiceException

            raise ServiceException(message=f'未知解释器: {pid}')
        session['parserId'] = pid
        if update_assembler or 'assemblerId' not in session:
            try:
                session['assemblerId'] = validate_assembler_for_src(assembler_id, src_kind)
            except ValueError as e:
                from exceptions.exception import ServiceException

                raise ServiceException(message=str(e)) from e
        elif not session.get('assemblerId'):
            session['assemblerId'] = ASSEMBLER_PASSTHROUGH
        if update_routes or routes is not None:
            try:
                session['routes'] = cls.validate_routes(routes if routes is not None else [])
            except ValueError as e:
                from exceptions.exception import ServiceException

                raise ServiceException(message=str(e)) from e
        elif 'routes' not in session:
            session['routes'] = []
        session['srcKind'] = src_kind
        session['srcParam'] = src_param
        if source is not None:
            session['source'] = str(source).strip()
        await redis.set(key, _dumps(session))
        return session

    @classmethod
    async def get_session(
        cls, redis: aioredis.Redis, src_param: str, src_kind: str | None = None
    ) -> dict[str, Any] | None:
        src_kind = src_kind or infer_src_kind(src_param)
        return _loads(await redis.get(rk.session_key(src_kind, src_param)))

    @classmethod
    async def list_sessions(cls, redis: aioredis.Redis) -> list[dict[str, Any]]:
        """列出会话；采集进程已不在的僵尸 session 会清理，避免遥控按钮假「已连接」。"""
        keys = [k async for k in redis.scan_iter(match=f'{rk.PREFIX}:session:*', count=100)]
        out: list[dict[str, Any]] = []
        for key in keys:
            session = _loads(await redis.get(key))
            if not session:
                continue
            src_param = str(session.get('srcParam') or '')
            if src_param and not cls._is_session_device_alive(src_param):
                try:
                    await redis.delete(key)
                except Exception:
                    pass
                continue
            if not session.get('assemblerId'):
                session['assemblerId'] = ASSEMBLER_PASSTHROUGH
            if 'routes' not in session:
                session['routes'] = []
            out.append(session)
        out.sort(key=lambda x: x.get('srcParam') or '')
        return out

    @classmethod
    def _is_session_device_alive(cls, src_param: str) -> bool:
        from module_payload.collectors.process_manager import CollectorProcessManager

        mgr = CollectorProcessManager.instance()
        p = (src_param or '').strip()
        parts = p.split(':')
        if len(parts) >= 4 and parts[0] == 'can':
            card_id = ':'.join(parts[:3])
            try:
                can_index = int(parts[3])
            except ValueError:
                return False
            for entry in mgr.list_opened():
                if entry.get('type') == 'can' and entry.get('deviceId') == card_id:
                    return bool(entry.get('alive')) and can_index in (entry.get('channels') or [])
            return False
        if parts[0] == 'serial' or p.startswith('udp:') or p.startswith('tcp:') or p.startswith('net:'):
            for entry in mgr.list_opened():
                if entry.get('deviceId') == p:
                    return bool(entry.get('alive'))
            return False
        return True

    @classmethod
    def list_parser_options(cls) -> list[dict[str, str]]:
        return list_parsers()

    @classmethod
    def list_assembler_options(cls, src_kind: str | None = None) -> list[dict[str, str]]:
        return list_assemblers(src_kind=src_kind)

    @classmethod
    def validate_assembler_id(cls, assembler_id: str | None, src_kind: str | None = None) -> str:
        """校验并归一化；未知或不匹配连接类型则抛 ValueError。"""
        return validate_assembler_for_src(assembler_id, src_kind)
