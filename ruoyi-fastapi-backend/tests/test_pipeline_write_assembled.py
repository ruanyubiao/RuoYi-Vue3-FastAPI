"""assembled Redis 写入：latest + log。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from module_payload import redis_keys as rk
from module_payload.constants import ASSEMBLED_LOG_MAX
from module_payload.pipeline import assembled_entry, write_assembled_async, write_assembled_sync
from module_payload.collectors import redis_cmd_helper as redis_cmd


def _entry(device_id: str = 'can:0:0:0') -> dict:
    return assembled_entry(device_id, 'passthrough', b'\x01\x02', {'kind': 'raw'})


def test_write_assembled_sync_uses_write_batch() -> None:
    redis = MagicMock()
    entry = _entry()
    write_assembled_sync(redis, 'can:0:0:0', entry)
    redis.write_batch.assert_called_once()
    ops = redis.write_batch.call_args[0][0]
    assert ops == redis_cmd.assembled('can:0:0:0', entry)


def test_write_assembled_async() -> None:
    redis = AsyncMock()
    entry = _entry('udp:0.0.0.0:9000')
    asyncio.run(write_assembled_async(redis, 'udp:0.0.0.0:9000', entry))
    latest = rk.assembled_latest_key('udp:0.0.0.0:9000')
    log = rk.assembled_log_key('udp:0.0.0.0:9000')
    redis.set.assert_awaited_once()
    assert redis.set.await_args.args[0] == latest
    redis.lpush.assert_awaited_once_with(log, redis.set.await_args.args[1])
    redis.ltrim.assert_awaited_once_with(log, 0, ASSEMBLED_LOG_MAX - 1)


def test_assembled_entry_image_hex_empty() -> None:
    entry = assembled_entry('cam', 'camera_image_d6', b'\xff' * 10, {'kind': 'image'}, is_image=True)
    assert entry['hex'] == ''
    assert entry['len'] == 10
