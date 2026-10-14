"""流水线错误写入 Redis：按失败步骤分 List，便于排查。

结构：
  payload:error:assembler:log   List  组帧错误（含相机图像拼图）
  payload:error:parser:log      List  遥测解析错误
  payload:error:session:log     List  入库过程中未归到上两类的异常
  payload:error:{type}:latest   各类型最近一条
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from module_payload.collectors import redis_cmd_helper as redis_cmd
from module_payload.constants import ERROR_TYPE_SESSION


def push_pipeline_error(
    redis_client: Any,
    *,
    error_type: str,
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
        bucket = (error_type or '').strip() or ERROR_TYPE_SESSION
        entry: dict[str, Any] = {
            'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'type': bucket,
            'message': str(message),
            'deviceId': device_id or '',
        }
        if assembler_id:
            entry['assemblerId'] = assembler_id
        if parser_id:
            entry['parserId'] = parser_id
        if data_len is not None:
            entry['dataLen'] = int(data_len)

        redis_client.write_batch(redis_cmd.error(bucket, entry, device_id=device_id))
    except Exception:
        pass
