"""assembled Redis 写入：latest + log。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from module_payload.pipeline import assembled_entry, write_assembled_async, write_assembled_sync


def _entry(device_id: str = 'can:0:0:0') -> dict:
    return assembled_entry(device_id, 'passthrough', b'\x01\x02', {'kind': 'raw'})


def test_write_assembled_sync_uses_write_batch() -> None:
    redis = MagicMock()
    entry = _entry()
    write_assembled_sync(redis, 'can:0:0:0', entry)
    redis.write_batch.assert_not_called()


def test_write_assembled_async() -> None:
    redis = AsyncMock()
    entry = _entry('udp:0.0.0.0:9000')
    asyncio.run(write_assembled_async(redis, 'udp:0.0.0.0:9000', entry))
    redis.set.assert_not_awaited()
    redis.lpush.assert_not_awaited()
    redis.ltrim.assert_not_awaited()


def test_assembled_entry_image_hex_empty() -> None:
    entry = assembled_entry('cam', 'camera_image_d6', b'\xff' * 10, {'kind': 'image'}, is_image=True)
    assert entry['hex'] == ''
    assert entry['len'] == 10
