"""设备会话：打开记录 + 解释器/组装器绑定（Redis）。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from redis import asyncio as aioredis

from module_payload import redis_keys as rk
from module_payload.assemblers import create_assembler, list_assemblers, normalize_assembler_id, resolve_assembler_cls
from module_payload.constants import ASSEMBLER_PASSTHROUGH, infer_src_kind
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
    def open_session_sync(
        cls,
        redis_client: Any,
        *,
        src_param: str,
        src_kind: str | None = None,
        parser_id: str | None = None,
        assembler_id: str | None = None,
        status: str = 'running',
    ) -> dict[str, Any]:
        src_kind = src_kind or infer_src_kind(src_param)
        if parser_id and resolve_parser(parser_id) is None:
            raise ValueError(f'未知解释器: {parser_id}')
        aid = normalize_assembler_id(assembler_id)
        if resolve_assembler_cls(aid) is None:
            raise ValueError(f'未知组装器: {assembler_id}')
        session = {
            'srcKind': src_kind,
            'srcParam': src_param,
            'parserId': parser_id or '',
            'assemblerId': aid,
            'openedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status': status,
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
    ) -> dict[str, Any]:
        """更新解释器；可选同时更新组装器（update_assembler=True）。"""
        src_kind = src_kind or infer_src_kind(src_param)
        key = rk.session_key(src_kind, src_param)
        session = _loads(await redis.get(key))
        if not session:
            session = {
                'srcKind': src_kind,
                'srcParam': src_param,
                'parserId': '',
                'assemblerId': ASSEMBLER_PASSTHROUGH,
                'openedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'status': 'running',
            }
        pid = (parser_id or '').strip()
        if pid and resolve_parser(pid) is None:
            from exceptions.exception import ServiceException

            raise ServiceException(message=f'未知解释器: {pid}')
        session['parserId'] = pid
        if update_assembler or 'assemblerId' not in session:
            aid = normalize_assembler_id(assembler_id)
            if resolve_assembler_cls(aid) is None:
                from exceptions.exception import ServiceException

                raise ServiceException(message=f'未知组装器: {assembler_id}')
            session['assemblerId'] = aid
        elif not session.get('assemblerId'):
            session['assemblerId'] = ASSEMBLER_PASSTHROUGH
        session['srcKind'] = src_kind
        session['srcParam'] = src_param
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
        keys = [k async for k in redis.scan_iter(match=f'{rk.PREFIX}:session:*', count=100)]
        out: list[dict[str, Any]] = []
        for key in keys:
            session = _loads(await redis.get(key))
            if session:
                if not session.get('assemblerId'):
                    session['assemblerId'] = ASSEMBLER_PASSTHROUGH
                out.append(session)
        out.sort(key=lambda x: x.get('srcParam') or '')
        return out

    @classmethod
    def list_parser_options(cls) -> list[dict[str, str]]:
        return list_parsers()

    @classmethod
    def list_assembler_options(cls) -> list[dict[str, str]]:
        return list_assemblers()

    @classmethod
    def validate_assembler_id(cls, assembler_id: str | None) -> str:
        """校验并归一化；未知则抛 ValueError。"""
        aid = normalize_assembler_id(assembler_id)
        # 确保可创建
        create_assembler(aid)
        return aid
