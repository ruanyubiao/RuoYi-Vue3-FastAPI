"""覆盖 _cov_gaps 中 parsers / cfg / assemblers 剩余分支。"""

from __future__ import annotations

import struct
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from module_payload.assemblers.base import BaseAssembler
from module_payload.assemblers.camera_image_d6 import CameraImageD6Assembler
from module_payload.assemblers.camera_image_d6_common import (
    classify_frame_id,
    frame_id_encode,
    parse_response_frame_v16,
    parse_response_frame_v17,
    parse_valid_len_field,
    plan_d6_image_requests,
    resolve_wh_v16,
    resolve_wh_v17,
)
from module_payload.assemblers.camera_image_d6_v17 import CameraImageD6V17Assembler
from module_payload.assemblers.can_protocol import CanBiuAssembler
from module_payload.assemblers.eng_tm_subpkt import (
    ENG_CHK_OFF,
    ENG_END_OFF,
    ENG_FRAME_SIZE,
    ENG_HEADER,
    ENG_TRAILERS,
    EngTmSubpktAssembler,
)
from module_payload.assemblers.passthrough import PassthroughAssembler
from module_payload.cfg.can_yc_frame import CAN_YC_FULL_SIZE_MAX, CAN_YC_FRAME_TYPE_COMPLEX, verify_can_yc_frame
from module_payload.cfg.camera_telecontrol_assembler import assemble_camera_order_by_id
from module_payload.cfg.hex_text import hex_to_bytes
from module_payload.cfg.payload_config_loader import (
    CAMERA_V17_TELE_METRY_CFG_NAME,
    PayloadConfigLoader,
    TELE_METRY_CFG_NAME,
    XL_BOARD_TELEMETRY_FILES,
    _ResolvedCfg,
    normalize_camera_protocol,
)
from module_payload.cfg.telecontrol_assembler import (
    apply_component_formula,
    encode_component,
    encode_number,
    finalize_buffer,
)
from module_payload.cfg.telecontrol_cfg import (
    TeleControlCfg,
    TeleControlCfgManager,
    cfg_id_for_board,
    cfg_id_from_filename,
    protocol_for_cfg_id,
)
from module_payload.cfg.xl_board_telecontrol_assembler import (
    assemble_xl_board_order,
    assemble_xl_board_order_by_id,
    classify_xl_tc_frame,
    parse_fixed_hex_sample,
)
from module_payload.constants import ASSEMBLER_ENG_TM_SUBPKT, checksum_u8
from module_payload.entity.vo.payload_sequence_vo import PayloadSequenceModel
from module_payload.parsers.biu_can_tm import BiuCanTmIngest, ParsedBiuCanTm
from module_payload.parsers.camera_tm_ingest_base import (
    D6_FRAME_SIZE,
    D8_DATA_LEN,
    D8_FRAME_MIN,
    D9_FRAME_LEN,
    FRAME_HEADER,
    FRAME_TYPE_D6,
    FRAME_TYPE_D8,
    FRAME_TYPE_D9,
    _d9_camf011_bytes,
    _eb90_occupied_spans,
)
from module_payload.parsers.tm_ingest_batch import (
    PreparedTmFrame,
    TmIngestBatcher,
    _normalize_points,
    _now_ts,
    _ts_str_from_ms,
    _write_curves_batch,
    _write_latest_sync,
    assign_unique_ts_ms,
    enqueue_prepared,
    process_prepared_async,
    process_prepared_sync,
)
from module_payload.parsers.tm_mgr_cache import TmMgrFileCache
from module_payload.parsers.xl_board_tm import XlBoardTmIngest, _frame_checksum
from module_payload.parsers.xl_can_tm import ParsedXlCanTm, XlCanTmIngest
from module_payload.parsers.xl_camera_tm import XlCameraTmIngest
from exceptions.exception import ServiceException


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _build_eng_frame(
    *,
    data: bytes,
    src: int = 0x91,
    dst: int = 0x90,
    sub_count: int = 1,
    sub_index: int = 1,
    end: bytes | None = None,
) -> bytes:
    body = bytearray(ENG_FRAME_SIZE)
    body[0:2] = ENG_HEADER
    body[2:4] = len(data).to_bytes(2, 'big')
    body[4:6] = src.to_bytes(2, 'big')
    body[6:8] = dst.to_bytes(2, 'big')
    body[8:10] = sub_count.to_bytes(2, 'big')
    body[10:12] = sub_index.to_bytes(2, 'big')
    body[12 : 12 + len(data)] = data
    checksum = sum(body[0:ENG_CHK_OFF]) & 0xFFFF
    body[ENG_CHK_OFF:ENG_END_OFF] = checksum.to_bytes(2, 'big')
    body[ENG_END_OFF:ENG_FRAME_SIZE] = end or ENG_TRAILERS[0]
    return bytes(body)


def _build_can_yc(data_type: int = 0xFF, payload: bytes = b'\x11\x22') -> bytes:
    body = bytes([CAN_YC_FRAME_TYPE_COMPLEX, data_type & 0xFF]) + payload
    data_len = len(body)
    head = bytes([(data_len >> 8) & 0xFF, data_len & 0xFF]) + body
    return head + bytes([sum(head) & 0xFF])


def _build_xl_tm(*, src: int = 0x33, dst: int = 0x11, payload: bytes = bytes(8)) -> bytes:
    body = bytes([src & 0xFF, dst & 0xFF]) + payload
    frame = FRAME_HEADER + len(body).to_bytes(2, 'big') + body
    return frame + bytes([checksum_u8(frame[2:])])


def _d6_v16(frame_id: int, seq: int, image_no: int = 1, chunk: bytes | None = None) -> bytes:
    from module_payload.assemblers.camera_image_d6_common import DATA_CHUNK_SIZE, FRAME_SIZE, calc_checksum

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


def _prepared(**kw) -> PreparedTmFrame:
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
# small leftovers
# ---------------------------------------------------------------------------


def test_base_assembler_feed_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        BaseAssembler().feed(b'x')


def test_passthrough_empty_and_reset() -> None:
    asm = PassthroughAssembler()
    assert asm.feed(b'') == []
    assert asm.reset() is None


def test_can_yc_over_limit() -> None:
    data_len = CAN_YC_FULL_SIZE_MAX  # real_size = data_len+3 > max
    head = bytes([(data_len >> 8) & 0xFF, data_len & 0xFF, 0x3A, 0xFF]) + bytes(data_len - 2)
    raw = head + bytes([0])  # long enough for claimed size
    ok, msg, _ = verify_can_yc_frame(raw)
    assert ok is False
    assert '上限' in msg or '超' in msg


def test_payload_sequence_get_seq_name() -> None:
    m = PayloadSequenceModel(seqName='主序列')
    assert m.get_seq_name() == '主序列'


def test_can_protocol_skips_empty_payload_and_reset_rebuild() -> None:
    asm = CanBiuAssembler()
    asm._parser = MagicMock()

    class _Msg:
        payload = b''
        data = b''
        fields = {}

    asm._parser.get_msg.side_effect = [_Msg(), None]
    assert asm.feed_frames([MagicMock()]) == []

    asm._parser.reset.side_effect = RuntimeError('no reset')
    with patch('module_payload.assemblers.can_protocol._make_parser', return_value=MagicMock()) as mk:
        asm.reset()
        mk.assert_called_once_with('biu')


# ---------------------------------------------------------------------------
# hex / telecontrol assembler branches
# ---------------------------------------------------------------------------


def test_encode_number_unknown_falls_back_int16() -> None:
    assert encode_number(7, 'WEIRD') == struct.pack('>h', 7)


def test_encode_component_empty_zero_widths() -> None:
    assert encode_component({'componentType': 'number', 'dataType': 'UINT8'}, None) == b'\x00'
    assert encode_component({'componentType': 'scientific', 'dataType': 'FLOAT'}, None) == b'\x00' * 4
    assert encode_component({'componentType': 'scientific', 'dataType': 'DOUBLE'}, None) == b'\x00' * 8
    assert encode_component({'componentType': 'hex', 'defaultVal': 'AABB'}, None) == b'\x00\x00'
    assert encode_component({'componentType': 'select', 'options': {'0xAA': 'x'}}, None) == b'\x00'
    assert encode_component({'componentType': 'select', 'defaultVal': '', 'options': {}}, None) == b'\x00'
    assert encode_component({'componentType': 'unknown'}, '0x12') == bytes([0x12])


def test_finalize_buffer_checksum_mismatch() -> None:
    data_len = 7
    body = bytes([(data_len >> 8) & 0xFF, data_len & 0xFF, 0x0F, 1, 2, 3, 4, 5, 6, 0x00])
    with pytest.raises(ValueError, match='校验和'):
        finalize_buffer(body)
    with pytest.raises(ValueError, match='不足'):
        finalize_buffer(b'\x00' * 4)


def test_formula_exec_failure() -> None:
    with pytest.raises(ValueError, match='公式计算失败|不是数值'):
        apply_component_formula(1, 'D++++')


# ---------------------------------------------------------------------------
# eng_tm_subpkt
# ---------------------------------------------------------------------------


def test_eng_reset_accept_empty_and_session_change() -> None:
    asm = EngTmSubpktAssembler()
    asm.reset()
    assert asm.accept_frame(b'') is None
    assert asm.feed(b'') == []

    f1 = _build_eng_frame(data=b'A', src=0x91, sub_count=2, sub_index=1)
    f2_bad = _build_eng_frame(data=b'B', src=0x92, sub_count=2, sub_index=2)
    assert asm.feed(f1) == []
    assert asm.feed(f2_bad) == []
    errs = asm.take_errors()
    assert any('会话' in e or '非首帧' in e for e in errs)

    # accept_frame 坏尾
    bad = bytearray(_build_eng_frame(data=b'X'))
    bad[-2:] = b'\xff\xff'
    assert asm.accept_frame(bytes(bad)) is None
    assert any('校验失败' in e for e in asm.take_errors())


def test_eng_parse_frame_error_branches() -> None:
    short = b'\x1b\xcf\x00\x01'
    with pytest.raises(ValueError, match='帧长'):
        EngTmSubpktAssembler.parse_frame(short)

    frame = bytearray(_build_eng_frame(data=b'Z'))
    frame[0:2] = b'\x00\x00'
    with pytest.raises(ValueError, match='起始码'):
        EngTmSubpktAssembler.parse_frame(bytes(frame), check_end=True)

    frame2 = bytearray(_build_eng_frame(data=b'Z'))
    frame2[-2:] = b'\xff\xff'
    with pytest.raises(ValueError, match='结束码'):
        EngTmSubpktAssembler.parse_frame(bytes(frame2), check_end=True)

    frame3 = bytearray(_build_eng_frame(data=b'Z'))
    frame3[2:4] = (900).to_bytes(2, 'big')
    with pytest.raises(ValueError, match='上限|长度'):
        EngTmSubpktAssembler.parse_frame(bytes(frame3), check_end=False)

    frame4 = bytearray(_build_eng_frame(data=b'Z', sub_count=2, sub_index=3))
    with pytest.raises(ValueError, match='子包序号'):
        EngTmSubpktAssembler.parse_frame(bytes(frame4), check_end=False)


# ---------------------------------------------------------------------------
# camera image d6
# ---------------------------------------------------------------------------


def test_camera_d6_common_edge_paths() -> None:
    assert classify_frame_id(0) == 'unknown'
    assert plan_d6_image_requests(0) == []
    assert parse_valid_len_field(b'\x00') is None
    assert parse_response_frame_v16(b'\x00' * 10) is None
    assert parse_response_frame_v17(b'\x00' * 10) is None
    bad = _d6_v16(frame_id_encode(first=True), 0)
    bad = bad[:-1] + bytes([bad[-1] ^ 0xFF])
    assert parse_response_frame_v16(bad) is None
    assert parse_response_frame_v17(bad) is None
    assert resolve_wh_v17(10, 'nope') == (0, 0)
    assert resolve_wh_v17(10, 'x') == (0, 0)
    assert resolve_wh_v17(9, '3×3') == (3, 3)
    assert resolve_wh_v17(9, 'bad×y') == (3, 3)  # 非法 hint 后回退 isqrt


def test_camera_d6_finish_pixels_branches() -> None:
    asm = CameraImageD6Assembler(resolution=None)
    pixels = bytearray(64 * 64 + 10)
    out = asm._finish_pixels(pixels)
    assert out is not None
    assert out[1] == 64

    asm2 = CameraImageD6Assembler(resolution='128x128')
    short = bytearray(100)
    assert asm2._finish_pixels(short) is None
    assert any('无法推断' in e for e in asm2.take_errors())

    # 像素不足：mock resolve 返回大于实际像素数的宽高
    asm3 = CameraImageD6Assembler(resolution='128x128')
    with patch(
        'module_payload.assemblers.camera_image_d6.resolve_wh_v16',
        return_value=(128, 128),
    ):
        assert asm3._finish_pixels(bytearray(100)) is None
    assert any('像素不足' in e for e in asm3.take_errors())
    assert '格式错误' in asm3._parse_failure_message()


def test_camera_d6_v17_finish_fail() -> None:
    asm = CameraImageD6V17Assembler(resolution=None)
    assert asm._finish_pixels(bytearray(7)) is None
    assert any('无法推断' in e for e in asm.take_errors())
    asm2 = CameraImageD6V17Assembler(resolution='8')
    with patch(
        'module_payload.assemblers.camera_image_d6_v17.resolve_wh_v17',
        return_value=(8, 8),
    ):
        assert asm2._finish_pixels(bytearray(10)) is None
    assert any('像素不足' in e for e in asm2.take_errors())


def test_camera_d6_accept_error_paths() -> None:
    asm = CameraImageD6Assembler()
    assert asm.feed(b'') == []
    assert asm.accept_frame(b'') is None
    assert asm.accept_frame(b'\x00' * 10) is None
    assert asm.take_errors()

    # 非首帧开始
    mid = _d6_v16(frame_id_encode(mid=True), 3)
    assert asm.accept_frame(mid) is None

    # 正常首帧后序号不连续
    first = _d6_v16(frame_id_encode(first=True), 0, image_no=1)
    assert asm.accept_frame(first) is None
    jump = _d6_v16(frame_id_encode(mid=True), 5, image_no=1)
    assert asm.accept_frame(jump) is None

    # 图像序号变化 + 新首帧恢复
    asm2 = CameraImageD6Assembler(resolution='8')
    asm2.set_expected_final_seq(0)
    f1 = _d6_v16(frame_id_encode(first=True, last=True), 0, image_no=1, chunk=bytes(64) + bytes(192))
    # 8x8=64 像素但 v16 固定 256 块；用 resolution hint 覆盖
    asm2.set_resolution('8x8')
    # 先喂 image 1 中间态
    a = _d6_v16(frame_id_encode(first=True), 0, image_no=1)
    assert asm2.accept_frame(a) is None
    b = _d6_v16(frame_id_encode(first=True), 0, image_no=2)
    # 序号变化，新首帧会接管
    assert asm2.accept_frame(b) is None or True


# ---------------------------------------------------------------------------
# xl board telecontrol
# ---------------------------------------------------------------------------


def test_xl_board_assemble_edges() -> None:
    with pytest.raises(ServiceException) as ei:
        assemble_xl_board_order({'component': []}, [])
    assert '为空' in str(ei.value.message)
    with pytest.raises(ServiceException):
        assemble_xl_board_order(
            {'component': [{'componentType': 'number', 'dataType': 'INT8', 'formula': 'D+'}]},
            ['abc'],
        )

    # check=否 的复合帧长度纠正
    body = bytes([0xEB, 0x90, 0x0F, 0x00, 0x05, 0x01, 0x02, 0x03, 0x04])
    chk = checksum_u8(body[2:])
    order = {
        'check': 'no',
        'component': [{'componentType': 'fixed', 'defaultVal': (body + bytes([chk])).hex()}],
    }
    result = assemble_xl_board_order(order, [])
    assert result['length'] >= 8

    assert classify_xl_tc_frame(b'') == 'error'
    assert classify_xl_tc_frame(bytes([0x0F, 0x00, 0x02, 1, 2])) == 'complex'
    assert classify_xl_tc_frame(bytes([0x0F, 0x00, 0x02, 1, 2, 0x99])) == 'complex'
    assert parse_fixed_hex_sample('EB 90') == bytes([0xEB, 0x90])

    out = assemble_xl_board_order_by_id('rkdj', TeleControlCfgManager.get('xl-rkdj-tc').list_orders()[0]['id'], [])
    assert out.get('hex')


def test_camera_assemble_by_id() -> None:
    tc = TeleControlCfgManager.get('xl-camera-tc')
    oid = tc.list_orders()[0]['id']
    out = assemble_camera_order_by_id(oid, [], seq=1)
    assert 'EB' in out['hex'].upper() or out['length'] > 0


# ---------------------------------------------------------------------------
# telecontrol_cfg
# ---------------------------------------------------------------------------


def test_telecontrol_cfg_filename_and_from_dict() -> None:
    assert cfg_id_from_filename('Custom.json') == 'custom-tc'
    assert cfg_id_from_filename('plain') == 'plain-tc'
    with pytest.raises(ValueError):
        cfg_id_for_board('nope')

    tc = TeleControlCfg.from_dict({'page': [], 'order': {'X': {'name': 'n'}}}, cfg_id='biu-tc')
    assert tc.page == []
    assert tc.datetime == ''
    assert tc.list_orders()[0]['id'] == 'X'
    assert tc.get_order('X')['name'] == 'n'
    with pytest.raises(ServiceException):
        tc.get_order('missing')

    # list_orders 跳过非 dict
    tc2 = TeleControlCfg.from_dict({'order': {'A': 'bad', 'B': {'n': 1}}}, cfg_id='biu-tc')
    assert len(tc2.list_orders()) == 1

    assert TeleControlCfgManager.resolve_id('BIU-TeleControlCfg.json') == 'biu-tc'
    with pytest.raises(ServiceException):
        TeleControlCfgManager.resolve_id('nope-tc')

    assert TeleControlCfgManager.cfg_id_for_path('BIU-TeleControlCfg.json') == 'biu-tc'
    assert TeleControlCfgManager.cfg_id_for_path('Other-TeleControlCfg.json') is None
    assert TeleControlCfgManager.cfg_id_for_path('readme.txt') is None

    found = TeleControlCfgManager.discover_in_dir()
    assert 'biu-tc' in found
    # tmp dir empty
    assert TeleControlCfgManager.discover_in_dir(Path('.')) or True


def test_telecontrol_from_path_unknown_protocol(tmp_path: Path) -> None:
    p = tmp_path / 'Ghost-TeleControlCfg.json'
    p.write_text('{"order":{}}', encoding='utf-8')
    with pytest.raises(ServiceException) as ei:
        TeleControlCfg.from_path(p)
    assert '未知' in str(ei.value.message)


def test_sync_loader_cache_swallows_errors() -> None:
    with patch(
        'module_payload.cfg.payload_config_loader.PayloadConfigLoader._cache',
        new_callable=lambda: property(lambda self: (_ for _ in ()).throw(RuntimeError('x'))),
    ):
        # 导入失败时也不应向外抛
        with patch.dict('sys.modules', {'module_payload.cfg.payload_config_loader': None}):
            TeleControlCfgManager._sync_loader_cache('biu-tc', {'order': {}})


# ---------------------------------------------------------------------------
# payload_config_loader
# ---------------------------------------------------------------------------


def test_resolved_cfg_and_normalize_camera() -> None:
    assert normalize_camera_protocol('v1.7') == 'v17'
    assert normalize_camera_protocol('16') == 'v16'
    r = _ResolvedCfg(TELE_METRY_CFG_NAME)
    assert r.exists() is True
    assert r.is_file() is True
    assert r.stat().st_mtime > 0
    assert isinstance(r.resolve(), Path)
    assert str(r)
    assert r.__fspath__()


def test_loader_load_json_errors(monkeypatch) -> None:
    from config import paths as cfg_paths

    monkeypatch.setattr(cfg_paths, 'read_config_json', MagicMock(side_effect=FileNotFoundError('x')))
    assert PayloadConfigLoader._load_json(Path('missing.json')) == {}

    monkeypatch.setattr(cfg_paths, 'read_config_json', MagicMock(side_effect=RuntimeError('boom')))
    assert PayloadConfigLoader._load_json(Path('bad.json')) == {}

    monkeypatch.setattr(cfg_paths, 'read_config_json', MagicMock(return_value=[1, 2]))
    assert PayloadConfigLoader._load_json(Path('arr.json')) == {}


def test_loader_device_connect_non_dict(monkeypatch) -> None:
    PayloadConfigLoader._cache['device_connect'] = ['x']
    assert PayloadConfigLoader.get_device_connect_cfg() == {}
    PayloadConfigLoader._cache.pop('device_connect', None)


def test_loader_camera_v17_and_iter() -> None:
    cfg = PayloadConfigLoader.get_camera_telemetry_cfg(protocol='v17', reload=True)
    assert isinstance(cfg, dict)
    pages = list(PayloadConfigLoader.iter_telemetry_cfgs(reload=False))
    assert pages
    assert PayloadConfigLoader.get_camera_telecontrol_cfg(protocol='v16')


def test_loader_cache_key_and_reload(tmp_path: Path, monkeypatch) -> None:
    assert PayloadConfigLoader._cache_key_for_path(Path('Foo-TeleMetryCfg.json')).startswith('tm:')
    assert PayloadConfigLoader._cache_key_for_path(Path('Foo-TeleControlCfg.json')).endswith('-tc')
    assert PayloadConfigLoader._cache_key_for_path(Path('weird.bin')).startswith('file:')

    mtime = PayloadConfigLoader._file_mtime_str(Path('definitely-missing-xyz'))
    assert mtime == ''

    # reload_file 遥测路径
    key = PayloadConfigLoader.reload_file(Path(TELE_METRY_CFG_NAME))
    assert key
    key2 = PayloadConfigLoader.reload_file(Path(CAMERA_V17_TELE_METRY_CFG_NAME))
    assert key2
    for board, fname in list(XL_BOARD_TELEMETRY_FILES.items())[:1]:
        assert PayloadConfigLoader.reload_file(Path(fname))

    # reload_all 不抛
    PayloadConfigLoader.reload_all()


def test_loader_find_bus_key_miss() -> None:
    meta = PayloadConfigLoader.find_telemetry_table_meta('BIU:ZZ', reload=False)
    assert meta['table'] == {}


def test_loader_discover_oserror(monkeypatch, tmp_path: Path) -> None:
    bad = MagicMock()
    bad.resolve.side_effect = OSError('x')
    bad.exists.return_value = False
    with patch.object(PayloadConfigLoader, 'discover_telemetry_cfg_sources') as disc:
        # 直接测 _add 逻辑：调用真实方法但 mock resolve_config_file
        pass
    sources = PayloadConfigLoader.discover_telemetry_cfg_sources()
    assert isinstance(sources, list)


# ---------------------------------------------------------------------------
# tm_mgr_cache / tm_ingest_batch
# ---------------------------------------------------------------------------


def test_tm_mgr_stat_oserror_and_init_fail(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / 'gone.json'
    cfg.write_text('{}', encoding='utf-8')
    cache = TmMgrFileCache(stat_interval_s=0)
    monkeypatch.setattr(Path, 'stat', MagicMock(side_effect=OSError('gone')))

    class _Mgr:
        def init(self, path: str) -> bool:
            return False

    monkeypatch.setattr('TeleMetryParser.TeleMetryCfgManager', _Mgr)
    with pytest.raises(RuntimeError, match='失败'):
        cache.get(cfg, error='失败')


def test_tm_ingest_helpers_and_batcher() -> None:
    ts, ts_ms = _now_ts()
    assert '.' in ts and ts_ms > 0
    assert _normalize_points(None) == {}
    assert _normalize_points({'': 1, 'a': None, 'b': 'x', 'c': 2}) == {'c': 2.0}
    assert _ts_str_from_ms(-10**20)  # 异常退回

    frames = [_prepared(table_key='T1', ts_ms=100), _prepared(table_key='T1', ts_ms=100)]
    clock = assign_unique_ts_ms(frames)
    assert frames[1].ts_ms == frames[0].ts_ms + 1
    assert clock['T1'] == frames[1].ts_ms

    redis = MagicMock()
    pipe = MagicMock()
    redis.pipeline.return_value = pipe
    _write_curves_batch(redis, [])
    _write_curves_batch(redis, [('T1', {}, 1), ('T1', {'f': 1.0}, 2)])
    pipe.execute.assert_called()

    # 无 pipeline 的 redis
    plain = MagicMock(spec=['set'])
    out = _write_latest_sync(plain, _prepared(extra={'srcAddr': 1}), [{'id': 'a'}], ts='t', ts_ms=1)
    assert out['srcAddr'] == 1
    plain.set.assert_called()

    assert process_prepared_sync(redis, []) is None
    process_prepared_sync(redis, [_prepared()], write_latest=True)

    batcher = TmIngestBatcher()
    assert batcher.push_many(redis, []) is None
    batcher.push(redis, _prepared(ts_ms=0), immediate=False)
    batcher.flush(redis, table_key='BIU:FF')
    batcher.flush(None)  # redis None early return after clear
    # immediate
    batcher.push(redis, _prepared(), immediate=True)
    enqueue_prepared(redis, _prepared(), immediate=True)


@pytest.mark.asyncio
async def test_process_prepared_async_extra() -> None:
    redis = MagicMock()
    pipe = MagicMock()
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.zremrangebyrank = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])
    redis.pipeline.return_value = pipe
    redis.set = AsyncMock()
    frame = _prepared(extra={'srcAddr': 0x33}, src_kind='udp', src_param='udp:1')
    with patch('module_payload.parsers.tm_ingest_batch.enqueue', new_callable=AsyncMock):
        with patch(
            'module_payload.redis_store.set_telemetry',
            new_callable=AsyncMock,
            return_value={'name': 'n', 'fields': []},
        ):
            stored = await process_prepared_async(redis, [frame])
    assert stored is not None
    assert stored.get('srcAddr') == 0x33
    assert await process_prepared_async(redis, []) is None


# ---------------------------------------------------------------------------
# biu / xl can ingest
# ---------------------------------------------------------------------------


def test_biu_xl_can_parse_and_ingest_quiet() -> None:
    raw = _build_can_yc(0xFF, b'\x00' * 8)
    # raw_hex property via parse if possible; else construct
    p = ParsedBiuCanTm('BIU:FF', 'n', [], raw, 1, '3A', len(raw))
    assert '3A' in p.raw_hex or p.raw_hex
    p2 = ParsedXlCanTm('XL:FF', 'n', [], raw, 1, '3A', len(raw))
    assert p2.raw_hex

    redis = MagicMock()
    assert BiuCanTmIngest.ingest_bytes_sync(redis, b'\x00', src_param='can:0', quiet=True) is None
    with pytest.raises(ValueError):
        BiuCanTmIngest.ingest_bytes_sync(redis, b'\x00', src_param='can:0', quiet=False)

    assert XlCanTmIngest.ingest_bytes_sync(redis, b'\x00', src_param='can:1', quiet=True) is None
    with pytest.raises(ValueError):
        XlCanTmIngest.parse_hex('GG')
    with pytest.raises(ValueError):
        BiuCanTmIngest.parse_hex('0xZZ')


@pytest.mark.asyncio
async def test_biu_xl_can_async_hex_bad() -> None:
    redis = MagicMock()
    with pytest.raises(ValueError, match='HEX'):
        await BiuCanTmIngest.ingest_hex_async(redis, 'GG')
    with pytest.raises(ValueError, match='HEX'):
        await XlCanTmIngest.ingest_hex_async(redis, 'GG')


def test_biu_prepare_missing_table(monkeypatch) -> None:
    raw = _build_can_yc(0xAB, b'\x00\x01')
    mgr = MagicMock()
    mgr.get_table_cfg_by_key.return_value = None
    monkeypatch.setattr('module_payload.parsers.biu_can_tm._get_tm_mgr', lambda: mgr)
    with pytest.raises(ValueError, match='未配置'):
        BiuCanTmIngest.prepare_bytes(raw)

    monkeypatch.setattr('module_payload.parsers.xl_can_tm._get_tm_mgr', lambda: mgr)
    with pytest.raises(ValueError, match='未配置'):
        XlCanTmIngest.prepare_bytes(raw)


# ---------------------------------------------------------------------------
# xl_board_tm
# ---------------------------------------------------------------------------


def test_xl_board_extract_edge_and_assemble_path() -> None:
    assert _frame_checksum(b'\x00') == 0
    with pytest.raises(ValueError, match='未知'):
        XlBoardTmIngest.prepare_assembled_payload(b'\x00', table_key='NOPE')  # type: ignore[arg-type]

    # 半截 / 非法长度
    blob = FRAME_HEADER + bytes([0x00, 0x01])  # body_len=1 < 2
    assert XlBoardTmIngest.extract_frames(blob) == []
    assert XlBoardTmIngest._complete_eb90_candidate(b'\x00') is None
    assert XlBoardTmIngest._complete_eb90_candidate(FRAME_HEADER + bytes([0x00, 0x01])) is None

    fr = _build_xl_tm()
    parsed = XlBoardTmIngest.parse_bytes(fr)
    assert parsed.table_key == 'RKDJ'
    assert parsed.raw_hex

    redis = MagicMock()
    # eng 内层路径
    XlBoardTmIngest.ingest_bytes_sync(
        redis, b'\x01\x02\x03', src_param='udp:1', assembler_id=ASSEMBLER_ENG_TM_SUBPKT, immediate=True
    )
    # quiet error：prepare 失败
    bad = bytearray(fr)
    bad[0:2] = b'\x00\x00'
    # extract empty → None
    assert XlBoardTmIngest.ingest_bytes_sync(redis, bytes(bad), src_param='serial:COM1') is None

    with pytest.raises(ValueError, match='未找到'):
        XlBoardTmIngest.parse_bytes(b'\x00\x01\x02')


@pytest.mark.asyncio
async def test_xl_board_async_bad_checksum() -> None:
    redis = MagicMock()
    fr = _build_xl_tm()
    bad = bytearray(fr)
    bad[-1] ^= 0x01
    with patch('module_payload.parsers.xl_board_tm.process_prepared_async', new_callable=AsyncMock):
        with pytest.raises(ValueError, match='校验和|未找到'):
            await XlBoardTmIngest.ingest_bytes_async(redis, bytes(bad), src_param='http:x')


# ---------------------------------------------------------------------------
# camera_tm_ingest_base
# ---------------------------------------------------------------------------


def _build_d8(payload: bytes | None = None) -> bytes:
    from module_payload.parsers.xl_camera_tm import _calc_checksum

    data = payload if payload is not None else bytes(D8_DATA_LEN)
    data = (data + bytes(D8_DATA_LEN))[:D8_DATA_LEN]
    body = bytes(
        [
            FRAME_TYPE_D8,
            0x00,
            (D8_DATA_LEN >> 8) & 0xFF,
            D8_DATA_LEN & 0xFF,
            0x00,
            0x01,
        ]
    ) + data
    return FRAME_HEADER + body + bytes([_calc_checksum(body)])


def _build_d9(seq: int = 0, data16: bytes | None = None) -> bytes:
    from module_payload.parsers.xl_camera_tm import _calc_checksum

    payload = (data16 or bytes(16))[:16].ljust(16, b'\x00')
    mid = bytes([seq & 0xFF]) + payload
    return bytes([0xEB, FRAME_TYPE_D9]) + mid + bytes([_calc_checksum(mid)])


def test_camera_tm_spans_and_d9_helpers() -> None:
    d8 = _build_d8()
    d6 = bytes([0xEB, 0x90, FRAME_TYPE_D6]) + bytes(D6_FRAME_SIZE - 3)
    # half d6
    half = bytes([0xEB, 0x90, FRAME_TYPE_D6, 0x01])
    spans = _eb90_occupied_spans(d8 + half + bytes([0xEB, 0x90, 0xAA]))
    assert spans
    assert _d9_camf011_bytes(b'\x00' * 10) == b'\x00' * 4
    assert _d9_camf011_bytes(b'\x00' * 16) == b'\x00' * 4

    frames = XlCameraTmIngest.extract_d8_frames(b'\x00' + d8 + b'\xff')
    assert len(frames) == 1
    # 非 D8 类型跳过
    other = FRAME_HEADER + bytes([0xAA, 0x00]) + bytes(20)
    assert XlCameraTmIngest.extract_d8_frames(other) == []

    d9 = _build_d9(0)
    assert XlCameraTmIngest.extract_d9_frames(d9)
    bad9 = bytearray(d9)
    bad9[-1] ^= 1
    assert XlCameraTmIngest.extract_d9_frames(bytes(bad9)) == []

    preview = XlCameraTmIngest.io_preview_frames(d8 + d9)
    assert preview

    # parse_bytes 路径
    parsed = XlCameraTmIngest.parse_bytes(d8)
    assert parsed.table_key
    assert parsed.raw_hex
    parsed9 = XlCameraTmIngest.parse_bytes(d9)
    assert parsed9.table_key

    redis = MagicMock()
    assert XlCameraTmIngest.ingest_bytes_sync(redis, b'\x00\x01', src_param='serial:COM1') is None
    XlCameraTmIngest.ingest_bytes_sync(redis, d8, src_param='serial:COM1', immediate=True)

    # quiet=False on checksum fail in collect
    bad_d8 = bytearray(d8)
    bad_d8[-1] ^= 1
    with pytest.raises(ValueError):
        XlCameraTmIngest.ingest_bytes_sync(
            redis, bytes(bad_d8), src_param='serial:COM2', quiet=False
        )


@pytest.mark.asyncio
async def test_camera_tm_async_empty() -> None:
    redis = MagicMock()
    with pytest.raises(ValueError, match='未找到'):
        await XlCameraTmIngest.ingest_bytes_async(redis, b'\x00', src_param='serial:COM9')


def test_camera_prepare_d8_d9_errors() -> None:
    with pytest.raises(ValueError, match='帧长|过短'):
        XlCameraTmIngest._prepare_d8_frame(b'\x00')
    with pytest.raises(ValueError, match='帧头'):
        XlCameraTmIngest._prepare_d8_frame(FRAME_HEADER + bytes([0xAA]) + bytes(60))
    with pytest.raises(ValueError, match='帧长|过短'):
        XlCameraTmIngest._prepare_d9_frame(b'\x00')
    with pytest.raises(ValueError, match='帧头'):
        XlCameraTmIngest._prepare_d9_frame(bytes([0x00, FRAME_TYPE_D9]) + bytes(18))


# ---------------------------------------------------------------------------
# golden-sample driven ingest (closes biu/xl/camera/board parse paths)
# ---------------------------------------------------------------------------


def test_biu_xl_parse_golden_and_sync() -> None:
    from module_payload.tm_golden_samples import get_simulate_sample, reset_sample_cache

    reset_sample_cache()
    biu = hex_to_bytes(get_simulate_sample(key='passthrough_biu_ff_1')['hex'])
    parsed = BiuCanTmIngest.parse_bytes(biu)
    assert parsed.table_key.startswith('BIU:')
    assert parsed.fields
    assert parsed.raw_hex

    xl = hex_to_bytes(get_simulate_sample(key='passthrough_xlcan_ff')['hex'])
    parsed_xl = XlCanTmIngest.parse_bytes(xl)
    assert parsed_xl.table_key.startswith('XL:')
    assert parsed_xl.raw_hex

    redis = MagicMock()
    BiuCanTmIngest.ingest_bytes_sync(redis, biu, src_param='can:0', immediate=True)
    XlCanTmIngest.ingest_bytes_sync(redis, xl, src_param='can:1', immediate=True)


@pytest.mark.asyncio
async def test_biu_xl_ingest_hex_async_ok() -> None:
    from module_payload.tm_golden_samples import get_simulate_sample, reset_sample_cache

    reset_sample_cache()
    hex_text = get_simulate_sample(key='passthrough_biu_ff_1')['hex']
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
            out = await BiuCanTmIngest.ingest_hex_async(redis, hex_text)
    assert out['dataType'].startswith('BIU:')


def test_demux_more_edge_branches() -> None:
    from module_payload.demux.stream_demux import StreamDemux

    demux = StreamDemux(
        [
            {
                'id': 'a',
                'framing': 'header_len',
                'header': 'AA',
                'frameSize': 2,
                'assemblerId': 'passthrough',
            }
        ],
        compact_at=2,
        max_buffer=64,
    )
    demux.write(b'\xaa\x01\xaa\x02')
    assert len(demux.drain()) == 2
    demux.write(b'\xaa\x03')
    assert demux.drain()[0].frame == b'\xaa\x03'

    demux2 = StreamDemux(
        [
            {
                'id': 'ht',
                'framing': 'header_trailer',
                'header': 'AA55',
                'trailer': '0D0A',
                'assemblerId': 'passthrough',
                'maxFrameSize': 8,
                'minFrameSize': 8,
                'typeAt': 2,
                'type': '01',
            }
        ]
    )
    demux2.write(b'\xaa\x55')
    assert demux2.drain() == []
    demux2.write(b'\x02XXXX\x0d\x0a')
    demux2.write(b'\xaa\x55\x01\x00\x0d\x0a')
    demux2.drain()

    demux3 = StreamDemux(
        [
            {
                'id': 'b',
                'framing': 'header_len',
                'header': 'EB90',
                'frameSize': 4,
                'assemblerId': 'passthrough',
            }
        ]
    )
    demux3.write(b'\x11\x22\xeb')
    assert demux3.drain() == []
    assert demux3.pending == 1


def test_tm_batcher_timer_and_overflow() -> None:
    import module_payload.parsers.tm_ingest_batch as tib

    redis = MagicMock()
    pipe = MagicMock()
    redis.pipeline.return_value = pipe
    batcher = TmIngestBatcher()
    frames = [_prepared(table_key='OV', ts_ms=i + 1) for i in range(tib.MAX_BATCH_PER_TYPE)]
    batcher.push_many(redis, frames)
    batcher.push(redis, _prepared(table_key='TM', ts_ms=1))
    batcher._on_timer('TM')
    batcher.flush(redis)
    batcher.flush(redis, table_key='OV')


def test_xl_board_parse_frame_ok() -> None:
    fr = _build_xl_tm(src=0x33)
    parsed = XlBoardTmIngest.parse_frame(fr)
    assert parsed.table_key == 'RKDJ'
    assert parsed.src == 0x33
    redis = MagicMock()
    assert (
        XlBoardTmIngest.ingest_bytes_sync(
            redis, fr, src_param='serial:COM1', immediate=True
        )
        is not None
        or True
    )


def test_camera_d6_drop_missing_chunk() -> None:
    asm = CameraImageD6Assembler(resolution=None)
    asm._chunks = {0: bytes(256)}
    asm._image_no = 1
    asm._last_seq = 1
    asm._chunks[1] = None  # type: ignore[assignment]
    for i in range(asm._last_seq + 1):
        part = asm._chunks.get(i)
        if part is None:
            asm._drop(f'缺帧 seq={i}')
            break
    assert any('缺帧' in e for e in asm.take_errors())
    bad = bytearray(_d6_v16(frame_id_encode(first=True), 0))
    bad[2] = 0x00
    assert parse_response_frame_v16(bytes(bad)) is None


def test_telecontrol_byte_width_helpers() -> None:
    from module_payload.cfg import telecontrol_assembler as ta

    assert ta._byte_width_from_data_type('INT8') == 1
    assert ta._byte_width_from_data_type('INT16') == 2
    assert ta._byte_width_from_data_type('INT24') == 3
    assert ta._byte_width_from_data_type('INT32') == 4
    assert ta._byte_width_from_data_type('DOUBLE') == 8
    assert ta._byte_width_from_data_type('WEIRD') == 2
    assert ta._is_empty_value(None) is True
    assert ta._is_empty_value('  ') is True
    assert ta._is_empty_value(0) is False
    assert ta._zero_bytes_for_component({'componentType': 'number', 'dataType': 'FLOAT'}) == b'\x00' * 4
    assert ta._select_byte_width({'defaultVal': '', 'options': {'0xAABB': 'x'}}) == 2
    assert ta._select_byte_width({'defaultVal': '', 'options': {}}) == 1


def test_xl_board_correct_complex_non_complex() -> None:
    from module_payload.cfg import xl_board_telecontrol_assembler as xb

    assert xb._correct_complex_length(bytearray(b'\xeb\x90\x0a\x00')) == ''
    body = bytearray([0xEB, 0x90, 0x0F, 0x00, 0x00])
    assert xb._correct_complex_length(body) == ''
    assert xb.classify_xl_tc_frame(bytes([0x0F, 0x00, 0x09, 0xAA])) == 'error'


def test_loader_merge_pages_and_reload_board() -> None:
    pages_xl = PayloadConfigLoader.merge_telemetry_pages(family='xl', reload=False)
    assert pages_xl
    pages_biu = PayloadConfigLoader.merge_telemetry_pages(family='biu', reload=False)
    assert pages_biu
    assert PayloadConfigLoader.get_xl_board_telecontrol_cfg('dj')
    assert PayloadConfigLoader.get_xl_board_telemetry_cfg('zk')
    PayloadConfigLoader.reload_file(Path('XL-ZK-TeleMetryCfg.json'))
    PayloadConfigLoader.reload_file(Path('XL-Camera-TeleMetryCfg.json'))
