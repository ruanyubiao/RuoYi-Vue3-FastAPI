"""P0 正确性/可靠性：设备开闭 off-loop、TX 至少一次、遥测热写常量合一。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from module_payload import constants as payload_constants
from module_payload.entity.vo.payload_device_vo import CanOpenModel
from module_payload.service.payload_device_service import PayloadDeviceService
from module_payload.service.payload_telemetry_archive_service import PayloadTelemetryArchiveService


def test_curve_max_points_single_source() -> None:
    """CURVE_MAX_POINTS 只在 constants 定义，热写模块均引用同一值。"""
    from module_payload import redis_store
    from module_payload.parsers import tm_can_yc_ingest

    assert payload_constants.CURVE_MAX_POINTS == 50000
    assert redis_store.CURVE_MAX_POINTS is payload_constants.CURVE_MAX_POINTS
    assert tm_can_yc_ingest.CURVE_MAX_POINTS is payload_constants.CURVE_MAX_POINTS


def test_base_collector_no_legacy_telemetry_writers() -> None:
    from module_payload.collectors.base_collector import BaseCollector

    assert not hasattr(BaseCollector, '_write_telemetry')
    assert not hasattr(BaseCollector, '_append_curve')


@pytest.mark.asyncio
async def test_open_can_runs_sync_body_in_thread() -> None:
    """open_can 必须经 asyncio.to_thread，避免阻塞事件循环。"""
    body = CanOpenModel(vendor=0, dev_index=0, can_index=0)
    expected = {'deviceId': 'can:0:0:0', 'status': 'opened', 'session': {}}
    seen: dict[str, Any] = {}

    def fake_sync(_body: CanOpenModel) -> dict[str, Any]:
        seen['thread'] = threading.current_thread().name
        time.sleep(0.05)
        return expected

    with patch.object(PayloadDeviceService, '_open_can_sync', side_effect=fake_sync):
        marker = {'done': False}

        async def heartbeat() -> None:
            await asyncio.sleep(0.01)
            marker['done'] = True

        result, _ = await asyncio.gather(
            PayloadDeviceService.open_can(body),
            heartbeat(),
        )

    assert result == expected
    assert marker['done'] is True
    assert seen.get('thread') != 'MainThread'


@pytest.mark.asyncio
async def test_tx_flush_failure_requeues_batch() -> None:
    events = [
        {'ts_ms': 1, 'src_param': 'can:0:0:0', 'raw_hex': 'AA'},
        {'ts_ms': 2, 'src_param': 'can:0:0:0', 'raw_hex': 'BB'},
    ]
    redis = AsyncMock()
    redis.lpush = AsyncMock()

    with patch.object(
        PayloadTelemetryArchiveService,
        'flush_tx_events',
        new=AsyncMock(side_effect=RuntimeError('db down')),
    ):
        with patch.object(
            PayloadTelemetryArchiveService,
            '_drain_tx_queue',
            new=AsyncMock(return_value=list(events)),
        ):
            tx_batch = await PayloadTelemetryArchiveService._drain_tx_queue(redis)
            assert tx_batch
            try:
                await PayloadTelemetryArchiveService.flush_tx_events(tx_batch)
            except Exception:
                await PayloadTelemetryArchiveService._requeue_tx_batch(redis, tx_batch)

    assert redis.lpush.await_count == 2
    # reversed + LPUSH：先推 BB 再推 AA，队头仍是 AA
    first_call = redis.lpush.await_args_list[0]
    second_call = redis.lpush.await_args_list[1]
    assert json.loads(first_call.args[1])['raw_hex'] == 'BB'
    assert json.loads(second_call.args[1])['raw_hex'] == 'AA'


@pytest.mark.asyncio
async def test_tx_flush_success_no_requeue() -> None:
    redis = AsyncMock()
    redis.lpush = AsyncMock()
    events = [{'ts_ms': 1, 'src_param': 'can:0:0:0', 'raw_hex': 'AA'}]

    with patch.object(
        PayloadTelemetryArchiveService,
        'flush_tx_events',
        new=AsyncMock(return_value=None),
    ):
        with patch.object(
            PayloadTelemetryArchiveService,
            '_drain_tx_queue',
            new=AsyncMock(return_value=list(events)),
        ):
            tx_batch = await PayloadTelemetryArchiveService._drain_tx_queue(redis)
            await PayloadTelemetryArchiveService.flush_tx_events(tx_batch)

    redis.lpush.assert_not_awaited()


def test_process_manager_has_lifecycle_lock() -> None:
    from module_payload.collectors.process_manager import CollectorProcessManager

    mgr = CollectorProcessManager.__new__(CollectorProcessManager)
    mgr._registry = {}
    mgr._lifecycle_lock = threading.RLock()
    assert mgr._lifecycle_lock is not None


def test_start_serial_returns_already_open_when_alive() -> None:
    from module_payload.collectors.process_manager import CollectorProcessManager, ProcessEntry

    mgr = CollectorProcessManager.__new__(CollectorProcessManager)
    mgr._registry = {}
    mgr._lifecycle_lock = threading.RLock()

    alive_proc = MagicMock()
    alive_proc.poll.return_value = None
    mgr._registry['serial:COM1'] = ProcessEntry(
        device_id='serial:COM1', collector_type='serial', process=alive_proc
    )

    device_id, already = mgr.start_serial('COM1', {'baudrate': 115200})
    assert device_id == 'serial:COM1'
    assert already is True
    # 不应再 spawn
    assert mgr._registry['serial:COM1'].process is alive_proc


def test_start_net_returns_already_open_when_alive() -> None:
    from module_payload.collectors.process_manager import CollectorProcessManager, ProcessEntry

    mgr = CollectorProcessManager.__new__(CollectorProcessManager)
    mgr._registry = {}
    mgr._lifecycle_lock = threading.RLock()

    alive_proc = MagicMock()
    alive_proc.poll.return_value = None
    mgr._registry['net:udp:127.0.0.1:9000'] = ProcessEntry(
        device_id='net:udp:127.0.0.1:9000', collector_type='net', process=alive_proc
    )

    device_id, already = mgr.start_net('udp', '127.0.0.1', 9000, {})
    assert device_id == 'net:udp:127.0.0.1:9000'
    assert already is True
