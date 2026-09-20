"""流水线错误写入 Redis：按类型分 List，便于排查。

结构：
  payload:error:assembler:log      List  组装器校验/组帧错误
  payload:error:tm:log             List  遥测解析错误（含相机 D8/D9）
  payload:error:session:log        List  会话入库等其它错误
  payload:error:camera:log         List  相机图像组装错误
  payload:error:{type}:latest      各类型最近一条
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from module_payload.collectors import redis_cmd_helper as redis_cmd

# stage → Redis 类型键后缀
_STAGE_TO_TYPE = {
    'assembler': 'assembler',
    'parser': 'tm',
    'tm': 'tm',
    'telemetry': 'tm',
    'session': 'session',
    'camera': 'camera',
    'camera_image': 'camera',
}


def normalize_error_type(stage: str) -> str:
    """流水线 stage 映射为前端错误分类；未知则原样返回。"""
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
    """写入 payload:error:{type}:log（数组）与 payload:error:{type}:latest。"""
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

        redis_client.write_batch(redis_cmd.error(error_type, entry, device_id=device_id))
    except Exception:
        pass
