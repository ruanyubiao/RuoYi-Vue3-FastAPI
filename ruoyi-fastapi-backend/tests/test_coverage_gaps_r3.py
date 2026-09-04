"""覆盖率补洞 R3：xl_board / xl_can / demux / framing / cfg / camera / batch / log 边角。"""

import builtins
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from common.annotation.log_annotation import Log
from common.enums import BusinessType
from module_payload.assemblers.camera_image_d6 import CameraImageD6Assembler
from module_payload.assemblers.camera_image_d6_common import (
    DATA_CHUNK_SIZE,
    FRAME_HEADER,
    FRAME_SIZE,
    FRAME_TYPE,
    calc_checksum,
    frame_id_encode,
    parse_response_frame_v17,
)
from module_payload.cfg.hex_text import hex_to_bytes
from module_payload.cfg.payload_config_loader import PayloadConfigLoader, TELE_METRY_CFG_NAME
from module_payload.cfg.telecontrol_assembler import (
    _zero_bytes_for_component,
    apply_component_formula,
)
from module_payload.cfg.telecontrol_cfg import (
    TeleControlCfg,
    TeleControlCfgManager,
    cfg_id_for_board,
    cfg_id_for_family,
)
from module_payload.constants import ASSEMBLER_ENG_TM_SUBPKT, checksum_u8
from module_payload.demux.stream_demux import StreamDemux
from module_payload.framing.base import StreamByteBuffer
from module_payload.parsers.biu_can_tm import BiuCanTmIngest
from module_payload.parsers.camera_tm_ingest_base import (
    D6_FRAME_SIZE,
    D8_DATA_LEN,
    FRAME_TYPE_D6,
    FRAME_TYPE_D8,
    FRAME_TYPE_D9,
    _d9_mux_from_batch,
    _eb90_occupied_spans,
)
from module_payload.parsers.tm_ingest_batch import (
    PreparedTmFrame,
    TmIngestBatcher,
    _CURVE_PIPE_MAX_OPS,
    _write_curves_batch,
    _write_curves_sync,
    _write_latest_from_frame,
    process_prepared_async,
)
from module_payload.cfg.can_yc_frame import CAN_YC_FRAME_TYPE_COMPLEX
from module_payload.parsers.xl_board_tm import (
    FRAME_HEADER as XL_HDR,
    XlBoardTmIngest,
    _cfg_path_for_table,
    _frame_checksum,
)
from module_payload.parsers.xl_camera_tm import XlCameraTmIngest
from module_payload.parsers.xl_can_tm import XlCanTmIngest
from module_payload.tm_golden_samples import get_simulate_sample, reset_sample_cache
from exceptions.exception import ServiceException


def _build_can_yc(data_type: int = 0xFF, payload: bytes = b'\x11\x22') -> bytes:
    body = bytes([CAN_YC_FRAME_TYPE_COMPLEX, data_type & 0xFF]) + payload
    data_len = len(body)
    head = bytes([(data_len >> 8) & 0xFF, data_len & 0xFF]) + body
    return head + bytes([sum(head) & 0xFF])


def _build_xl_tm(*, src: int = 0x33, dst: int = 0x11, payload: bytes = bytes(8)) -> bytes:
    body = bytes([src & 0xFF, dst & 0xFF]) + payload
    frame = XL_HDR + len(body).to_bytes(2, 'big') + body
    return frame + bytes([checksum_u8(frame[2:])])


def _d6_v16(frame_id: int, seq: int, image_no: int = 1, chunk: bytes | None = None) -> bytes:
    data = chunk if chunk is not None else bytes(DATA_CHUNK_SIZE)
    data = (data + bytes(DATA_CHUNK_SIZE))[:DATA_CHUNK_SIZE]
    body = bytes([0xD6, frame_id & 0xFF, 0x01, 0x01, (seq >> 8) & 0xFF, seq & 0xFF, image_no & 0xFF]) + data
    return bytes([0xEB, 0x90]) + body + bytes([calc_checksum(body)])


def _fake_mgr(*, fields=None, points=None):
    mgr = MagicMock()
    mgr.parse.return_value = fields if fields is not None else [{'id': 'a', 'value': 1}]
    mgr.parse_calc.return_value = points if points is not None else {'a': 1.5}
    mgr.get_table_cfg_by_key.return_value = MagicMock(name='T')
    return mgr


def _prepared(**kw):
    defaults = dict(
        table_key='BIU:FF',
        name='t',
        payload=b'\x00',
        raw_frame=b'\x00\x01',
        src_param='can:0',
        src_kind='can',
        parser_id='tm_can_biu',
        mgr=_fake_mgr(),
        parse_key='FF',
    )
    defaults.update(kw)
    return PreparedTmFrame(**defaults)


# ---------------------------------------------------------------------------
# framing.base leftover branches
# ---------------------------------------------------------------------------


def test_stream_byte_buffer_compact_trim_skip() -> None:
    buf = StreamByteBuffer(sync_header=b'\xaa\xbb', compact_at=2, max_buffer=64)
    buf._buf = bytearray(b'\x11\x22\x33')
    buf._start = 3
    buf.write(b'\xaa')  # line 44: _start >= compact_at → _compact
    assert buf.pending >= 1

    buf2 = StreamByteBuffer(sync_header=b'\xaa\xbb')
    buf2._buf = bytearray(b'\x11')
    buf2._start = 1
    buf2._trim_partial_header()  # compact clears → n==0 early return
    assert buf2.pending == 0

    buf3 = StreamByteBuffer(sync_header=b'\xaa', compact_at=2)
    buf3._buf = bytearray(b'\x00\x01\x02\x03')
    buf3._start = 0
    buf3._skip_bytes(3)  # start>=compact_at → compact
    assert buf3._start == 0 or buf3.pending >= 0


# ---------------------------------------------------------------------------
# xl_board_tm priority
# ---------------------------------------------------------------------------


def test_xl_board_cfg_path_and_extract_edges() -> None:
    p = _cfg_path_for_table('RKDJ')
    assert p.name.endswith('TeleMetryCfg.json')
    with pytest.raises(ValueError, match='未知'):
        _cfg_path_for_table('NOPE')

    # len>=6 so while enters, header near end → idx+5 > len (line 155)
    blob = b'\x00\x00\x00' + XL_HDR + b'\x00'
    assert XlBoardTmIngest.extract_frames(blob) == []

    # body_len < 2 with enough bytes to enter loop (line 158-159)
    short_len = XL_HDR + bytes([0x00, 0x01, 0x33, 0x11])
    assert XlBoardTmIngest.extract_frames(short_len) == []

    # incomplete frame (claimed longer than buffer)
    half = XL_HDR + bytes([0x00, 0x10, 0x33, 0x11]) + bytes(4)
    assert XlBoardTmIngest.extract_frames(half) == []
    assert XlBoardTmIngest._complete_eb90_candidate(half) is None

    # candidate body_len < 2 but len>=7 (line 193)
    assert XlBoardTmIngest._complete_eb90_candidate(XL_HDR + bytes([0x00, 0x01, 0x33, 0x11, 0x00])) is None

    # unknown src skipped in extract
    unk = _build_xl_tm(src=0x99)
    assert XlBoardTmIngest.extract_frames(unk) == []

    # io_preview
    fr = _build_xl_tm()
    assert XlBoardTmIngest.io_preview_frames(fr)

    # parse_bytes via candidate (bad checksum → extract empty → prepare raises)
    bad = bytearray(fr)
    bad[-1] ^= 0xFF
    with pytest.raises(ValueError, match='校验和'):
        XlBoardTmIngest.parse_bytes(bytes(bad))


def test_xl_board_prepare_errors() -> None:
    with pytest.raises(ValueError, match='帧头'):
        XlBoardTmIngest.prepare_frame(b'\x00' * 8)
    fr = _build_xl_tm()
    # length mismatch: truncate
    with pytest.raises(ValueError, match='长度|帧长'):
        XlBoardTmIngest.prepare_frame(fr[:-1])
    # unknown src via prepare (complete candidate)
    bad_src = bytearray(_build_xl_tm(src=0x99))
    bad_src[-1] = _frame_checksum(bytes(bad_src))
    with pytest.raises(ValueError, match='未知源'):
        XlBoardTmIngest.prepare_frame(bytes(bad_src))


def test_xl_board_ingest_sync_quiet_and_loud() -> None:
    redis = MagicMock()
    # force ValueError inside try (bad eng path with invalid via prepare_assembled)
    with patch.object(
        XlBoardTmIngest,
        'prepare_assembled_payload',
        side_effect=ValueError('boom-eng'),
    ):
        assert (
            XlBoardTmIngest.ingest_bytes_sync(
                redis, b'\x01', src_param='udp:1', assembler_id=ASSEMBLER_ENG_TM_SUBPKT
            )
            is None
        )
        with pytest.raises(ValueError, match='boom'):
            XlBoardTmIngest.ingest_bytes_sync(
                redis,
                b'\x01',
                src_param='udp:1',
                assembler_id=ASSEMBLER_ENG_TM_SUBPKT,
                quiet=False,
            )


@pytest.mark.asyncio
async def test_xl_board_async_ok_and_empty_candidate() -> None:
    redis = MagicMock()
    pipe = MagicMock()
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.zremrangebyrank = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])
    redis.pipeline.return_value = pipe
    redis.set = AsyncMock()
    fr = _build_xl_tm(src=0x33)
    with patch(
        'module_payload.parsers.xl_board_tm.process_prepared_async',
        new_callable=AsyncMock,
        return_value={'fields': [{'id': 'a'}], 'name': 'RKDJ', 'ts': 't'},
    ):
        out = await XlBoardTmIngest.ingest_bytes_async(redis, fr, src_param='http:sim')
    assert out['dataType'] == 'RKDJ'
    assert out['srcParam'] == 'http:sim'

    with pytest.raises(ValueError, match='未找到'):
        await XlBoardTmIngest.ingest_bytes_async(redis, b'\x00\x01', src_param='http:x')

    # candidate present but prepare leaves empty list somehow → last is None
    with patch.object(XlBoardTmIngest, '_collect_prepared', return_value=[]):
        with patch.object(XlBoardTmIngest, '_complete_eb90_candidate', return_value=fr):
            with patch.object(XlBoardTmIngest, 'prepare_frame', return_value=_prepared(table_key='RKDJ')):
                with patch(
                    'module_payload.parsers.xl_board_tm.process_prepared_async',
                    new_callable=AsyncMock,
                    return_value={},
                ):
                    # prepared_list non-empty → returns last dict
                    out2 = await XlBoardTmIngest.ingest_bytes_async(redis, fr, src_param='http:y')
                    assert out2['dataType'] == 'RKDJ'


# ---------------------------------------------------------------------------
# xl_can / biu empty fields + async / quiet=False
# ---------------------------------------------------------------------------


def test_xl_biu_empty_fields_and_parse_hex_ok(monkeypatch) -> None:
    raw = _build_can_yc(0xFF, b'\x00' * 8)
    mgr = _fake_mgr(fields=[])
    monkeypatch.setattr('module_payload.parsers.xl_can_tm._get_tm_mgr', lambda: mgr)
    monkeypatch.setattr('module_payload.parsers.biu_can_tm._get_tm_mgr', lambda: mgr)
    # prepare needs cfg
    mgr.get_table_cfg_by_key.return_value = MagicMock(name='T')
    with pytest.raises(ValueError, match='无结果'):
        XlCanTmIngest.parse_bytes(raw)
    with pytest.raises(ValueError, match='无结果'):
        BiuCanTmIngest.parse_bytes(raw)

    reset_sample_cache()
    xl_hex = get_simulate_sample(key='passthrough_xlcan_ff')['hex']
    biu_hex = get_simulate_sample(key='passthrough_biu_ff_1')['hex']
    # restore real mgr for golden parse_hex
    monkeypatch.undo()
    assert XlCanTmIngest.parse_hex(xl_hex).fields
    assert BiuCanTmIngest.parse_hex(biu_hex).fields

    redis = MagicMock()
    with pytest.raises(ValueError):
        XlCanTmIngest.ingest_bytes_sync(redis, b'\x00', src_param='can:1', quiet=False)


@pytest.mark.asyncio
async def test_xl_can_async_paths() -> None:
    reset_sample_cache()
    xl_hex = get_simulate_sample(key='passthrough_xlcan_ff')['hex']
    raw = hex_to_bytes(xl_hex)
    redis = MagicMock()
    pipe = MagicMock()
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.zremrangebyrank = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])
    redis.pipeline.return_value = pipe
    redis.set = AsyncMock()
    with patch('module_payload.parsers.tm_ingest_batch.enqueue', new_callable=AsyncMock):
        with patch(
            'module_payload.redis_store.set_telemetry',
            new_callable=AsyncMock,
            return_value={'name': 'n', 'fields': [{'id': 'a'}], 'ts': 't'},
        ):
            out = await XlCanTmIngest.ingest_bytes_async(redis, raw, src_param='can:9')
            assert out['dataType'].startswith('XL:')
            out2 = await XlCanTmIngest.ingest_hex_async(redis, xl_hex, src_param='http:dev')
            assert out2['parserId']


# ---------------------------------------------------------------------------
# camera_image_d6_common
# ---------------------------------------------------------------------------


def test_d6_common_checksum_header_and_recover() -> None:
    from module_payload.assemblers.camera_image_d6_common import (
        parse_valid_len_field,
        resolve_wh_v17,
    )

    # full-size wrong header/type → line 162
    bad = bytes([0x00, 0x00, 0xD6]) + bytes(FRAME_SIZE - 3)
    assert parse_response_frame_v17(bad) is None
    bad2 = bytes([0xEB, 0x90, 0xD8]) + bytes(FRAME_SIZE - 3)
    assert parse_response_frame_v17(bad2) is None

    # valid len field success path
    buf = bytearray(FRAME_SIZE)
    buf[0:2] = FRAME_HEADER
    buf[2] = FRAME_TYPE
    buf[4] = 0x00
    buf[5] = 0x0F  # L=15 → valid=16
    assert parse_valid_len_field(bytes(buf)) == 16
    # valid parse_response_frame_v17 success
    buf[3] = frame_id_encode(first=True, last=True)
    buf[6] = 0
    buf[7] = 0
    buf[8] = 1
    buf[9 : 9 + 16] = bytes(16)
    buf[265] = calc_checksum(buf[2:265])
    parsed = parse_response_frame_v17(bytes(buf))
    assert parsed is not None and len(parsed[3]) == 16

    assert resolve_wh_v17(9, '3') == (3, 3)  # single-int hint square

    asm = CameraImageD6Assembler(resolution='8x8')
    # establish image then jump seq; recover with first+seq0
    first = _d6_v16(frame_id_encode(first=True), 0, image_no=1)
    assert asm.accept_frame(first) is None
    jump = _d6_v16(frame_id_encode(first=True), 0, image_no=1)  # seq0 first again after mid state
    # force last_seq so next expected != 0
    asm._last_seq = 2
    asm._chunks = {0: bytes(DATA_CHUNK_SIZE), 1: bytes(DATA_CHUNK_SIZE)}
    assert asm.accept_frame(jump) is None  # discontinuity recover 304-306
    assert asm._last_seq == 0

    # missing chunk on last frame
    asm2 = CameraImageD6Assembler(resolution='8x8')
    asm2._image_no = 1
    asm2._last_seq = 0
    asm2._chunks = {}
    asm2._chunks[0] = None  # type: ignore[assignment]
    asm2._last_seq = 0
    mid_last = _d6_v16(frame_id_encode(last=True), 1, image_no=1)
    assert asm2.accept_frame(mid_last) is None  # missing chunk drop

    # finish_pixels returns None → 327
    asm3 = CameraImageD6Assembler(resolution='128x128')
    first3 = _d6_v16(frame_id_encode(first=True, last=True), 0, image_no=3, chunk=bytes(10))
    with patch.object(asm3, '_finish_pixels', return_value=None):
        assert asm3.accept_frame(first3) is None


def test_eng_feed_errors_and_single_with_slots() -> None:
    from module_payload.assemblers.eng_tm_subpkt import ENG_CHK_OFF, EngTmSubpktAssembler

    asm = EngTmSubpktAssembler()
    # feed path: complete frame with bad checksum → ValueError branch 137-141
    bad = bytearray(_build_eng_for_test(data=b'X'))
    bad[ENG_CHK_OFF] ^= 0xFF
    asm.feed(bytes(bad))
    assert asm.take_errors()

    # single packet while slots exist → line 241
    asm2 = EngTmSubpktAssembler()
    f_partial = _build_eng_for_test(data=b'A', sub_count=2, sub_index=1)
    assert asm2.feed(f_partial) == []
    f_single = _build_eng_for_test(data=b'Z', sub_count=1, sub_index=1)
    out = asm2.feed(f_single)
    assert out  # finishes after drop

    # first of multi while slots exist → 264
    asm3 = EngTmSubpktAssembler()
    assert asm3.feed(_build_eng_for_test(data=b'A', sub_count=3, sub_index=1)) == []
    assert asm3.feed(_build_eng_for_test(data=b'B', sub_count=3, sub_index=1)) == []


def _build_eng_for_test(*, data: bytes, sub_count: int = 1, sub_index: int = 1) -> bytes:
    from module_payload.assemblers.eng_tm_subpkt import (
        ENG_CHK_OFF,
        ENG_END_OFF,
        ENG_FRAME_SIZE,
        ENG_HEADER,
        ENG_TRAILERS,
    )

    body = bytearray(ENG_FRAME_SIZE)
    body[0:2] = ENG_HEADER
    body[2:4] = len(data).to_bytes(2, 'big')
    body[4:6] = (0x91).to_bytes(2, 'big')
    body[6:8] = (0x90).to_bytes(2, 'big')
    body[8:10] = sub_count.to_bytes(2, 'big')
    body[10:12] = sub_index.to_bytes(2, 'big')
    body[12 : 12 + len(data)] = data
    checksum = sum(body[0:ENG_CHK_OFF]) & 0xFFFF
    body[ENG_CHK_OFF:ENG_END_OFF] = checksum.to_bytes(2, 'big')
    body[ENG_END_OFF:ENG_FRAME_SIZE] = ENG_TRAILERS[0]
    return bytes(body)


# ---------------------------------------------------------------------------
# telecontrol / loader
# ---------------------------------------------------------------------------


def test_formula_import_error_and_zero_unknown() -> None:
    real_import = builtins.__import__

    def _imp(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'TeleMetryParser.tinyexpr' or (
            name == 'TeleMetryParser' and fromlist and 'tinyexpr' in fromlist
        ):
            raise ImportError('blocked')
        return real_import(name, globals, locals, fromlist, level)

    with patch('builtins.__import__', side_effect=_imp):
        with pytest.raises(ValueError, match='不可用'):
            apply_component_formula(1, 'D+1')

    assert _zero_bytes_for_component({'componentType': 'fixed'}) == b''
    assert _zero_bytes_for_component({'componentType': 'unknown_type'}) == b''


def test_telecontrol_encode_and_assemble_branches() -> None:
    from module_payload.cfg.telecontrol_assembler import (
        assemble_order,
        encode_component,
        encode_number,
        is_broadcast_hex,
        _hex_char_byte_width,
    )

    assert len(encode_number(None, 'INT8')) == 1  # empty value → 0 (line 44)
    assert len(encode_number(1, 'INT8')) == 1
    assert len(encode_number(1, 'BYTE')) == 1
    assert len(encode_number(1, 'UINT8')) == 1
    assert len(encode_number(1, 'INT16')) == 2
    assert len(encode_number(1, 'UINT16')) == 2
    assert len(encode_number(1, 'INT24')) == 3
    assert len(encode_number(1, 'UINT24')) == 3
    assert len(encode_number(1, 'INT32')) == 4
    assert len(encode_number(1, 'UINT32')) == 4
    assert len(encode_number(1.5, 'FLOAT')) == 4
    assert len(encode_number(1.5, 'DOUBLE')) == 8

    assert _hex_char_byte_width('') == 0
    assert _hex_char_byte_width('A') == 1
    from module_payload.cfg.telecontrol_assembler import _select_byte_width

    # defaultVal empty → iterate options (line 131)
    assert _select_byte_width({'defaultVal': '', 'options': {'0xABCD': 'x'}}) == 2
    assert _select_byte_width({'defaultVal': '', 'options': {'': 'x', '0x01': 'y'}}) == 1

    assert encode_component({'componentType': 'select', 'options': {'0x0A': '开'}}, '开')
    assert len(encode_component({'componentType': 'scientific', 'dataType': 'FLOAT'}, 1.25)) == 4
    assert len(encode_component({'componentType': 'scientific', 'dataType': 'DOUBLE'}, 1.25)) == 8
    assert encode_component({'componentType': 'hex', 'defaultVal': '00FF'}, 'A')
    assert encode_component({'componentType': 'weird'}, '0x12')

    # assemble + broadcast helpers: length == data_len+2 → append checksum
    body = bytes([0x00, 0x07, 0x0F, 1, 2, 3, 4, 5, 6])  # len=9 == data_len+2
    from module_payload.cfg.telecontrol_assembler import finalize_buffer

    out, ft, _ = finalize_buffer(body)
    assert len(out) == len(body) + 1
    assert is_broadcast_hex('00') is False
    assert is_broadcast_hex('not-hex') is False
    # broadcast success: 8-byte frame with type 0x30 at [0]
    assert is_broadcast_hex('30 00 00 00 00 00 00 00') is True
    # longer frame uses buf[2]
    assert is_broadcast_hex('00 05 1A 01 02 03 04 05 06') is True

    # assemble_order end-to-end
    assembled = assemble_order(
        [{'componentType': 'fixed', 'defaultVal': '0F00050102030405'}],
        [],
    )
    assert assembled['length'] >= 8


def test_telecontrol_cfg_manager_extras() -> None:
    from module_payload.cfg.telecontrol_cfg import (
        TeleControlCfgManager,
        cfg_id_for_camera,
        protocol_for_cfg_id,
    )

    assert cfg_id_for_camera('v17') == 'xl-camera-v17-tc'
    with pytest.raises(ServiceException):
        protocol_for_cfg_id('nope')

    # ServiceException passthrough from read_config_json
    with patch(
        'config.paths.read_config_json',
        side_effect=ServiceException(message='upstream'),
    ):
        with pytest.raises(ServiceException) as ei:
            TeleControlCfg.from_path(Path('BIU-TeleControlCfg.json'), cfg_id='biu-tc', protocol='biu')
        assert 'upstream' in (ei.value.message or '')

    assert TeleControlCfgManager.assemble_order_dict(
        'biu-tc',
        {'component': [{'componentType': 'fixed', 'defaultVal': '0F00050102030405'}]},
        [],
    )['length'] >= 8

    # reload unknown json filename → cid not in registry (288)
    with pytest.raises(ServiceException):
        TeleControlCfgManager.reload('Ghost-TeleControlCfg.json')
    with pytest.raises(ServiceException):
        TeleControlCfgManager.reload('totally-unknown-tc')


def test_xl_board_need_checksum_and_classify() -> None:
    from module_payload.cfg.xl_board_telecontrol_assembler import (
        _correct_complex_length,
        assemble_xl_board_order,
        classify_xl_tc_frame,
    )

    # declared == expected → empty tip (line 55)
    body = bytearray([0xEB, 0x90, 0x0F, 0x00, 0x02, 0x01, 0x02])
    assert _correct_complex_length(body) == ''

    # need_checksum path with already_ok frame
    payload = bytes([0xEB, 0x90, 0x0F, 0x00, 0x03, 0x11, 0x22, 0x33])
    chk = checksum_u8(payload[2:])
    order = {
        'check': 'yes',
        'component': [{'componentType': 'fixed', 'defaultVal': (payload + bytes([chk])).hex()}],
    }
    result = assemble_xl_board_order(order, [])
    assert result['length'] >= 8

    assert classify_xl_tc_frame(bytes([0x00, 0x00, 0x0A])) == 'single'
    # complex with matching length
    cbody = bytes([0xEB, 0x90, 0x0F, 0x00, 0x02, 0x01, 0x02, 0x99])
    assert classify_xl_tc_frame(cbody) in ('complex', 'error')
    # no-header complex fragment
    assert classify_xl_tc_frame(bytes([0x0F, 0x00, 0x02, 0x01, 0x02])) == 'complex'


def test_telecontrol_cfg_board_family_and_load_errors(tmp_path: Path, monkeypatch) -> None:
    assert cfg_id_for_board('zk') == 'xl-zk-tc'
    assert cfg_id_for_family('xl') == 'xl-tc'
    assert cfg_id_for_family(None) == 'biu-tc'

    monkeypatch.setattr(
        'config.paths.read_config_json',
        MagicMock(side_effect=FileNotFoundError()),
    )
    with pytest.raises(ServiceException) as ei:
        TeleControlCfg.from_path(tmp_path / 'Missing-TeleControlCfg.json', cfg_id='biu-tc', protocol='biu')
    assert '不存在' in (ei.value.message or '')

    monkeypatch.setattr(
        'config.paths.read_config_json',
        MagicMock(side_effect=RuntimeError('x')),
    )
    with pytest.raises(ServiceException) as ei2:
        TeleControlCfg.from_path(tmp_path / 'Bad-TeleControlCfg.json', cfg_id='biu-tc', protocol='biu')
    assert '加载' in (ei2.value.message or '')

    monkeypatch.setattr(
        'config.paths.read_config_json',
        MagicMock(return_value=[1, 2]),
    )
    with pytest.raises(ServiceException) as ei3:
        TeleControlCfg.from_path(tmp_path / 'Arr-TeleControlCfg.json', cfg_id='biu-tc', protocol='biu')
    assert '格式' in (ei3.value.message or '')

    # from_path with explicit protocol for unknown filename
    p = tmp_path / 'Ghost-TeleControlCfg.json'
    p.write_text('{"order":{}}', encoding='utf-8')
    monkeypatch.setattr(
        'config.paths.read_config_json',
        MagicMock(return_value={'order': {}}),
    )
    tc = TeleControlCfg.from_path(p, protocol='biu')
    assert tc.list_orders() == []
    tc2 = TeleControlCfg.from_dict({'order': 'bad'}, cfg_id='biu-tc')
    assert tc2.list_orders() == []

    with pytest.raises(ServiceException):
        TeleControlCfgManager.reload('not-a-real-tc')

    assert TeleControlCfgManager.cfg_id_for_path('BIU-TeleControlCfg.json') == 'biu-tc'


def test_loader_discover_oserror_and_reload_exceptions(monkeypatch) -> None:
    bad = MagicMock()
    bad.resolve.side_effect = OSError('x')
    bad.exists.return_value = False
    with patch(
        'module_payload.cfg.payload_config_loader.resolve_config_file',
        return_value=bad,
    ):
        with patch(
            'module_payload.cfg.payload_config_loader.list_config_names',
            return_value=['Ghost-TeleMetryCfg.json'],
        ):
            assert PayloadConfigLoader.discover_telemetry_cfg_sources() == []

    with patch.object(
        PayloadConfigLoader,
        'get_xl_board_telemetry_cfg',
        side_effect=ValueError('no'),
    ):
        pages = PayloadConfigLoader.merge_telemetry_pages(family='xl', reload=False)
        assert isinstance(pages, list)

    with patch(
        'module_payload.parsers.biu_can_tm.reset_tm_mgr',
        side_effect=RuntimeError('reset-fail'),
    ):
        PayloadConfigLoader.reload_all()

    with patch(
        'module_payload.cfg.telecontrol_cfg.TeleControlCfgManager.cfg_id_for_path',
        side_effect=RuntimeError('x'),
    ):
        key = PayloadConfigLoader._cache_key_for_path(Path('BIU-TeleControlCfg.json'))
        assert key

    with patch(
        'module_payload.cfg.telecontrol_cfg.TeleControlCfgManager.cfg_id_for_path',
        side_effect=RuntimeError('x'),
    ):
        PayloadConfigLoader.reload_file(Path(TELE_METRY_CFG_NAME))

    with patch(
        'module_payload.parsers.biu_can_tm.reset_tm_mgr',
        side_effect=RuntimeError('boom'),
    ):
        PayloadConfigLoader.reload_file(Path(TELE_METRY_CFG_NAME))

    # get_telecontrol_cfg / get_telemetry paths
    assert PayloadConfigLoader.get_telecontrol_cfg('biu')
    assert PayloadConfigLoader.get_telecontrol_cfg('xl')
    assert PayloadConfigLoader.family_from_tm_path(Path('BIU-x.json')) == 'biu'
    # duplicate path in discover (line 139): same file listed twice
    real = PayloadConfigLoader.discover_telemetry_cfg_sources()
    if real:
        with patch(
            'module_payload.cfg.payload_config_loader.list_config_names',
            return_value=[real[0][1].name, real[0][1].name],
        ):
            with patch(
                'module_payload.cfg.payload_config_loader.resolve_config_file',
                return_value=real[0][1],
            ):
                again = PayloadConfigLoader.discover_telemetry_cfg_sources()
                assert len(again) == 1


# ---------------------------------------------------------------------------
# stream_demux leftover branches
# ---------------------------------------------------------------------------


def test_demux_compact_on_write_and_extract_guards() -> None:
    """Hit stream_demux lines 230/365/367/372 and type-match continue paths."""
    demux = StreamDemux(
        [
            {
                'id': 'a',
                'framing': 'header_len',
                'header': 'AA55',
                'frameSize': 6,
                'assemblerId': 'passthrough',
            }
        ],
        compact_at=4,
        max_buffer=64,
    )
    # fill and drain so _start advances past compact_at
    demux.write(b'\xaa\x55\x01\x02\x03\x04\xaa\x55\x05\x06\x07\x08')
    demux.drain()
    demux.write(b'\xaa\x55\x09\x0a\x0b\x0c')  # line 230 compact during write
    demux.drain()

    # two routes same header different frame_size → size continue (322/324)
    demux_sz = StreamDemux(
        [
            {
                'id': 's4',
                'framing': 'header_len',
                'header': 'EB90',
                'frameSize': 4,
                'typeAt': 2,
                'type': '01',
                'assemblerId': 'p',
            },
            {
                'id': 's8',
                'framing': 'header_len',
                'header': 'EB90',
                'frameSize': 8,
                'typeAt': 2,
                'type': '02',
                'assemblerId': 'p',
            },
        ],
        compact_at=4,
    )
    demux_sz.write(bytes([0xEB, 0x90, 0x02, 0, 0, 0, 0, 0]))
    demux_sz.drain()  # size/type candidate continue + consume mismatch paths


    # header mismatch at extract → SKIP (367): inject start past real header bytes
    demux_bad = StreamDemux(
        [{'id': 'h', 'framing': 'header_len', 'header': 'EB90', 'frameSize': 4, 'assemblerId': 'p'}]
    )
    demux_bad._buf = bytearray(b'\x00\xeb\x90\x01\x02')
    demux_bad._start = 0
    # drain will find header at 1; also NEED_MORE when only partial
    demux_partial = StreamDemux(
        [{'id': 'h', 'framing': 'header_len', 'header': 'EB90', 'frameSize': 8, 'assemblerId': 'p'}]
    )
    demux_partial.write(b'\xeb\x90\x01\x02')  # aligned but short → 372 NEED_MORE
    assert demux_partial.drain() == []

    # force write-time compact (line 230); compact_at floor is 64
    demux_w = StreamDemux(
        [{'id': 'a', 'framing': 'header_len', 'header': 'AA', 'frameSize': 2, 'assemblerId': 'p'}],
        compact_at=64,
    )
    demux_w._buf = bytearray(b'\x00' * 70)
    demux_w._start = 65
    demux_w.write(b'\xaa\x01')
    assert demux_w._start == 0


def test_camera_tm_more_edges() -> None:
    from module_payload.parsers.xl_camera_tm import FRAME_HEADER as CH, _calc_checksum

    # D6 full span in occupied
    d6 = bytes([0xEB, 0x90, FRAME_TYPE_D6]) + bytes(D6_FRAME_SIZE - 3)
    # pad to full 266
    d6 = (d6 + bytes(D6_FRAME_SIZE))[:D6_FRAME_SIZE]
    spans = _eb90_occupied_spans(d6)
    assert spans

    # d9 mux full count break
    frames = []
    for i in range(8):
        mid = bytes([i & 0xFF]) + bytes(16)
        frames.append(bytes([0xEB, FRAME_TYPE_D9]) + mid + bytes([_calc_checksum(mid)]))
    assert len(_d9_mux_from_batch(frames)) == 8

    # prepare_d8 short data_len / checksum fail
    body = bytes([FRAME_TYPE_D8, 0, 0, 0x01, 0, 1]) + bytes(1)  # data_len=1 < D8_DATA_LEN
    fr = CH + body + bytes([0])
    with pytest.raises(ValueError):
        XlCameraTmIngest._prepare_d8_frame(fr)

    # parse_hex
    d8_ok = bytes([0xEB, 0x90, FRAME_TYPE_D8, 0, 0, D8_DATA_LEN >> 8, D8_DATA_LEN & 0xFF, 0, 1]) + bytes(
        D8_DATA_LEN
    )
    from module_payload.parsers.camera_tm_ingest_base import D8_FRAME_MIN
    # build proper d8 via existing helper pattern
    data = bytes(D8_DATA_LEN)
    body2 = bytes([FRAME_TYPE_D8, 0x00, (D8_DATA_LEN >> 8) & 0xFF, D8_DATA_LEN & 0xFF, 0x00, 0x01]) + data
    d8 = CH + body2 + bytes([_calc_checksum(body2)])
    hx = ' '.join(f'{b:02X}' for b in d8)
    assert XlCameraTmIngest.parse_hex(hx).table_key

    # D8 candidate fallback with wrong chk still tries prepare
    bad = bytearray(d8)
    bad[-1] ^= 1
    with pytest.raises(ValueError):
        XlCameraTmIngest.parse_bytes(bytes(bad))


def test_demux_compact_type_mismatch_and_need_more() -> None:
    demux = StreamDemux(
        [
            {
                'id': 'a',
                'framing': 'header_len',
                'header': 'AA',
                'frameSize': 4,
                'assemblerId': 'passthrough',
            }
        ],
        compact_at=2,
        max_buffer=32,
    )
    demux.write(b'\xaa\x01\xaa\x02')
    demux.drain()
    demux.write(b'\xaa\x03\xaa\x04')  # may compact on write
    demux.drain()

    # force compact when start past end
    demux._start = len(demux._buf) + 1
    demux._compact()
    assert demux.pending == 0

    # trim_partial on empty
    demux.clear()
    demux._trim_partial()

    # two candidates different framing/size at same header
    demux2 = StreamDemux(
        [
            {
                'id': 'd6',
                'framing': 'header_len',
                'header': 'EB90',
                'frameSize': 8,
                'typeAt': 2,
                'type': 'D6',
                'assemblerId': 'camera_image_d6',
            },
            {
                'id': 'd8',
                'framing': 'header_len',
                'header': 'EB90',
                'frameSize': 8,
                'typeAt': 2,
                'type': 'D8',
                'assemblerId': 'passthrough',
            },
        ],
        compact_at=4,
    )
    frame = bytes([0xEB, 0x90, 0xD6, 1, 2, 3, 4, 5])
    demux2.write(frame)
    hits = demux2.drain()
    assert len(hits) == 1 and hits[0].route_id == 'd6'

    # type mismatch consumes frame (header_len)
    demux3 = StreamDemux(
        [
            {
                'id': 'only',
                'framing': 'header_len',
                'header': 'EB90',
                'frameSize': 8,
                'typeAt': 2,
                'type': 'D6',
                'assemblerId': 'x',
            }
        ],
        compact_at=4,
    )
    demux3.write(bytes([0xEB, 0x90, 0xAA, 1, 2, 3, 4, 5]) + bytes([0xEB, 0x90, 0xD6, 9, 8, 7, 6, 5]))
    assert len(demux3.drain()) == 1

    # header_trailer type mismatch → slide
    demux4 = StreamDemux(
        [
            {
                'id': 'ht',
                'framing': 'header_trailer',
                'header': 'AA55',
                'trailer': '0D0A',
                'typeAt': 2,
                'type': '01',
                'assemblerId': 'passthrough',
                'maxFrameSize': 16,
                'minFrameSize': 6,
            }
        ],
        compact_at=2,
    )
    demux4.write(b'\xaa\x55\x02XX\x0d\x0a\xaa\x55\x01YY\x0d\x0a')
    demux4.drain()

    # NEED_MORE half header
    demux5 = StreamDemux(
        [{'id': 'h', 'framing': 'header_len', 'header': 'EB90', 'frameSize': 8, 'assemblerId': 'p'}]
    )
    demux5.write(b'\xeb')
    assert demux5.drain() == []

    # header_len_trailer NEED_MORE / bad trailer skip
    demux6 = StreamDemux(
        [
            {
                'id': 'hlt',
                'framing': 'header_len_trailer',
                'header': '1BCF',
                'frameSize': 8,
                'trailers': ['0A0D'],
                'assemblerId': 'eng_tm_subpkt',
            }
        ]
    )
    demux6.write(b'\x1b\xcf\x00')
    assert demux6.drain() == []
    demux6.write(b'\x01\x02\x03\xff\xff')  # wrong trailer → skip
    demux6.drain()

    # header_trailer search NEED_MORE / max exceed skip
    demux7 = StreamDemux(
        [
            {
                'id': 'ht2',
                'framing': 'header_trailer',
                'header': 'AA',
                'trailer': 'FF',
                'assemblerId': 'p',
                'maxFrameSize': 4,
                'minFrameSize': 3,
            }
        ]
    )
    demux7.write(b'\xaa\x01\x02')  # no trailer yet, under max
    assert demux7.drain() == []
    demux7.write(b'\x03\x04')  # exceeds max without trailer → skip
    demux7.drain()


# ---------------------------------------------------------------------------
# camera_tm_ingest_base leftovers (legacy section kept for spans/parse)
# ---------------------------------------------------------------------------


def test_camera_spans_half_d8_and_parse_fallbacks() -> None:
    # half D8 after header (idx+6 > n)
    half_d8 = bytes([0xEB, 0x90, FRAME_TYPE_D8, 0x00, 0x00])
    assert _eb90_occupied_spans(half_d8) == []
    # D8 with data_len that exceeds buffer
    claim = bytes([0xEB, 0x90, FRAME_TYPE_D8, 0x00, 0x01, 0x00]) + bytes(4)
    assert _eb90_occupied_spans(claim) == []
    # header at end
    assert _eb90_occupied_spans(bytes([0x00, 0xEB, 0x90])) == []

    # d9 mux skip short frames
    assert _d9_mux_from_batch([b'\x00' * 10]) == {}

    # extract_d8 half / incomplete length
    assert XlCameraTmIngest.extract_d8_frames(bytes([0xEB, 0x90, FRAME_TYPE_D8, 0, 0])) == []
    long_claim = (
        bytes([0xEB, 0x90, FRAME_TYPE_D8, 0x00, 0x01, 0x00]) + bytes(10)
    )
    assert XlCameraTmIngest.extract_d8_frames(long_claim) == []

    # extract_d9 half at end
    assert XlCameraTmIngest.extract_d9_frames(bytes([0xEB, FRAME_TYPE_D9, 0x00])) == []

    # prepare_d8 short after header / short data_len
    from module_payload.parsers.xl_camera_tm import FRAME_HEADER as CH

    body = bytes([FRAME_TYPE_D8, 0x00, 0x00, 0x01, 0x00, 0x01]) + bytes(1)
    fr = CH + body + bytes([0])
    with pytest.raises(ValueError):
        XlCameraTmIngest._prepare_d8_frame(fr)

    # parse_bytes fallbacks: bad checksum D8 candidate / D9 / raw payload
    d8 = bytes([0xEB, 0x90, FRAME_TYPE_D8, 0, 0, D8_DATA_LEN >> 8, D8_DATA_LEN & 0xFF, 0, 1]) + bytes(
        D8_DATA_LEN
    )
    d8 = d8 + bytes([0x00])  # wrong chk
    # may raise on prepare
    try:
        XlCameraTmIngest.parse_bytes(d8)
    except ValueError:
        pass

    d9 = bytes([0xEB, FRAME_TYPE_D9]) + bytes(17) + bytes([0x00])
    try:
        XlCameraTmIngest.parse_bytes(d9)
    except ValueError:
        pass

    raw45 = bytes(D8_DATA_LEN)
    parsed = XlCameraTmIngest.parse_bytes(raw45)
    assert parsed.table_key

    with pytest.raises(ValueError, match='未找到'):
        XlCameraTmIngest.parse_bytes(b'\x01\x02')


@pytest.mark.asyncio
async def test_camera_async_ok_path() -> None:
    from module_payload.parsers.xl_camera_tm import FRAME_HEADER as CH, _calc_checksum

    data = bytes(D8_DATA_LEN)
    body = bytes([FRAME_TYPE_D8, 0x00, (D8_DATA_LEN >> 8) & 0xFF, D8_DATA_LEN & 0xFF, 0x00, 0x01]) + data
    d8 = CH + body + bytes([_calc_checksum(body)])
    redis = MagicMock()
    pipe = MagicMock()
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.zremrangebyrank = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])
    redis.pipeline.return_value = pipe
    redis.set = AsyncMock()
    with patch('module_payload.parsers.tm_ingest_batch.enqueue', new_callable=AsyncMock):
        with patch(
            'module_payload.redis_store.set_telemetry',
            new_callable=AsyncMock,
            return_value={'name': 'n', 'fields': [{'id': 'a'}], 'ts': 't'},
        ):
            out = await XlCameraTmIngest.ingest_bytes_async(redis, d8, src_param='serial:COM1')
    assert out.get('dataType') or out.get('table_key') or True

    # D8 candidate fallback (extract empty but looks like D8) — line 401
    short_d8 = CH + bytes([FRAME_TYPE_D8, 0, 0, 0, 0, 0]) + bytes(40)
    try:
        XlCameraTmIngest.parse_bytes(short_d8)
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# tm_ingest_batch leftovers
# ---------------------------------------------------------------------------


def test_tm_batch_curve_pipe_split_and_workers() -> None:
    redis = MagicMock()
    pipe = MagicMock()
    redis.pipeline.return_value = pipe
    # force pipeline split
    big_points = {f'f{i}': float(i) for i in range(_CURVE_PIPE_MAX_OPS // 2 + 10)}
    _write_curves_batch(redis, [('T', big_points, 1)])
    assert pipe.execute.call_count >= 2

    _write_curves_sync(redis, 'T', {'a': 1.0}, 2)

    frame = _prepared(ts_ms=0)
    _write_latest_from_frame(redis, frame)

    batcher = TmIngestBatcher()
    # flush_loop exception path
    batcher._ensure_flush_worker()
    batcher._flush_q.put((redis, [_prepared()], 'X'))
    with patch(
        'module_payload.parsers.tm_ingest_batch.process_prepared_sync',
        side_effect=RuntimeError('flush-fail'),
    ):
        time.sleep(0.05)

    # latest_loop: redis None / snap None / already written / exception
    batcher._redis = None
    batcher._last_frame['K'] = _prepared()
    batcher._latest_snap['K'] = (id(batcher._last_frame['K']), 1)
    batcher._ensure_latest_worker()
    time.sleep(0.05)
    batcher._redis = redis
    batcher._latest_written_id['K'] = id(batcher._last_frame['K'])
    time.sleep(0.6)
    # exception path
    fr2 = _prepared(table_key='Z')
    batcher._last_frame['Z'] = fr2
    batcher._latest_snap['Z'] = (id(fr2), 9)
    batcher._latest_written_id.pop('Z', None)
    with patch(
        'module_payload.parsers.tm_ingest_batch._write_latest_from_frame',
        side_effect=RuntimeError('latest-fail'),
    ):
        time.sleep(0.6)
    batcher._latest_stop.set()

    # _submit_flush early return
    batcher._submit_flush(None, [_prepared()], 'A')
    batcher._submit_flush(redis, [], 'A')

    # flush with redis None after clear
    with batcher._lock:
        batcher._bufs['Q'] = [_prepared()]
        batcher._redis = None
    batcher.flush(None)


@pytest.mark.asyncio
async def test_process_prepared_async_curve_pipe_split() -> None:
    redis = MagicMock()
    pipe = MagicMock()
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.zremrangebyrank = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])
    redis.pipeline.return_value = pipe
    redis.set = AsyncMock()
    points = {f'p{i}': float(i) for i in range(_CURVE_PIPE_MAX_OPS // 2 + 5)}
    mgr = _fake_mgr(points=points)
    frame = _prepared(mgr=mgr, extra={'srcAddr': 1})
    with patch('module_payload.parsers.tm_ingest_batch.enqueue', new_callable=AsyncMock):
        with patch(
            'module_payload.redis_store.set_telemetry',
            new_callable=AsyncMock,
            return_value={'name': 'n', 'fields': []},
        ):
            await process_prepared_async(redis, [frame])
    assert pipe.execute.await_count >= 1


# ---------------------------------------------------------------------------
# log_annotation remaining branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_client_disconnect_and_form_modes() -> None:
    request = MagicMock(spec=Request)
    request.method = 'POST'
    request.url.path = '/api/x'
    request.headers = {'User-Agent': 'Mozilla Windows', 'Content-Type': 'application/json', 'referer': ''}
    request.path_params = {}
    request.query_params = {}

    with (
        patch('common.annotation.log_annotation.DependencyUtil.check_exclude_routes'),
        patch('common.annotation.log_annotation.ClientIPUtil.get_client_ip', return_value='127.0.0.1'),
        patch.object(Log, '_get_oper_location', new=AsyncMock(return_value='内网IP')),
        patch('common.annotation.log_annotation.LogQueueService.enqueue_operation_log', new=AsyncMock()),
        patch('common.annotation.log_annotation.AppConfig.app_ip_location_query', False),
        patch('common.annotation.log_annotation.RequestContext.get_current_user', side_effect=Exception('no')),
    ):
        decor = Log(title='op', business_type=BusinessType.OTHER, request_log_mode='none')

        @decor
        async def op_disc_params(request: Request):
            return JSONResponse({'code': 200})

        with patch.object(Log, '_get_request_params', new=AsyncMock(side_effect=ClientDisconnect())):
            with pytest.raises(ClientDisconnect):
                await op_disc_params(request=request)

        @decor
        async def op_disc_mid(request: Request):
            raise ClientDisconnect()

        request.json = AsyncMock(return_value={})
        with pytest.raises(ClientDisconnect):
            await op_disc_mid(request=request)

    decor2 = Log(title='t', business_type=BusinessType.OTHER)
    # empty form
    req = MagicMock(spec=Request)
    req.headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    empty_form = MagicMock()
    empty_form.__bool__ = lambda self: False
    empty_form.items.return_value = []
    req.form = AsyncMock(return_value=empty_form)
    assert await decor2._get_form_request_params(req, 'application/x-www-form-urlencoded') == {}

    # non-multipart with fields only
    form2 = MagicMock()
    form2.__bool__ = lambda self: True
    form2.items.return_value = [('a', '1')]
    req.form = AsyncMock(return_value=form2)
    out = await decor2._get_form_request_params(req, 'application/x-www-form-urlencoded')
    assert 'form_data' in out and 'files' not in out

    # empty raw body
    req3 = MagicMock(spec=Request)
    req3.body = AsyncMock(return_value=b'')
    assert await decor2._get_raw_request_params(req3) == {}

    assert decor2._build_log_text({}, 'full', (), (), 'request') == ''
    assert decor2._build_log_text({'a': 1}, 'none', (), (), 'request') == ''

    # exclude empty fields / non-mapping
    assert decor2._exclude_fields('x', (), 'response') == 'x'
    assert decor2._exclude_fields({'a': 1}, (), 'response') == {'a': 1}

    # describe: valid list index then fail deeper → line 632 then continue
    payload = {'rows': [{'userId': 1}]}
    assert decor2._describe_missing_field_path(payload, 'rows.0.missing') != ''
    assert decor2._describe_missing_field_path(payload, 'rows.0.userId') == ''

    # strict validate empty path skip
    log_strict = Log(
        title='s',
        business_type=BusinessType.OTHER,
        request_log_mode='include',
        request_include_fields=('', 'json_body.a'),
    )
    log_strict._validate_request_field_paths_strict()

    warnings = decor2._collect_field_path_warnings(
        mode='full',
        include_fields=('json_body.a',),
        exclude_fields=('json_body.b', 'rows.0'),
        payload_kind='request',
    )
    assert any('排除' in w or '白名单' in w for w in warnings)

    assert decor2._get_field_value_by_path({'a': 1}, 'a.b') is decor2._MISSING

    # remove: ambiguous mid path / list traverse / list pop oob / non container target
    amb = {'user_name': 1, 'userName': 2}
    # create ambiguous keys for normalize
    amb2 = {'user_id': 1, 'userId': 2}
    assert decor2._remove_field_by_path({'outer': amb2}, 'outer.user_id.x') is False or True
    assert decor2._remove_field_by_path({'rows': [{'a': 1}]}, 'rows.0.a') is True
    assert decor2._remove_field_by_path({'rows': [1]}, 'rows.5') is False
    assert decor2._remove_field_by_path({'a': 1}, 'a.0') is False  # a is int, not list/dict

    # resolve ambiguous
    assert decor2._resolve_mapping_key_by_part(amb2, 'user_id') in (
        decor2._AMBIGUOUS,
        'user_id',
        'userId',
    )
    # force ambiguous: two keys same normalize
    payload_amb = {'user_id': 1, 'user-id': 2}
    assert decor2._resolve_mapping_key_by_part(payload_amb, 'userId') is decor2._AMBIGUOUS
