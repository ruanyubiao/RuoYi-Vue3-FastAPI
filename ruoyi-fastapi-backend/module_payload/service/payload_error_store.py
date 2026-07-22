"""流水线错误写入 Redis：按类型分 List，便于排查。

结构：
  payload:error:assembler          List  组装器校验/组帧错误
  payload:error:tm                 List  遥测解析错误
  payload:error:session            List  会话入库等其它错误
  payload:error:latest:{type}      各类型最近一条
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collectors.redis_sync import dumps_json
from module_payload.constants import ERROR_LOG_MAX

# stage → Redis 类型键后缀
_STAGE_TO_TYPE = {
    'assembler': 'assembler',
    'parser': 'tm',
    'tm': 'tm',
    'telemetry': 'tm',
    'session': 'session',
}


def normalize_error_type(stage: str) -> str:
    key = (stage or '').strip().lower()
    return _STAGE_TO_TYPE.get(key, key or 'session')


def push_pipeline_error(
    redis_client: Any,
    *,
    stage: str,
    message: str,
    device_id: str = '',
    assembler_id: str | None = None,
    parser_id: str | None = None,
    data_len: int | None = None,
) -> None:
    """写入 payload:error:{type}（数组）与 payload:error:latest:{type}。"""
    if redis_client is None or not message:
        return
    try:
        error_type = normalize_error_type(stage)
        entry: dict[str, Any] = {
            'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'type': error_type,
            'stage': stage,
            'message': str(message),
            'deviceId': device_id or '',
        }
        if assembler_id:
            entry['assemblerId'] = assembler_id
        if parser_id:
            entry['parserId'] = parser_id
        if data_len is not None:
            entry['dataLen'] = int(data_len)

        dumped = dumps_json(entry)
        redis_client.set(rk.error_type_latest_key(error_type), dumped)
        key = rk.error_type_key(error_type)
        redis_client.lpush(key, dumped)
        redis_client.ltrim(key, 0, ERROR_LOG_MAX - 1)

        if device_id and error_type == 'assembler':
            redis_client.set(rk.assembled_error_key(device_id), dumped)
    except Exception:
        pass
