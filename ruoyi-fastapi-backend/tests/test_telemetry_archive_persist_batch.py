"""遥测归档 _persist_batch / _raw_hex_from_event。"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from module_payload.constants import DATA_KIND_TM, PARSER_CAMERA_SC_LINK41EP, PARSER_TM_CAN_BIU
from module_payload.entity.do.payload_tm_frame_do import PayloadTmFrame
from module_payload.service.payload_telemetry_archive_service import PayloadTelemetryArchiveService


def test_raw_hex_from_event_prefers_raw_hex() -> None:
    ev = {'raw_hex': 'AA BB', 'raw_bin_b64': base64.b64encode(b'\x01\x02').decode()}
    assert PayloadTelemetryArchiveService._raw_hex_from_event(ev) == 'AA BB'


def test_raw_hex_from_event_from_b64() -> None:
    ev = {'raw_bin_b64': base64.b64encode(b'\xaa\xbb').decode()}
    assert PayloadTelemetryArchiveService._raw_hex_from_event(ev) == 'AA BB'


def test_raw_hex_from_event_invalid_b64() -> None:
    assert PayloadTelemetryArchiveService._raw_hex_from_event({'raw_bin_b64': '!!!'}) == ''


@pytest.mark.asyncio
async def test_persist_batch_can_with_points() -> None:
    db = MagicMock()
    db.commit = AsyncMock()
    events = [
        {
            'ts_ms': 1_700_000_000_000,
            'data_kind': DATA_KIND_TM,
            'data_sub': 'ff',
            'src_kind': 'can',
            'src_param': 'can:3:0:0',
            'parser_id': PARSER_TM_CAN_BIU,
            'raw_hex': 'AA BB CC',
            'points': {'JGB001': 12.5},
            'parsed_json': {'name': '快遥'},
            'field_count': 1,
            'cfg_version': 'v1',
        }
    ]
    await PayloadTelemetryArchiveService._persist_batch(db, events)
    db.add_all.assert_called_once()
    rows: list[PayloadTmFrame] = db.add_all.call_args.args[0]
    assert len(rows) == 1
    row = rows[0]
    assert row.data_sub == 'FF'
    assert row.src_kind == 'can'
    assert row.src_param == 'can:3:0:0'
    assert row.raw_hex == 'AA BB CC'
    assert row.points_json == {'JGB001': 12.5}
    assert row.field_count == 1
    assert row.cfg_version == 'v1'
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_batch_skips_non_mysql_sources() -> None:
    db = MagicMock()
    db.commit = AsyncMock()
    events = [
        {
            'ts_ms': 1000,
            'src_kind': 'serial',
            'src_param': 'serial:COM3',
            'parser_id': PARSER_CAMERA_SC_LINK41EP,
            'points': {'CAM001': 1.0},
            'raw_hex': '01',
        },
        {
            'ts_ms': 1001,
            'src_kind': 'can',
            'src_param': 'can:0:0:0',
            'parser_id': PARSER_TM_CAN_BIU,
            'points': {'J1': 2.0},
            'raw_hex': '02',
            'data_sub': 'FF',
        },
    ]
    await PayloadTelemetryArchiveService._persist_batch(db, events)
    rows: list[PayloadTmFrame] = db.add_all.call_args.args[0]
    assert len(rows) == 1
    assert rows[0].src_kind == 'can'
    assert rows[0].points_json == {'J1': 2.0}


@pytest.mark.asyncio
async def test_persist_batch_backfill_points_from_numeric_fields() -> None:
    db = MagicMock()
    db.commit = AsyncMock()
    events = [
        {
            'ts_ms': 2000,
            'data_sub': 'D8',
            'src_param': 'can:1:0:0',
            'parser_id': PARSER_TM_CAN_BIU,
            'numeric_fields': [
                {'field_id': 'CAM001', 'value_num': 3.14},
                {'field_id': None, 'value_num': 9},
                {'field_id': 'X', 'value_num': 'bad'},
            ],
            'raw_hex': '33',
        }
    ]
    await PayloadTelemetryArchiveService._persist_batch(db, events)
    rows: list[PayloadTmFrame] = db.add_all.call_args.args[0]
    assert len(rows) == 1
    assert rows[0].points_json == {'CAM001': 3.14}
    assert rows[0].field_count == 1


@pytest.mark.asyncio
async def test_persist_batch_backfill_points_from_parsed_json() -> None:
    db = MagicMock()
    db.commit = AsyncMock()
    events = [
        {
            'ts_ms': 3000,
            'data_sub': 'FF',
            'src_param': 'can:2:0:0',
            'parser_id': PARSER_TM_CAN_BIU,
            'parsed_json': {
                'fields': [
                    {'id': 'JGB001', 'calc_val': 7.5},
                    {'id': '', 'calc_val': 1},
                    {'id': 'J2', 'show': 'not-a-number'},
                ]
            },
            'raw_hex': '44',
        }
    ]
    await PayloadTelemetryArchiveService._persist_batch(db, events)
    rows: list[PayloadTmFrame] = db.add_all.call_args.args[0]
    assert len(rows) == 1
    assert rows[0].points_json == {'JGB001': 7.5}
    assert rows[0].field_count == 1
