"""网页进程把开关命令交给监工，并等待结果。"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collector_host import current_collector_host
from module_payload.collectors.redis_sync import create_sync_redis, loads_json

OFFLINE_MESSAGE = '采集程序未启动'


def _mock_manager():
    """单测用 MagicMock 代替监工。正式进程的管理器不是 Mock。"""
    try:
        from unittest.mock import Mock

        from module_payload.collectors.process_manager import CollectorProcessManager

        mgr = CollectorProcessManager.instance()
    except Exception:
        return None
    if isinstance(mgr, Mock):
        return mgr
    return None


def _invoke_mock(mgr, op: str, payload: dict[str, Any]) -> dict[str, Any]:
    """把命令落到测试桩上的进程管理器，返回和监工一样的结果。"""
    if op == 'start_serial':
        device_id, already = mgr.start_serial(payload.get('port'), payload.get('config') or {})
        running: dict[str, Any] = {}
        for entry in mgr.list_opened():
            if entry.get('deviceId') == device_id:
                running = dict(entry.get('config') or {})
                break
        return {'ok': True, 'deviceId': device_id, 'alreadyOpen': already, 'config': running}
    if op == 'stop':
        mgr.stop(payload.get('deviceId'))
        return {'ok': True}
    if op == 'open_can':
        device_id, already = mgr.open_can_channel(
            payload.get('vendor'),
            payload.get('devIndex'),
            payload.get('canIndex'),
            payload.get('config') or {},
        )
        return {'ok': True, 'deviceId': device_id, 'alreadyOpen': already}
    if op == 'close_can':
        mgr.close_can_channel(payload.get('vendor'), payload.get('devIndex'), payload.get('canIndex'))
        return {'ok': True, 'deviceId': payload.get('deviceId') or ''}
    if op == 'start_net':
        config = payload.get('config') or {}
        device_id, already = mgr.start_net(
            payload.get('proto') or 'udp',
            payload.get('localHost'),
            payload.get('localPort'),
            config,
        )
        if already:
            mgr.apply_net_reuse_params(
                device_id,
                remote_host=config.get('remote_host') or '',
                remote_port=config.get('remote_port') or 0,
            )
        return {'ok': True, 'deviceId': device_id, 'alreadyOpen': already}
    if op == 'shutdown':
        mgr.shutdown_all()
        return {'ok': True, 'shutdown': True}
    raise RuntimeError(f'未知命令: {op}')


def invoke(op: str, payload: dict[str, Any] | None = None, *, timeout_s: float = 8.0) -> dict[str, Any]:
    """向当前采集机的命令队列推一条指令。超时未回复视为监工没在跑。"""
    mocked = _mock_manager()
    if mocked is not None:
        return _invoke_mock(mocked, op, payload or {})
    host = current_collector_host()
    req_id = uuid.uuid4().hex
    body = {'op': op, 'reqId': req_id, 'host': host}
    if payload:
        body.update(payload)
    redis = create_sync_redis()
    result_key = rk.collector_cmd_result_key(req_id, host)
    try:
        redis.delete(result_key)
        redis.lpush(rk.collector_cmd_key(host), json.dumps(body, ensure_ascii=False))
        deadline = time.time() + float(timeout_s)
        while time.time() < deadline:
            raw = redis.get(result_key)
            if raw:
                redis.delete(result_key)
                data = loads_json(raw) or {}
                if not data.get('ok', False):
                    raise RuntimeError(str(data.get('error') or '采集命令失败'))
                return data
            time.sleep(0.05)
    finally:
        try:
            redis.close()
        except Exception:
            pass
    raise RuntimeError(OFFLINE_MESSAGE)


def write_result(redis, host: str, req_id: str, result: dict[str, Any]) -> None:
    """监工把命令结果写回，供网页进程取走。"""
    redis.setex(
        rk.collector_cmd_result_key(req_id, host),
        30,
        json.dumps(result, ensure_ascii=False),
    )
