"""can_collector 覆盖率补齐：mock gpcan 客户端，不依赖 DEMO 硬件。"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from gpcan import CanProtocolType, CanRetCode
from module_payload.assemblers.base import AssembledPayload
from module_payload.collectors.can_collector import CanCollector, _assembler_to_protocol
from module_payload.collectors.redis_sync import dumps_json
from module_payload.constants import (
    ASSEMBLER_CAN_BIU,
    ASSEMBLER_CAN_XL,
    ASSEMBLER_PASSTHROUGH,
)


_OK = int(CanRetCode.CAN_RET_CODE_OK)
_ERR = int(CanRetCode.CAN_RET_CODE_ERR)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _built(frames=None):
    if frames is None:
        frames = [SimpleNamespace(un_id=1, str_data=b'\x01')]
    return SimpleNamespace(frames=frames)


class _Builder:
    """Real builder object so ``hasattr`` does not always succeed (unlike MagicMock)."""

    def __init__(self) -> None:
        self._telemetry = _built()
        self._sync = _built()
        self._tc = _built()
        self._bc = _built()

    def build_telemetry_request(self, **_kwargs):
        return self._telemetry

    def build_time_sync(self, **_kwargs):
        return self._sync

    def build_telecommand(self, data=b''):
        return self._tc

    def build_broadcast(self, data=b''):
        return self._bc

    def foo(self, **_kwargs):
        return _built([1])


def _fake_client(**kwargs) -> MagicMock:
    client = MagicMock()
    client.init_can.return_value = kwargs.get('init', _OK)
    client.open_can.return_value = kwargs.get('open', _OK)
    client.close_can.return_value = _OK
    client.deinit_can.return_value = _OK
    client.get_protocol.return_value = kwargs.get('proto', CanProtocolType.BIU)
    client.send_msg.return_value = kwargs.get('send_msg', _OK)
    client.send.return_value = kwargs.get('send', _OK)
    client.recv.return_value = kwargs.get('recv', [])
    cable = SimpleNamespace(n_node_addr_to=0x0D, n_cable_flag=0)
    client.get_cable_param.return_value = cable
    client.builder = _Builder()
    return client


def _can(**kwargs) -> CanCollector:
    """``__new__`` 装配，跳过 BaseCollector.__init__ / Redis。"""
    c = CanCollector.__new__(CanCollector)
    c.device_id = kwargs.pop('device_id', 'can:0:0')
    c.config = kwargs.pop('config', {'vendor': 0, 'dev_index': 0, 'can_index': 0})
    c._running = True
    c._redis = kwargs.pop('redis', MagicMock())
    c._rx_count = 0
    c._tx_count = 0
    c._assembler = None
    c._assembler_id = None
    c._assemblers = {}
    c._demux = None
    c._demux_fp = None
    c._xfer_loggers = {}
    c._xfer_tags = {}
    c._session_cache = {}
    c._session_cache_mono = {}
    c._assembled_mono = {}
    c._pipeline_lock = threading.RLock()
    c._rx_thread = None
    c._io_log_last_mono = {}
    c._stream_io_lock = threading.Lock()
    c._stream_io_bufs = {}
    c._stream_io_seq = {}
    c._stream_io_flushed_seq = {}
    c._channels = {}
    c._timed_tm = False
    c._timed_tm_family = 'biu'
    c._timed_tm_tick = 0
    c._timed_tm_next = 0.0
    c._timed_tm_prefer_can = None
    c._timed_sync = False
    c._timed_sync_family = 'biu'
    c._timed_sync_next = 0.0
    c._timed_sync_last_can = None
    c._gnss_valid = True
    c._start_utc = {'biu': '', 'xl': ''}
    for k, v in kwargs.items():
        setattr(c, k, v)
    return c


def _ch(can_index: int = 0, client: MagicMock | None = None, **cfg) -> dict:
    client = client or _fake_client()
    return {
        'client': client,
        'cfg': {'can_index': can_index, 'assembler_id': ASSEMBLER_CAN_BIU, **cfg},
        'channel_device_id': f'can:0:0:{can_index}',
    }


class _FakeTs:
    offset_ms = 0

    def set_payload_time(self, ms: int) -> None:
        self.offset_ms = int(ms) - 1_000_000

    def set_offset(self, ms: int) -> None:
        self.offset_ms = int(ms)

    def get_system_time_ms(self) -> int:
        return 1_700_000_123


# ---------------------------------------------------------------------------
# _assembler_to_protocol / __init__
# ---------------------------------------------------------------------------


def test_assembler_to_protocol_mapping() -> None:
    assert _assembler_to_protocol(ASSEMBLER_CAN_XL) == CanProtocolType.XL
    assert _assembler_to_protocol(ASSEMBLER_CAN_BIU) == CanProtocolType.BIU
    assert _assembler_to_protocol(ASSEMBLER_PASSTHROUGH) == CanProtocolType.NONE
    assert _assembler_to_protocol(None) == CanProtocolType.NONE
    assert _assembler_to_protocol('  ') == CanProtocolType.NONE
    assert _assembler_to_protocol('unknown') == CanProtocolType.NONE


def test_init_state(monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )
    c = CanCollector('can:1:2', {'vendor': 1, 'dev_index': 2})
    assert c._channels == {}
    assert c._timed_tm is False
    assert c._gnss_valid is True
    assert c._start_utc == {'biu': '', 'xl': ''}


# ---------------------------------------------------------------------------
# setup / open / close
# ---------------------------------------------------------------------------


def test_setup_partial_open_fail_records_last_error(monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )
    c = CanCollector(
        'can:0:0',
        {'vendor': 0, 'dev_index': 0, 'channels': [{'can_index': 0}]},
    )
    c._write_channel_status = MagicMock()
    c._write_status = MagicMock()
    with patch('gpcan.CanProtocolClient', side_effect=RuntimeError('nohw')):
        assert c.setup() is False
    args = c._write_status.call_args[0]
    assert '打开异常' in args[1] or 'CAN' in args[1]


def test_tick_when_disabled() -> None:
    c = _can()
    c._timed_tm = False
    c._tick_timed_tm(time.monotonic())
    c._timed_sync = False
    c._tick_timed_sync(time.monotonic())


def test_setup_no_channels_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )
    c = CanCollector('can:0:0', {})
    c._write_status = MagicMock()
    assert c.setup() is False
    c._write_status.assert_called()


def test_setup_open_success_and_already_open(monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )
    client = _fake_client()
    c = CanCollector(
        'can:0:0',
        {
            'vendor': 0,
            'dev_index': 0,
            'channels': [
                {
                    'can_index': 0,
                    'baud_rate': 500,
                    'cable_flag': 0,
                    'node_addr_to': 0x0D,
                    'assembler_id': ASSEMBLER_CAN_BIU,
                }
            ],
        },
    )
    c._write_channel_status = MagicMock()
    c._write_status = MagicMock()
    c._get_session_cached = MagicMock(return_value={})
    c._sync_client_protocol = MagicMock(return_value=ASSEMBLER_CAN_BIU)

    with patch('gpcan.CanProtocolClient', return_value=client):
        assert c.setup() is True
    assert 0 in c._channels

    # already open → refresh status only
    ok, err = c._open_channel_client(0, {'can_index': 0})
    assert ok is True and err == ''


def test_setup_single_can_index_form(monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )
    client = _fake_client()
    c = CanCollector('can:0:0', {'vendor': 0, 'dev_index': 0, 'can_index': 1})
    c._write_channel_status = MagicMock()
    c._get_session_cached = MagicMock(side_effect=RuntimeError('warm'))
    c._sync_client_protocol = MagicMock()
    with patch('gpcan.CanProtocolClient', return_value=client):
        assert c.setup() is True
    assert 1 in c._channels


def test_open_channel_init_open_exception_paths(monkeypatch) -> None:
    c = _can()
    c._write_channel_status = MagicMock()

    # init fail
    client = _fake_client(init=_ERR)
    with patch('gpcan.CanProtocolClient', return_value=client):
        ok, err = c._open_channel_client(0, {'can_index': 0})
    assert ok is False and '初始化失败' in err

    # open fail + deinit exception
    client = _fake_client(open=_ERR)
    client.deinit_can.side_effect = RuntimeError('d')
    with patch('gpcan.CanProtocolClient', return_value=client):
        ok, err = c._open_channel_client(1, {'can_index': 1, 'assembler_id': ASSEMBLER_CAN_XL})
    assert ok is False and '打开失败' in err

    # constructor exception
    with patch('gpcan.CanProtocolClient', side_effect=RuntimeError('boom')):
        ok, err = c._open_channel_client(2, {'can_index': 2})
    assert ok is False and '打开异常' in err


def test_close_channel_and_teardown() -> None:
    c = _can()
    c._write_channel_status = MagicMock()
    c._stop_all_timers = MagicMock(wraps=c._stop_all_timers)
    client = _fake_client()
    client.close_can.side_effect = RuntimeError('c')
    logger = MagicMock()
    logger.close.side_effect = RuntimeError('l')
    c._channels[0] = _ch(0, client)
    c._xfer_loggers['can:0:0:0'] = logger
    c._xfer_tags['can:0:0:0'] = 't'
    c._timed_tm = True
    c._timed_sync = True

    c._close_channel(0)
    assert 0 not in c._channels
    c._stop_all_timers.assert_called()
    c._close_channel(9)  # missing

    c._channels[3] = _ch(3)
    with patch.object(CanCollector.__bases__[0], 'teardown', MagicMock()) as base_td:
        c.teardown()
    assert c._channels == {}
    base_td.assert_called_once()


# ---------------------------------------------------------------------------
# handle_control / cable
# ---------------------------------------------------------------------------


def test_handle_control_ops() -> None:
    c = _can()
    ch = _ch(0)
    c._channels[0] = ch
    c._invalidate_session_cache = MagicMock()
    c._sync_xfer_logger = MagicMock()
    c._reset_tm_parsers = MagicMock()
    c._sync_client_protocol = MagicMock(side_effect=[None, RuntimeError('x')])
    c._open_channel_client = MagicMock(return_value=(True, ''))
    c._close_channel = MagicMock()
    c._set_channel_cable = MagicMock()

    c.handle_control({'op': 'session_changed'})
    c.handle_control({'op': 'rebind'})
    c._channels[1] = _ch(1)
    c.handle_control({'op': 'source_changed'})  # second sync raises
    c.handle_control({'op': 'reload_tm_cfg'})
    c.handle_control({'op': 'open_channel', 'can_index': 2, 'config': {'can_index': 2}})
    c.handle_control({'op': 'close_channel', 'can_index': 0})
    c.handle_control({'op': 'set_cable', 'can_index': 0, 'cable_flag': 1})
    c._open_channel_client.assert_called()
    c._close_channel.assert_called_with(0)
    c._set_channel_cable.assert_called()


def test_set_channel_cable() -> None:
    c = _can()
    c._set_channel_cable(0, {'node_addr_to': 1})  # missing channel
    client = _fake_client()
    c._channels[0] = _ch(0, client, cable_flag=0)
    c._set_channel_cable(0, {'node_addr_to': 0x11, 'cable_flag': 1})
    client.set_cable_param.assert_called()
    assert c._channels[0]['cfg']['node_addr_to'] == 0x11
    assert c._channels[0]['cfg']['cable_flag'] == 1
    # partial update keeps current
    c._set_channel_cable(0, {})
    assert c._channels[0]['cfg']['cable_flag'] == 1


# ---------------------------------------------------------------------------
# timers / sync protocol / cfg
# ---------------------------------------------------------------------------


def test_cfg_assembler_and_sync_protocol() -> None:
    c = _can()
    ch = _ch(0)
    ch['cfg'] = {}
    assert c._cfg_assembler_id(ch) is None
    ch['cfg'] = {'assembler_id': '  '}
    assert c._cfg_assembler_id(ch) is None
    ch['cfg'] = {'assembler_id': 'nope'}
    assert c._cfg_assembler_id(ch) is None
    ch['cfg'] = {'assembler_id': ASSEMBLER_CAN_XL}
    assert c._cfg_assembler_id(ch) == ASSEMBLER_CAN_XL

    client = _fake_client(proto=CanProtocolType.XL)
    ch = _ch(0, client, assembler_id=ASSEMBLER_CAN_XL)
    # allow_skip_redis + already matching
    assert c._sync_client_protocol(ch) == ASSEMBLER_CAN_XL

    # mismatch → set_protocol_param
    client.get_protocol.return_value = CanProtocolType.XL
    c._get_session_cached = MagicMock(return_value={'assemblerId': ASSEMBLER_CAN_BIU})
    assert c._sync_client_protocol(ch, allow_skip_redis=False) == ASSEMBLER_CAN_BIU
    client.set_protocol_param.assert_called()

    c._get_session_cached = MagicMock(return_value={'assemblerId': 'garbage'})
    ch['cfg'] = {}
    client.get_protocol.return_value = CanProtocolType.NONE
    aid = c._sync_client_protocol(ch, allow_skip_redis=False)
    assert aid == ASSEMBLER_CAN_BIU

    c._get_session_cached = MagicMock(return_value={'assemblerId': ASSEMBLER_PASSTHROUGH})
    client.get_protocol.return_value = CanProtocolType.BIU
    assert c._sync_client_protocol(ch, allow_skip_redis=False) == ASSEMBLER_PASSTHROUGH


def test_timer_family_and_handle_timer(monkeypatch) -> None:
    c = _can()
    c._channels[0] = _ch(0)
    monkeypatch.setattr(
        'module_payload.collectors.can_timers.time_sync_for_family',
        lambda _f: _FakeTs(),
    )

    assert c._timer_family({'family': 'xl'}) == 'xl'
    assert c._timer_family({'family': 'biu'}) == 'biu'
    c._timed_tm_family = 'xl'
    assert c._timer_family({}) == 'xl'
    c._timed_tm_family = 'biu'
    assert c._timer_family({}) == 'biu'

    ch = c._channels[0]
    out = c._handle_timer(ch, {'kind': 'timed_tm', 'enable': True, 'family': 'biu'})
    assert out['success'] is True and out['timedTm'] is True
    assert c._timed_tm_prefer_can == 0
    out = c._handle_timer(ch, {'kind': 'timed_tm', 'enable': False})
    assert out['timedTm'] is False

    out = c._handle_timer(ch, {'kind': 'timed_sync', 'enable': True, 'gnssValid': False, 'family': 'xl'})
    assert c._timed_sync is True and c._gnss_valid is False
    out = c._handle_timer(ch, {'kind': 'timed_sync', 'enable': False, 'gnss_valid': True})
    assert c._timed_sync is False

    out = c._handle_timer(ch, {'kind': 'set_gnss', 'gnssValid': True})
    assert out['gnssValid'] is True

    out = c._handle_timer(ch, {'kind': 'get_status', 'family': 'biu'})
    assert out['message'] == 'OK'

    out = c._handle_timer(ch, {'kind': 'set_start', 'utc': '2020-01-01 00:00:00', 'family': 'biu'})
    assert out['utc'].startswith('2020')
    out = c._handle_timer(ch, {'kind': 'set_offset', 'offsetMs': 42})
    assert out['offsetMs'] == 42
    out = c._handle_timer(ch, {'kind': 'reset_start'})
    assert out['offsetMs'] == 0
    out = c._handle_timer(ch, {'kind': 'nope'})
    assert out['success'] is False


def test_timed_tm_pick_and_can_info() -> None:
    c = _can()
    assert c._timed_tm_pick() == (None, None)
    assert c._timed_tm_can_info() == {'timedTmCan': '', 'timedTmDeviceId': ''}

    c._channels[0] = _ch(0, cable_flag=0)
    c._channels[1] = _ch(1, cable_flag=1)
    c._timed_tm = True
    c._timed_tm_prefer_can = 1
    idx, ch = c._timed_tm_pick()
    assert idx == 1 and ch is c._channels[1]
    info = c._timed_tm_can_info()
    assert info['timedTmCan'] == 'CAN-B'
    assert info['timedTmDeviceId']

    c._timed_tm_prefer_can = 99
    # prefer gone → first open
    idx, _ = c._timed_tm_pick()
    assert idx == 0

    c._channels.clear()
    c._timed_tm = True
    assert c._timed_tm_can_info() == {'timedTmCan': '', 'timedTmDeviceId': ''}


def test_tick_timers_and_send_quiet(monkeypatch) -> None:
    c = _can()
    c._timed_tm = True
    c._timed_sync = True
    c._tick_timers()  # no channels → stop
    assert c._timed_tm is False

    client = _fake_client()
    c._channels[0] = _ch(0, client)
    c._channels[1] = _ch(1, _fake_client())
    c._timed_tm = True
    c._timed_tm_family = 'biu'
    c._timed_tm_next = 0.0
    c._timed_tm_prefer_can = 0
    c._timed_sync = True
    c._timed_sync_family = 'biu'
    c._timed_sync_next = 0.0
    c._sync_client_protocol = MagicMock(return_value=ASSEMBLER_CAN_BIU)
    monkeypatch.setattr(
        'module_payload.collectors.can_timers.time_sync_for_family',
        lambda _f: _FakeTs(),
    )

    c._tick_timers()
    assert c._timed_tm_tick == 1
    assert c._timed_sync_last_can == 0

    # not yet due
    c._timed_tm_next = time.monotonic() + 10
    c._timed_sync_next = time.monotonic() + 10
    tick_before = c._timed_tm_tick
    c._tick_timers()
    assert c._timed_tm_tick == tick_before

    # xl family
    c._timed_tm_family = 'xl'
    c._timed_tm_next = 0.0
    c._tick_timed_tm(time.monotonic())
    assert c._timed_tm_tick == tick_before + 1

    # pick fails → disable
    c._channels.clear()
    c._timed_tm = True
    c._tick_timed_tm(time.monotonic())
    assert c._timed_tm is False

    # sync with empty open_ids after clear
    c._timed_sync = True
    c._tick_timed_sync(time.monotonic())
    assert c._timed_sync is False

    # quiet send edge: no method / no frames / send ok increments
    c._channels[0] = _ch(0, client)
    c._sync_client_protocol = MagicMock()
    c._tx_count = 0
    assert not hasattr(client.builder, 'missing')
    c._send_protocol_quiet(c._channels[0], 'missing', {})
    client.builder._telemetry = None
    c._send_protocol_quiet(c._channels[0], 'build_telemetry_request', {})
    client.builder._telemetry = SimpleNamespace(frames=None)
    c._send_protocol_quiet(c._channels[0], 'build_telemetry_request', {})
    client.builder._telemetry = _built([SimpleNamespace()])
    client.send_msg.return_value = _OK
    c._send_protocol_quiet(c._channels[0], 'build_telemetry_request', {})
    assert c._tx_count == 1

    # tick exceptions swallowed
    c._channels[0] = _ch(0)
    c._timed_tm = True
    c._timed_sync = True
    c._tick_timed_tm = MagicMock(side_effect=RuntimeError('t'))  # type: ignore
    c._tick_timed_sync = MagicMock(side_effect=RuntimeError('s'))  # type: ignore
    c._tick_timers()


def test_tick_timed_sync_missing_channel(monkeypatch) -> None:
    c = _can()
    c._timed_sync = True
    c._timed_sync_next = 0.0
    c._channels[0] = _ch(0)
    monkeypatch.setattr(
        'module_payload.collectors.can_timers.next_round_robin_can',
        lambda _ids, _last: 99,
    )
    monkeypatch.setattr(
        'module_payload.collectors.can_timers.time_sync_for_family',
        lambda _f: _FakeTs(),
    )
    c._tick_timed_sync(time.monotonic())  # ch missing → return early


# ---------------------------------------------------------------------------
# read / ingest / heartbeat
# ---------------------------------------------------------------------------


def test_read_and_parse_paths() -> None:
    c = _can()
    c._tick_timers = MagicMock()
    c._push_io = MagicMock()
    c._push_stream_io = MagicMock()
    c._ingest_can_frames = MagicMock()

    # recv exception
    bad = _fake_client()
    bad.recv.side_effect = RuntimeError('r')
    c._channels[0] = _ch(0, bad)
    c.read_and_parse()

    # empty frames
    client = _fake_client(recv=[])
    c._channels[0] = _ch(0, client)
    c.read_and_parse()

    # frames with good / bad objs + ingest boom
    frame_ok = SimpleNamespace(str_data=b'\xAA\xBB', un_id=0x123)
    frame_bad = SimpleNamespace(str_data=b'\x01', un_id='x')  # int() may still work? use property boom

    class BoomFrame:
        @property
        def str_data(self):
            raise RuntimeError('bad')

        un_id = 1

    client.recv.return_value = [frame_ok, BoomFrame(), SimpleNamespace(str_data=b'', un_id=2)]
    c._ingest_can_frames = MagicMock(side_effect=RuntimeError('ing'))
    c.read_and_parse()
    assert c._rx_count >= 1
    c._tick_timers.assert_called()


def test_heartbeat_channel_status() -> None:
    c = _can()
    c._write_channel_status = MagicMock(side_effect=[None, RuntimeError('x')])
    with patch.object(CanCollector.__bases__[0], '_heartbeat', MagicMock()):
        c._channels[0] = _ch(0)
        c._channels[1] = {'client': MagicMock(), 'cfg': {}, 'channel_device_id': ''}
        c._channels[2] = _ch(2)
        c._heartbeat()


def test_ingest_can_frames(monkeypatch) -> None:
    c = _can()
    c._emit_assembler_errors = MagicMock()
    c._dispatch_payloads = MagicMock()
    c._xfer_append_can_assembled = MagicMock()

    c._ingest_can_frames('can:0:0:0', [])  # early

    frames = [SimpleNamespace(str_data=b'\x01\x02', un_id=1)]
    asm = MagicMock()
    asm.feed_frames.return_value = [b'\x11\x22', AssembledPayload(data=b'\x33', meta={})]
    monkeypatch.setattr(
        'module_payload.collectors.can_collector.get_session_sync',
        lambda *_a, **_k: {'assemblerId': ASSEMBLER_CAN_BIU, 'parserId': 'tm_can_biu'},
    )
    monkeypatch.setattr(
        'module_payload.assemblers.create_assembler',
        lambda _aid: asm,
    )
    monkeypatch.setattr(
        'module_payload.parsers.resolve_parser',
        lambda _pid: None,
    )
    c._ingest_can_frames('can:0:0:0', frames)
    c._dispatch_payloads.assert_called()
    assert c._xfer_append_can_assembled.call_count >= 1

    # passthrough without feed_frames (only feed)
    class PtAsm:
        def feed(self, data):
            return [data] if data else []

    monkeypatch.setattr(
        'module_payload.collectors.can_collector.get_session_sync',
        lambda *_a, **_k: {'assemblerId': ASSEMBLER_PASSTHROUGH, 'parserId': ''},
    )
    monkeypatch.setattr('module_payload.assemblers.create_assembler', lambda _aid: PtAsm())
    c._assembler = None
    c._assembler_id = None
    c._ingest_can_frames('can:0:0:0', [SimpleNamespace(str_data=b'\xCC', un_id=1)])

    # invalid assembler id clamped to BIU; empty payloads
    asm_empty = MagicMock()
    asm_empty.feed_frames.return_value = []
    monkeypatch.setattr(
        'module_payload.collectors.can_collector.get_session_sync',
        lambda *_a, **_k: {'assemblerId': 'not-a-real-assembler'},
    )
    monkeypatch.setattr('module_payload.assemblers.create_assembler', lambda _aid: asm_empty)
    c._assembler = None
    c._ingest_can_frames('can:0:0:0', frames)

    # outer exception + push_pipeline_error boom
    monkeypatch.setattr(
        'module_payload.collectors.can_collector.get_session_sync',
        MagicMock(side_effect=RuntimeError('sess')),
    )
    with patch(
        'module_payload.collectors.can_collector.push_pipeline_error',
        side_effect=RuntimeError('pe'),
    ):
        c._ingest_can_frames('can:0:0:0', frames)

    # push_pipeline_error succeeds on exception path
    with patch('module_payload.collectors.can_collector.push_pipeline_error') as ppe:
        c._ingest_can_frames('can:0:0:0', frames)
    ppe.assert_called()

    # payload with empty data skipped for xfer
    asm3 = MagicMock()
    asm3.feed_frames.return_value = [
        b'',
        AssembledPayload(data=b'', meta={}),
        SimpleNamespace(data=None),
        b'\xEE',
    ]
    monkeypatch.setattr(
        'module_payload.collectors.can_collector.get_session_sync',
        lambda *_a, **_k: {'assemblerId': ASSEMBLER_CAN_BIU, 'parserId': ''},
    )
    monkeypatch.setattr('module_payload.assemblers.create_assembler', lambda _aid: asm3)
    c._assembler = None
    c._xfer_append_can_assembled.reset_mock()
    c._dispatch_payloads.reset_mock()
    c._ingest_can_frames('can:0:0:0', frames)
    c._dispatch_payloads.assert_called()
    c._xfer_append_can_assembled.assert_called_with(b'\xEE', 'can:0:0:0')


# ---------------------------------------------------------------------------
# execute_command / consume_commands
# ---------------------------------------------------------------------------


def test_execute_command_branches(monkeypatch) -> None:
    c = _can()
    with pytest.raises(RuntimeError, match='未打开'):
        c.execute_command({'can_index': 9})

    client = _fake_client()
    c._channels[0] = _ch(0, client)
    c._sync_client_protocol = MagicMock(return_value=ASSEMBLER_CAN_BIU)
    c._handle_timer = MagicMock(return_value={'success': True, 'message': 't'})
    monkeypatch.setattr(
        'module_payload.collectors.can_timers.time_sync_for_family',
        lambda _f: _FakeTs(),
    )

    assert c.execute_command({'can_index': 0, 'timer': {'kind': 'get_status'}})['success']

    # protocol_build unknown / empty / ok / send fail
    r = c.execute_command({'can_index': 0, 'protocol_build': {'method': '', 'kwargs': {}}})
    assert r['success'] is False
    r = c.execute_command({'can_index': 0, 'protocol_build': {'method': 'nope'}})
    assert '未知协议' in r['message']
    client.builder.foo = lambda **_k: None  # type: ignore[method-assign]
    r = c.execute_command({'can_index': 0, 'protocol_build': {'method': 'foo'}})
    assert '无帧' in r['message']
    client.builder.foo = lambda **_k: _built([1])  # type: ignore[method-assign]
    r = c.execute_command(
        {
            'can_index': 0,
            'protocol_build': {'method': 'foo', 'kwargs': {'data': [1, 2, 256]}},
        }
    )
    assert r['success'] is True
    client.send_msg.return_value = _ERR
    r = c.execute_command({'can_index': 0, 'protocol_build': {'method': 'foo', 'kwargs': {}}})
    assert '发送失败' in r['message']
    client.send_msg.return_value = _OK

    # business NONE
    client.get_protocol.return_value = CanProtocolType.NONE
    r = c.execute_command({'can_index': 0, 'use_business': True, 'hex': 'AA'})
    assert '透传' in r['message']

    client.get_protocol.return_value = CanProtocolType.BIU
    client.builder._tc = None
    r = c.execute_command({'can_index': 0, 'use_business': True, 'hex': 'AA BB'})
    assert '业务组包失败' in r['message']
    client.builder._tc = _built([1])
    r = c.execute_command({'can_index': 0, 'use_business': True, 'hex': 'AA'})
    assert r['success'] is True
    client.builder._bc = _built([1])
    r = c.execute_command(
        {'can_index': 0, 'use_business': True, 'hex': 'AA', 'broadcast': True}
    )
    assert r['success'] is True

    # raw
    r = c.execute_command({'can_index': 0, 'hex': 'AA'})
    assert 'frame_id' in r['message']
    r = c.execute_command({'can_index': 0, 'frame_id': 1, 'hex': 'AA BB CC DD EE FF 11 22 33'})
    assert '最多8字节' in r['message']
    r = c.execute_command({'can_index': 0, 'frame_id': 0x123, 'hex': 'AA BB'})
    assert r['success'] is True
    r = c.execute_command({'can_index': 0, 'frame_id': 1, 'hex': ''})
    assert r['success'] is True
    client.send.return_value = _ERR
    r = c.execute_command({'can_index': 0, 'frame_id': 1, 'hex': '01'})
    assert r['success'] is False


def test_consume_commands() -> None:
    c = _can()
    client = _fake_client()
    c._channels[0] = _ch(0, client)
    c._push_history = MagicMock()
    c.execute_command = MagicMock(
        side_effect=[
            {'success': True, 'message': 'OK'},
            RuntimeError('boom'),
            {'success': True, 'message': 't'},
        ]
    )

    raw_ok = dumps_json({'cmd_id': 'c1', 'hex': 'AA'})
    raw_bad = dumps_json({'hex': 'BB'})
    raw_timer = dumps_json({'timer': {'kind': 'get_status'}, 'cmd_id': 't1'})
    raw_empty = dumps_json(None)
    c._redis.lpop = MagicMock(side_effect=[raw_ok, raw_bad, raw_timer, raw_empty, None])
    c._consume_commands()
    assert c._redis.setex.call_count >= 3
    c._push_history.assert_called()


# ---------------------------------------------------------------------------
# leftover collector misses (base / process_manager / serial / runner)
# ---------------------------------------------------------------------------


def test_base_leftover_misses(monkeypatch) -> None:
    from module_payload.collectors.base_collector import BaseCollector

    c = BaseCollector.__new__(BaseCollector)
    c.device_id = 'serial:COM9'
    c.config = {'fullDuplex': False, 'loop_interval_s': 0.0}
    c._running = False
    c._redis = MagicMock()
    c._rx_count = 0
    c._tx_count = 0
    c._assembler = None
    c._assembler_id = None
    c._assemblers = {}
    c._demux = None
    c._demux_fp = None
    c._xfer_loggers = {}
    c._xfer_tags = {}
    c._session_cache = {}
    c._session_cache_mono = {}
    c._assembled_mono = {}
    c._pipeline_lock = threading.RLock()
    c._rx_thread = None
    c._io_log_last_mono = {}
    c._stream_io_lock = threading.Lock()
    c._stream_io_bufs = {}
    c._stream_io_seq = {}
    c._stream_io_flushed_seq = {}

    logger = MagicMock()
    c._get_xfer_logger = MagicMock(return_value=logger)
    c._sync_xfer_logger(device_id='serial:COM9')
    c._xfer_append_io('send', b'\x01', frame_id=1)
    logger.append_send.assert_called()
    c._xfer_append_eng(b'\x02')
    logger.append_eng.assert_called()
    c._xfer_append_can_assembled(b'\x03')
    logger.append_can_assembled.assert_called()

    # session cache miss
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.get_session_sync',
        lambda *_a, **_k: {'assemblerId': ASSEMBLER_PASSTHROUGH},
    )
    sess = c._get_session_cached('serial:COM9', 'serial')
    assert 'assemblerId' in sess

    # locked empty + empty payloads + demux routes + push error boom
    c._try_session_ingest_locked(b'', 'serial:COM9', 'serial')
    asm = MagicMock()
    asm.feed.return_value = []
    monkeypatch.setattr(
        'module_payload.assemblers.create_assembler',
        lambda _aid: asm,
    )
    c._assembler = None
    c._try_session_ingest_locked(b'\x01', 'serial:COM9', 'serial')

    demux = MagicMock()
    demux.drain.return_value = []
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.get_session_sync',
        lambda *_a, **_k: {'routes': [{'header': 'AA', 'assemblerId': 'passthrough'}]},
    )
    # bypass cache
    c._session_cache.clear()
    c._session_cache_mono.clear()
    with (
        patch('module_payload.demux.StreamDemux', return_value=demux),
        patch('module_payload.demux.routes_fingerprint', return_value='fp'),
    ):
        c._try_session_ingest_locked(b'\x01', 'serial:COM9', 'serial')

    # exception → push_pipeline_error also fails
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.get_session_sync',
        MagicMock(side_effect=RuntimeError('x')),
    )
    c._session_cache.clear()
    c._session_cache_mono.clear()
    with patch(
        'module_payload.collectors.base_collector.push_pipeline_error',
        side_effect=RuntimeError('pe'),
    ):
        c._try_session_ingest_locked(b'\x01', 'serial:COM9', 'serial')

    # store exceptions
    with patch(
        'module_payload.pipeline.write_assembled_sync',
        side_effect=RuntimeError('w'),
    ):
        c._store_assembled(
            'd',
            ASSEMBLER_PASSTHROUGH,
            AssembledPayload(data=b'\x01', meta={}),
        )
    c._redis.set.side_effect = RuntimeError('img')
    c._store_camera_image(
        'd',
        AssembledPayload(data=b'\x00' * 4, meta={'width': 2, 'height': 2, 'kind': 'image'}),
    )
    c._redis.set.side_effect = None

    # consume_control empty msg + stop break path in run
    c._running = True
    c._redis.lpop = MagicMock(side_effect=[json.dumps(None), json.dumps({'op': 'stop'})])
    c._flush_stream_io_to_redis = MagicMock()
    c._consume_control()
    assert c._running is False

    # push_io display_hex
    c._push_io('recv', b'\x01', display_hex=True, frame_id=1)

    # stream io exception
    with patch.object(c, '_ensure_stream_io', side_effect=RuntimeError('s')):
        c._push_stream_io('recv', b'\x01')

    # ack / clear exceptions
    c._redis.setex.side_effect = RuntimeError('ack')
    c._ack_stream_io('serial:COM9', 'rid')
    c._redis.setex.side_effect = None
    c._stream_io_bufs = {}
    c._redis.delete.side_effect = RuntimeError('del')
    c._clear_stream_io(req_id='r2')  # no device_id → else branch
    c._redis.delete.side_effect = None

    # run: break after control stops; outer KeyboardInterrupt
    class Coll(BaseCollector):
        def setup(self):
            return True

        def read_and_parse(self):
            return None

        def execute_command(self, command):
            return {'success': True}

        def teardown(self):
            return None

    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )
    coll = Coll('serial:COM9', {'loop_interval_s': 0.0})
    coll._write_status = MagicMock()
    coll._consume_control = MagicMock(side_effect=lambda: setattr(coll, '_running', False))
    coll._consume_commands = MagicMock()
    coll._heartbeat = MagicMock()
    coll.teardown = MagicMock()
    coll.run()

    coll2 = Coll('serial:COM9', {'loop_interval_s': 0.0})
    coll2._write_status = MagicMock()
    coll2._is_full_duplex = MagicMock(return_value=False)

    def boom_loop():
        raise KeyboardInterrupt()

    coll2._consume_control = boom_loop  # type: ignore
    coll2.teardown = MagicMock()
    coll2.run()


def test_process_manager_stop_success_and_wait_exception() -> None:
    import subprocess

    from module_payload.collectors.process_manager import CollectorProcessManager, ProcessEntry

    m = CollectorProcessManager.__new__(CollectorProcessManager)
    m._registry = {}
    m._lifecycle_lock = threading.RLock()
    m._shutting_down = False
    m._redis = None
    m._push_ctrl = MagicMock()

    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.return_value = 0  # first wait succeeds → line 371 return
    m._registry['ok'] = ProcessEntry('ok', 'serial', process=proc)
    m.stop('ok')

    proc2 = MagicMock()
    proc2.poll.return_value = None
    proc2.wait.side_effect = [
        subprocess.TimeoutExpired(cmd='x', timeout=0.1),
        RuntimeError('after-term'),  # lines 391-392
    ]
    m._registry['e'] = ProcessEntry('e', 'serial', process=proc2)
    m.stop('e')

    # lazy redis + clear status + stream notify
    fake_r = MagicMock()
    with patch(
        'module_payload.collectors.redis_sync.create_sync_redis',
        return_value=fake_r,
    ):
        assert m._get_redis() is fake_r
        assert m._get_redis() is fake_r  # cached
    m._clear_channel_status('can:0:0:0')
    fake_r.delete.assert_called()
    m.notify_flush_io_stream('can:0:0:0', 'rid1')
    m.notify_clear_io_stream('can:0:0:0', 'rid2')
    assert m._push_ctrl.call_count >= 2


def test_runner_unknown_type(monkeypatch) -> None:
    from module_payload.collectors.runner import run_collector

    monkeypatch.setattr('module_payload.collectors.runner._bootstrap_env', lambda: None)
    with pytest.raises(ValueError, match='未知采集类型'):
        run_collector('weird', 'x', {})


def test_serial_import_exception_branch() -> None:
    import sys

    from module_payload.collectors.serial_collector import SerialCollector

    saved = {
        k: sys.modules[k]
        for k in list(sys.modules)
        if k == 'serial' or k.startswith('serial.')
    }
    try:
        # Force ImportError / halted import even if pyserial was never loaded yet
        sys.modules['serial'] = None  # type: ignore[assignment]
        for k in list(saved):
            if k != 'serial':
                sys.modules[k] = None  # type: ignore[assignment]
        assert SerialCollector._is_port_lost_error(ValueError('x')) is False
    finally:
        for k in list(sys.modules):
            if k == 'serial' or k.startswith('serial.'):
                if k in saved:
                    sys.modules[k] = saved[k]
                else:
                    sys.modules.pop(k, None)


def test_runner_main_guard_via_runpy(monkeypatch) -> None:
    """Exercise runner ``main()``; ``__main__`` guard already has pragma: no cover."""
    import sys

    from module_payload.collectors import runner as runner_mod

    monkeypatch.setattr(
        sys,
        'argv',
        ['runner.py', 'net', 'udp:1:2', '{}'],
    )
    monkeypatch.setattr(runner_mod, 'run_collector', MagicMock())
    runner_mod.main()
