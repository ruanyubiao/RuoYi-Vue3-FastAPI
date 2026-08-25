"""遥测批处理抽样、归档事件、分区月份工具。"""

from __future__ import annotations

from unittest.mock import MagicMock

from module_payload.parsers.tm_ingest_batch import (
    MAX_CURVE_FRAMES,
    PreparedTmFrame,
    _normalize_points,
    _sample_frames,
)
from module_payload.service.payload_telemetry_archive_service import build_archive_event, bytes_to_raw_hex
from module_payload.service.payload_tm_partition_service import (
    PARTITIONED_TABLES,
    _month_start_ms,
    _next_month,
    _partition_name,
)


def test_prepared_parse_key() -> None:
    fr = PreparedTmFrame(
        table_key='BIU:FF',
        name='n',
        payload=b'',
        raw_frame=b'',
        src_param='can:3:0:0',
        src_kind='can',
        parser_id='tm_can_biu',
        mgr=None,
        parse_key='',
    )
    assert fr.cfg_parse_key() == 'FF'
    fr.parse_key = 'FD'
    assert fr.cfg_parse_key() == 'FD'


def test_normalize_points() -> None:
    assert _normalize_points({'a': 1, 'b': '2.5', 'c': None, '': 3, 'd': 'x'}) == {
        'a': 1.0,
        'b': 2.5,
    }


def test_sample_frames_keeps_head_and_tail() -> None:
    frames = [
        PreparedTmFrame(
            table_key='FF',
            name=str(i),
            payload=b'',
            raw_frame=b'',
            src_param='',
            src_kind='can',
            parser_id='x',
            mgr=None,
        )
        for i in range(100)
    ]
    sampled = _sample_frames(frames, MAX_CURVE_FRAMES)
    assert len(sampled) <= MAX_CURVE_FRAMES
    assert sampled[0] is frames[0]
    assert sampled[-1] is frames[-1]
    assert _sample_frames(frames[:3], 40) == frames[:3]
    assert _sample_frames(frames, 1) == [frames[-1]]


def test_build_archive_event() -> None:
    ev = build_archive_event(
        ts_ms=1000,
        raw_frame=b'\xaa\xbb',
        points={'J1': 1.5, None: 1, 'skip': None},
        data_sub='ff',
        src_param='can:3:0:0',
        name='快遥',
    )
    assert ev['data_sub'] == 'FF'
    assert ev['raw_hex'] == 'AA BB'
    assert ev['points'] == {'J1': 1.5}
    assert ev['src_kind'] == 'can'
    assert ev['parsed_json']['name'] == '快遥'
    assert bytes_to_raw_hex(None) == ''
    assert bytes_to_raw_hex(b'') == ''


def test_partition_month_helpers() -> None:
    assert _partition_name(2026, 8) == 'p202608'
    assert _next_month(2026, 12) == (2027, 1)
    assert _next_month(2026, 1) == (2026, 2)
    assert _month_start_ms(2026, 1) < _month_start_ms(2026, 2)
    assert PARTITIONED_TABLES == ('payload_tm_frame', 'payload_tx_log')


def test_enqueue_sync_lpush() -> None:
    from module_payload.service.payload_telemetry_archive_service import PayloadTelemetryArchiveService

    redis = MagicMock()
    PayloadTelemetryArchiveService.enqueue_sync(redis, {'ts_ms': 1, 'points': {}})
    redis.lpush.assert_called()
