"""设备会话：打开记录 + 解释器/组装器绑定（Redis）。"""

from __future__ import annotations

from collections.abc import Callable
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
from module_payload.store.jsonutil import dumps_json
from module_payload.store.session_store import (
    delete_session_sync,
    get_session_sync as store_get_session_sync,
    loads_session,
)


def _dumps(data: Any) -> str:
    """会话写入 Redis 前的 JSON 编码。"""
    return dumps_json(data)


def _loads(text: str | bytes | None) -> dict[str, Any] | None:
    """Redis 取值反序列化为 dict；空返回 None。"""
    return loads_session(text)


class PayloadSessionService:
    """设备会话：parser/assembler/routes 绑定，存 Redis ``payload:session:*``。"""

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
        """写入 Redis 会话；已有记录则保留 openedAt，未传 routes 时沿用旧值。"""
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
        """删除 Redis 会话键。"""
        delete_session_sync(redis_client, src_param, src_kind)

    @classmethod
    def get_session_sync(cls, redis_client: Any, src_param: str, src_kind: str | None = None) -> dict[str, Any] | None:
        """同步读 Redis 会话；不存在返回 None。"""
        return store_get_session_sync(redis_client, src_param, src_kind)

    @classmethod
    def get_parser_id_sync(cls, redis_client: Any, src_param: str, src_kind: str | None = None) -> str | None:
        """从会话取 parserId；无会话或空串返回 None。"""
        session = cls.get_session_sync(redis_client, src_param, src_kind)
        if not session:
            return None
        pid = (session.get('parserId') or '').strip()
        return pid or None

    @classmethod
    def get_assembler_id_sync(cls, redis_client: Any, src_param: str, src_kind: str | None = None) -> str:
        """从会话取组装器 id；无会话回落到透传。"""
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
        """异步读 Redis 会话。"""
        src_kind = src_kind or infer_src_kind(src_param)
        return _loads(await redis.get(rk.session_key(src_kind, src_param)))

    @classmethod
    async def list_sessions(
        cls,
        redis: aioredis.Redis,
        *,
        is_alive: Callable[[str], bool] | None = None,
    ) -> list[dict[str, Any]]:
        """列出 Redis 会话。

        ``is_alive`` 由设备服务传入（查采集进程是否仍在）。
        未传则不按进程裁剪，避免 SessionService 依赖 ProcessManager。
        传入时：采集已不在的僵尸 session 会删键，避免遥控按钮假「已连接」。
        """
        keys = [k async for k in redis.scan_iter(match=f'{rk.PREFIX}:session:*', count=100)]
        out: list[dict[str, Any]] = []
        for key in keys:
            session = _loads(await redis.get(key))
            if not session:
                continue
            src_param = str(session.get('srcParam') or '')
            if src_param and is_alive is not None and not is_alive(src_param):
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
    def list_parser_options(cls) -> list[dict[str, str]]:
        """前端下拉用的解释器列表。"""
        return list_parsers()

    @classmethod
    def list_assembler_options(cls, src_kind: str | None = None) -> list[dict[str, str]]:
        """前端下拉用的组装器列表；可按连接类型过滤。"""
        return list_assemblers(src_kind=src_kind)

    @classmethod
    def validate_assembler_id(cls, assembler_id: str | None, src_kind: str | None = None) -> str:
        """校验并归一化；未知或不匹配连接类型则抛 ValueError。"""
        return validate_assembler_for_src(assembler_id, src_kind)
