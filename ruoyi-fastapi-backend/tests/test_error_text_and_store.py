"""流水线错误文案与 Redis 错误存储。"""

from __future__ import annotations

from unittest.mock import MagicMock

from module_payload.error_text import checksum_mismatch, frame_len_mismatch, frame_len_over_limit
from module_payload.service.payload_error_store import normalize_error_type, push_pipeline_error
from module_payload import redis_keys as rk


def test_error_text_format() -> None:
    assert '数据长度：10' in frame_len_mismatch('相机', 10, 13, 8)
    assert '上限：512' in frame_len_over_limit('CAN 遥测', 600, 603, 512)
    assert checksum_mismatch('相机', 0xAB, 0xCD) == '相机 校验和错误: 计算：AB， 帧内：CD'
    assert checksum_mismatch('x', 1, 2, width=4).endswith('0002')


def test_normalize_error_type() -> None:
    assert normalize_error_type('parser') == 'tm'
    assert normalize_error_type('telemetry') == 'tm'
    assert normalize_error_type('camera_image') == 'camera'
    assert normalize_error_type('assembler') == 'assembler'
    assert normalize_error_type('unknown') == 'unknown'
    assert normalize_error_type('') == 'session'


def test_push_pipeline_error_writes_list_and_latest() -> None:
    redis = MagicMock()
    push_pipeline_error(
        redis,
        stage='assembler',
        message='组帧失败',
        device_id='serial:COM4',
        assembler_id='camera_image_d6',
        data_len=10,
    )
    ops = redis.write_batch.call_args[0][0]
    keys = [op.args[0] for op in ops]
    assert rk.error_type_latest_key('assembler') in keys
    assert rk.error_type_key('assembler') in keys
    assert rk.assembled_error_key('serial:COM4') in keys


def test_push_skips_empty_or_none() -> None:
    redis = MagicMock()
    push_pipeline_error(None, stage='tm', message='x')
    push_pipeline_error(redis, stage='tm', message='')
    redis.set.assert_not_called()
