"""覆盖率补洞 R4：全量 suite 仍 missing 的 31 行 + __main__ 入口。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from module_payload.cfg.payload_config_loader import (
    PayloadConfigLoader,
    XL_TELE_METRY_CFG_NAME,
)
from module_payload.collectors.base_collector import BaseCollector
from module_payload.collectors.connection_transfer_logger import ConnectionTransferLogger
from module_payload.demux.stream_demux import StreamDemux, _NEED_MORE, _SKIP_HEADER
from module_payload.parsers.camera_tm_ingest_base import (
    D8_DATA_LEN,
    D8_FRAME_MIN,
    D9_MUX_COUNT,
    FRAME_HEADER,
    FRAME_TYPE_D8,
    FRAME_TYPE_D9,
    _calc_checksum,
    _d9_mux_from_batch,
)
from module_payload.parsers.tm_ingest_batch import (
    PreparedTmFrame,
    TmIngestBatcher,
    process_prepared_async,
)
from module_payload.parsers.xl_camera_tm import XlCameraTmIngest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _d8_partial_header() -> bytes:
    """EB90 D8 出现在缓冲末尾，不够 D8_FRAME_MIN → extract 走 239 break。"""
    return b'\x00' + FRAME_HEADER + bytes([FRAME_TYPE_D8, 0x00])


def _d8_incomplete_by_len() -> bytes:
    """长度字段声称很长，缓冲不够 → extract 246 break；parse_bytes 可走 401。"""
    # header(2)+type(1)+flag(1)+len(2)+seq(2)+payload+chk
    data_len = 0x0100  # 远大于实际
    body_prefix = bytes([FRAME_TYPE_D8, 0x00, (data_len >> 8) & 0xFF, data_len & 0xFF, 0, 0])
    # 凑够 D8_FRAME_MIN 字节以便 parse_bytes 401 判定，但 extract 因 total 超长返回 []
    pad = bytes(D8_FRAME_MIN - 2 - len(body_prefix))
    return FRAME_HEADER + body_prefix + pad


def _d8_short_data_len() -> bytes:
    """data_len < D8_DATA_LEN 且整帧 ≥ D8_FRAME_MIN → _prepare_d8 343。"""
    data_len = 1
    # 8 字节头区 + 1B payload + chk，再垫到 D8_FRAME_MIN
    core = FRAME_HEADER + bytes([FRAME_TYPE_D8, 0x00, 0x00, data_len, 0, 0, 0x11])
    core = core + bytes([_calc_checksum(core[2:])])
    return core + bytes(D8_FRAME_MIN - len(core))


def _d8_truncated_need() -> bytes:
    """len ≥ D8_FRAME_MIN 但 data_len 声称更大 → _prepare_d8 341。"""
    data_len = 0x0100  # need = 8+256+1 = 265 > 54
    body = bytes(
        [FRAME_TYPE_D8, 0x00, (data_len >> 8) & 0xFF, data_len & 0xFF, 0, 0]
    ) + bytes(D8_FRAME_MIN - 8)
    return FRAME_HEADER + body


def _d9(seq: int, slot: bytes = b'\x01\x02\x03\x04') -> bytes:
    data = (bytes(12) + slot[:4].ljust(4, b'\x00'))[:16]
    mid = bytes([seq & 0xFF]) + data
    return bytes([0xEB, FRAME_TYPE_D9]) + mid + bytes([_calc_checksum(mid)])


def _fake_mgr():
    mgr = MagicMock()
    mgr.parse.return_value = [{'id': 'a', 'value': 1}]
    mgr.parse_calc.return_value = {'a': 1.5}
    mgr.get_table_cfg_by_key.return_value = MagicMock(name='T')
    return mgr


def _prepared(**kw):
    defaults = dict(
        table_key='D8',
        name='t',
        payload=b'\x00' * 8,
        raw_frame=b'\x00\x01',
        src_param='serial:COM3',
        src_kind='serial',
        parser_id='xl_camera',
        mgr=_fake_mgr(),
        parse_key='D8',
        ts_ms=1,
    )
    defaults.update(kw)
    return PreparedTmFrame(**defaults)


# ---------------------------------------------------------------------------
# camera_tm_ingest_base
# ---------------------------------------------------------------------------


def test_camera_d9_mux_duplicate_slot_skips() -> None:
    """同一 mux 出现两次 → 127 continue（倒序保留后出现的）。"""
    a = _d9(0, b'\xaa\xaa\xaa\xaa')
    b = _d9(0, b'\xbb\xbb\xbb\xbb')  # same mux 0
    # 不要凑满 8 槽，否则会在遇到重复前就 break
    got = _d9_mux_from_batch([a, b])
    assert list(got.keys()) == [0]
    assert got[0] == b'\xbb\xbb\xbb\xbb'


def test_camera_table_cfg_reload_flag() -> None:
    with patch.object(XlCameraTmIngest, '_load_telemetry_cfg', return_value={'table': {'D8': {'id': 'D8'}}}):
        with patch.object(XlCameraTmIngest, '_get_tm_mgr', return_value=_fake_mgr()) as mgr:
            cfg = XlCameraTmIngest._table_cfg('D8', reload=True)
            assert cfg.get('id') == 'D8'
            mgr.assert_called_with(reload=True)


def test_camera_extract_d8_short_tail_and_incomplete_len() -> None:
    # 整缓冲够进 while，但帧头贴在末尾 → 239
    tail = bytes(60) + FRAME_HEADER + bytes([FRAME_TYPE_D8, 0x00])
    assert XlCameraTmIngest.extract_d8_frames(tail) == []
    assert XlCameraTmIngest.extract_d8_frames(_d8_incomplete_by_len()) == []


def test_camera_extract_d9_short_tail() -> None:
    # 整缓冲够进 while，EB D9 贴末尾不够 20B → 274
    blob = bytes(25) + bytes([0xEB, FRAME_TYPE_D9, 0x01])
    assert XlCameraTmIngest.extract_d9_frames(blob, skip_spans=[]) == []


def test_camera_prepare_d8_len_errors() -> None:
    with pytest.raises(ValueError):
        XlCameraTmIngest._prepare_d8_frame(_d8_truncated_need())
    with pytest.raises(ValueError, match='数据长度异常'):
        XlCameraTmIngest._prepare_d8_frame(_d8_short_data_len())


def test_camera_prepare_d9_mux_none_and_parse_bytes_d8_fallback() -> None:
    fr = _d9(3)
    XlCameraTmIngest._d9_mux_cache.clear()
    prepared = XlCameraTmIngest._prepare_d9_frame(fr, mux32=None, src_param='serial:T')
    assert prepared.table_key == XlCameraTmIngest.TABLE_D9

    # extract 为空但缓冲看起来像 D8 → parse_bytes 401
    raw = _d8_incomplete_by_len()
    with pytest.raises(ValueError):
        XlCameraTmIngest.parse_bytes(raw)


# ---------------------------------------------------------------------------
# payload_config_loader
# ---------------------------------------------------------------------------


def test_merge_pages_skips_missing_board_file() -> None:
    missing = Path('__no_such_board_tm__.json')
    with patch(
        'module_payload.cfg.payload_config_loader.resolve_config_file',
        return_value=missing,
    ):
        with patch(
            'module_payload.cfg.payload_config_loader.XL_TELE_METRY_CFG_FILE'
        ) as xl_file:
            xl_file.exists.return_value = False
            with patch(
                'module_payload.cfg.payload_config_loader.CAMERA_TELE_METRY_CFG_FILE'
            ) as cam:
                cam.exists.return_value = False
                pages = PayloadConfigLoader.merge_telemetry_pages(family='xl')
    assert pages == []


def test_reload_all_swallows_telecontrol_clear_error() -> None:
    with patch(
        'module_payload.cfg.telecontrol_cfg.TeleControlCfgManager._instances'
    ) as inst:
        inst.clear.side_effect = RuntimeError('clear-fail')
        with patch('module_payload.parsers.biu_can_tm.reset_tm_mgr'):
            with patch('module_payload.parsers.xl_can_tm.reset_tm_mgr'):
                with patch('module_payload.parsers.xl_camera_tm.reset_xl_camera_tm_mgr'):
                    with patch('module_payload.parsers.xl_camera_tm_v17.reset_xl_camera_tm_v17_mgr'):
                        with patch('module_payload.parsers.xl_board_tm.reset_xl_board_tm_mgr'):
                            PayloadConfigLoader.reload_all()


def test_cache_key_and_reload_file_telecontrol_and_xl() -> None:
    with patch(
        'module_payload.cfg.telecontrol_cfg.TeleControlCfgManager.cfg_id_for_path',
        return_value='biu',
    ):
        assert PayloadConfigLoader._cache_key_for_path(Path('any.json')) == 'biu'

    with patch(
        'module_payload.cfg.telecontrol_cfg.TeleControlCfgManager.cfg_id_for_path',
        return_value='biu',
    ), patch(
        'module_payload.cfg.telecontrol_cfg.TeleControlCfgManager.reload',
        return_value='biu',
    ) as reld:
        assert PayloadConfigLoader.reload_file(Path('BIU-TeleControlCfg.json')) == 'biu'
        reld.assert_called_once()

    # XL 遥测 reload：写 telemetry:xl 别名 + reset xl_can
    with patch(
        'module_payload.cfg.telecontrol_cfg.TeleControlCfgManager.cfg_id_for_path',
        return_value=None,
    ), patch.object(
        PayloadConfigLoader, '_load_json', return_value={'table': {}}
    ), patch(
        'module_payload.cfg.payload_config_loader.resolve_config_file',
        return_value=Path(XL_TELE_METRY_CFG_NAME),
    ), patch(
        'module_payload.parsers.xl_can_tm.reset_tm_mgr'
    ) as reset_xl:
        key = PayloadConfigLoader.reload_file(Path(XL_TELE_METRY_CFG_NAME))
        assert key
        assert PayloadConfigLoader._cache.get('telemetry:xl') == {'table': {}}
        reset_xl.assert_called_once()


# ---------------------------------------------------------------------------
# stream_demux
# ---------------------------------------------------------------------------


def test_demux_compact_branches_333_341_355() -> None:
    """compact_at 下限为 64，需推高 _start 后才能打中 compact 分支。"""
    demux = StreamDemux(
        [
            {
                'id': 'only',
                'framing': 'header_len',
                'header': 'EB90',
                'frameSize': 8,
                'typeAt': 2,
                'type': 'D8',
                'assemblerId': 'x',
            }
        ],
        compact_at=64,
    )
    bad = bytes([0xEB, 0x90, 0xAA, 1, 2, 3, 4, 5])
    demux.write(bad * 9)  # 72B mismatch → 途中 333 compact
    assert demux.drain() == []

    demux2 = StreamDemux(
        [
            {
                'id': 'ok',
                'framing': 'header_len',
                'header': 'AA55',
                'frameSize': 8,
                'assemblerId': 'p',
            }
        ],
        compact_at=64,
    )
    good = b'\xaa\x55\x01\x02\x03\x04\x05\x06'
    demux2.write(good * 9)  # 341 compact
    assert len(demux2.drain()) == 9

    # 355: header_trailer 超 max → for 结束走滑窗 compact
    demux4 = StreamDemux(
        [
            {
                'id': 'ht',
                'framing': 'header_trailer',
                'header': 'AA',
                'trailer': 'FF',
                'assemblerId': 'p',
                'maxFrameSize': 4,
                'minFrameSize': 3,
            }
        ],
        compact_at=64,
    )
    demux4.write(b'\xaa\x01\x02\x03' * 20 + b'\xaa\xff')
    demux4.drain()

    # 322: extract 用 header_len，type 匹配循环遇到 header_trailer 时 continue
    demux5 = StreamDemux(
        [
            {
                'id': 'hl',
                'framing': 'header_len',
                'header': 'EB90',
                'frameSize': 8,
                'typeAt': 2,
                'type': 'D8',
                'assemblerId': 'a',
            },
            {
                'id': 'ht',
                'framing': 'header_trailer',
                'header': 'EB90',
                'trailer': '0D0A',
                'typeAt': 2,
                'type': 'AA',
                'assemblerId': 'b',
                'maxFrameSize': 16,
                'minFrameSize': 6,
            },
        ]
    )
    # type=AA：hl 不匹配；循环到 ht 时 framing 不同 → 322，最终当 mismatch 消费
    demux5.write(bytes([0xEB, 0x90, 0xAA, 1, 2, 3, 4, 5]))
    assert demux5.drain() == []

    # 365 / 367: _extract_at 半截头 / 头不匹配
    demux6 = StreamDemux(
        [{'id': 'h', 'framing': 'header_len', 'header': 'EB90', 'frameSize': 8, 'assemblerId': 'p'}]
    )
    assert demux6._extract_at(0, demux6._routes[0]) is _NEED_MORE
    demux6.write(b'\x11\x22\x33\x44\x55\x66\x77\x88')
    assert demux6._extract_at(0, demux6._routes[0]) is _SKIP_HEADER


# ---------------------------------------------------------------------------
# tm_ingest_batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_prepared_skips_empty_curve_points() -> None:
    redis = AsyncMock()
    pipe = MagicMock()
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.zremrangebyrank = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])
    redis.pipeline = MagicMock(return_value=pipe)
    redis.set = AsyncMock()

    mgr = _fake_mgr()
    mgr.parse_calc.return_value = {}  # empty → curve row with no points → 266 continue
    frame = _prepared(mgr=mgr)
    with patch(
        'module_payload.redis_store.set_telemetry',
        AsyncMock(return_value={'fields': [], 'name': 't', 'ts': ''}),
    ), patch(
        'module_payload.parsers.tm_ingest_batch.enqueue',
        AsyncMock(),
    ), patch(
        'module_payload.parsers.tm_ingest_batch.should_archive_tm_mysql',
        return_value=False,
    ):
        await process_prepared_async(redis, [frame])
    pipe.zadd.assert_not_called()


def test_batcher_flush_and_latest_none_paths() -> None:
    b = TmIngestBatcher()
    # flush_loop: None redis / empty batch → 339 continue
    items = [(None, [1], 'D8'), (MagicMock(), [], 'D8')]

    def _flush_once():
        for item in items:
            redis, batch, key = item
            if not batch or redis is None:
                continue
            raise AssertionError('should not process')

    # 直接调用循环体逻辑不够；用有限次 get 包装
    class _Q:
        def __init__(self):
            self._i = 0
            self._items = items + [(MagicMock(), None, 'x')]  # third also continue via not batch

        def get(self):
            if self._i >= len(self._items):
                raise SystemExit
            v = self._items[self._i]
            self._i += 1
            return v

    b._flush_q = _Q()  # type: ignore
    try:
        b._flush_loop()
    except SystemExit:
        pass

    # latest_loop: redis None → 372
    b2 = TmIngestBatcher()
    b2._last_frame['D8'] = _prepared()
    b2._latest_snap.clear()
    b2._redis = None
    calls = {'n': 0}

    def _wait(_timeout=None):
        calls['n'] += 1
        return calls['n'] >= 3

    b2._latest_stop.wait = _wait  # type: ignore
    b2._latest_loop()

    # snap None → 375 continue
    b3 = TmIngestBatcher()
    b3._redis = MagicMock()
    b3._last_frame['D8'] = _prepared()
    b3._latest_snap.clear()
    calls3 = {'n': 0}

    def _wait3(_timeout=None):
        calls3['n'] += 1
        return calls3['n'] >= 2

    b3._latest_stop.wait = _wait3  # type: ignore
    with patch('module_payload.parsers.tm_ingest_batch._write_latest_from_frame') as w:
        b3._latest_loop()
        w.assert_not_called()


# ---------------------------------------------------------------------------
# base_collector outer KeyboardInterrupt (643-644)
# ---------------------------------------------------------------------------


def test_base_collector_outer_keyboard_interrupt_on_sleep() -> None:
    class Coll(BaseCollector):
        def setup(self):
            return True

        def teardown(self):
            pass

        def read_and_parse(self):
            pass

        def execute_command(self, command):
            return {'ok': True}

    c = Coll.__new__(Coll)
    c.device_id = 'serial:COM9'
    c.config = {'loop_interval_s': 0.001, 'full_duplex': False}
    c._running = False
    c._rx_thread = None
    c._redis = MagicMock()
    c._write_status = MagicMock()
    c._consume_control = MagicMock()
    c._consume_commands = MagicMock()
    c._heartbeat = MagicMock()
    c.teardown = MagicMock()
    c._is_full_duplex = MagicMock(return_value=False)  # type: ignore
    sleeps = {'n': 0}

    def _sleep(_t):
        sleeps['n'] += 1
        # 循环末尾 time.sleep 在内层 try 外 → 外层 KeyboardInterrupt 643-644
        raise KeyboardInterrupt

    with patch('module_payload.collectors.base_collector.time.sleep', _sleep):
        c.run()
    assert c._running is False


# ---------------------------------------------------------------------------
# connection_transfer_logger line 139 (empty payload early return)
# ---------------------------------------------------------------------------


def test_xfer_append_can_assembled_empty_returns(tmp_path: Path) -> None:
    log = ConnectionTransferLogger('can:3:0:0', kind='can', root_dir=tmp_path)
    try:
        log.append_can_assembled(b'')  # 139 return
        log.append_can_assembled(b'\x01\x02')
    finally:
        log.close()


# ---------------------------------------------------------------------------
# __main__ entry points (remove pragma dependency by executing as __main__)
# ---------------------------------------------------------------------------


def test_runner_main_callable() -> None:
    """脚本 ``if __name__`` 保持 pragma；这里覆盖可测的 ``main()`` 本体。"""
    from module_payload.collectors.runner import main as runner_main
    from module_payload.fileplay import worker as worker_mod

    with patch('sys.argv', ['runner', 'serial', 'serial:COM1', '{}']):
        with patch('module_payload.collectors.runner.run_collector') as rc:
            runner_main()
            rc.assert_called_once()
    assert callable(worker_mod.main)