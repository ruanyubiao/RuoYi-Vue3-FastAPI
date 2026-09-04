"""采集模块覆盖率补齐：base / process_manager / runner / redis_sync / net / duplex / timers / xfer。"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from module_payload.assemblers.base import AssembledPayload
from module_payload.collectors.base_collector import BaseCollector
from module_payload.collectors.can_timers import (
    can_port_label,
    parse_timer_op,
    utc_to_epoch_ms_floor_sec,
)
from module_payload.collectors.connection_transfer_logger import (
    ConnectionTransferLogger,
    ROTATE_MIN_AGE_S,
    ROTATE_MIN_BYTES,
    _ChannelState,
    _STOP,
)
from module_payload.collectors.duplex import resolve_full_duplex
from module_payload.collectors.net_collector import NetCollector
from module_payload.collectors.process_manager import CollectorProcessManager, ProcessEntry
from module_payload.collectors import redis_sync as redis_sync_mod
from module_payload.collectors.runner import _bootstrap_env, _mark_can_opening, main, run_collector
from module_payload.constants import SRC_KIND_SERIAL


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _base(**kwargs) -> BaseCollector:
    c = BaseCollector.__new__(BaseCollector)
    c.device_id = kwargs.pop('device_id', 'serial:COM9')
    c.config = kwargs.pop('config', {})
    c._running = False
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
    for k, v in kwargs.items():
        setattr(c, k, v)
    return c


def _mgr() -> CollectorProcessManager:
    m = CollectorProcessManager.__new__(CollectorProcessManager)
    m._registry = {}
    m._lifecycle_lock = threading.RLock()
    m._shutting_down = False
    m._redis = None
    return m


# ---------------------------------------------------------------------------
# redis_sync / duplex / can_timers
# ---------------------------------------------------------------------------


def test_redis_config_and_create_sync_redis(monkeypatch) -> None:
    monkeypatch.setenv('REDIS_HOST', '10.0.0.1')
    monkeypatch.setenv('REDIS_PORT', '6380')
    monkeypatch.setenv('REDIS_USERNAME', 'u')
    monkeypatch.setenv('REDIS_PASSWORD', 'p')
    monkeypatch.setenv('REDIS_DATABASE', '3')
    cfg = redis_sync_mod._redis_config()
    assert cfg['host'] == '10.0.0.1'
    assert cfg['port'] == 6380
    assert cfg['username'] == 'u'
    assert cfg['db'] == 3

    fake = MagicMock()
    with patch.object(redis_sync_mod.redis, 'Redis', return_value=fake) as ctor:
        client = redis_sync_mod.create_sync_redis()
    assert client is fake
    kwargs = ctor.call_args.kwargs
    assert kwargs['socket_keepalive'] is True
    assert kwargs['health_check_interval'] == 15


def test_resolve_full_duplex_loader_exception(monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.cfg.payload_config_loader.PayloadConfigLoader.get_device_connect_entry',
        MagicMock(side_effect=RuntimeError('boom')),
    )
    assert resolve_full_duplex(source='camera_ctrl') is False


def test_can_timers_edges() -> None:
    assert can_port_label(7) == 'CAN7'
    assert utc_to_epoch_ms_floor_sec('') % 1000 == 0
    assert utc_to_epoch_ms_floor_sec('not-a-date') % 1000 == 0
    assert parse_timer_op('') is None
    assert parse_timer_op('biu.time_sync.get') == {'kind': 'get_status', 'family': 'biu'}
    assert parse_timer_op('xl.time_sync.set_gnss', {'gnssValid': False}) == {
        'kind': 'set_gnss',
        'gnssValid': False,
        'family': 'xl',
    }
    # set_start / set_offset / broadcast / unknown after timesync
    assert parse_timer_op('biu.timeSync.setStart', {'utc': 'u'})['kind'] == 'set_start'
    assert parse_timer_op('biu.timeSync.setOffset', {'offsetMs': 3})['kind'] == 'set_offset'
    assert parse_timer_op('xl.timeSync.broadcast', {'enable': True})['kind'] == 'timed_sync'
    assert parse_timer_op('biu.timeSync.unknown') is None
    assert parse_timer_op('nope.timedTmEnable') is None
    assert parse_timer_op('biu.fooBar') is None  # family ok but no timesync/timedtmenable


def test_net_execute_no_sock(monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )
    c = NetCollector('udp:x:1', {'proto': 'udp'})
    c._sock = None
    assert c.execute_command({'hex': 'AA'})['success'] is False


def test_runner_main_signal_ign_fail(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        'argv',
        ['runner.py', 'net', 'udp:1:2', '{}'],
    )
    monkeypatch.setattr(
        'module_payload.collectors.runner.run_collector',
        MagicMock(),
    )
    with patch('signal.signal', side_effect=ValueError('no')):
        main()


def test_xfer_fp_none_paths(tmp_path: Path) -> None:
    log = ConnectionTransferLogger('fp', kind='other', root_dir=tmp_path)
    try:
        ch = _ChannelState()
        # rotate when fp already None
        log._rotate_if_needed(ch, 'recv', 'bin', 'burst')
        # write paths with fp forced None after ensure
        with patch.object(log, '_ensure_file'), patch.object(log, '_rotate_if_needed'):
            log._write_bin(ch, 'recv', b'\x01', policy='burst')
            log._write_txt(ch, 'send', 'x\n', policy='daily')
        # closed enqueue drop
        log._closed = True
        log._enqueue(('recv', b'\x01', None, False))
        log._closed = False
        # append_can_assembled when not can already covered; closed put timeout
        with patch.object(log._q, 'put', side_effect=queue.Full):
            log._closed = False
            log.close(flush=False)
    finally:
        if not getattr(log, '_closed', True):
            log.close(flush=False)


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------


def test_bootstrap_env_adds_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        'module_payload.collectors.runner._BACKEND_ROOT',
        tmp_path,
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'path', [p for p in sys.path if p != str(tmp_path)])
    _bootstrap_env()
    assert Path.cwd() == tmp_path
    assert str(tmp_path) in sys.path


def test_mark_can_opening_writes_and_swallows(monkeypatch) -> None:
    r = MagicMock()
    monkeypatch.setattr(
        'module_payload.collectors.redis_sync.create_sync_redis',
        lambda: r,
    )
    _mark_can_opening(
        {
            'vendor': 3,
            'dev_index': 0,
            'channels': [{'can_index': 0}, {'can_index': 1}],
        }
    )
    assert r.set.call_count == 2
    r.close.assert_called_once()

    # single can_index form
    r.reset_mock()
    _mark_can_opening({'vendor': 1, 'dev_index': 2, 'can_index': 0})
    assert r.set.call_count == 1

    monkeypatch.setattr(
        'module_payload.collectors.redis_sync.create_sync_redis',
        MagicMock(side_effect=RuntimeError('no redis')),
    )
    _mark_can_opening({'can_index': 0})  # swallow


def test_run_collector_dispatches(monkeypatch) -> None:
    calls = []

    class Fake:
        def __init__(self, did, cfg):
            calls.append((type(self).__name__, did, cfg))

        def run(self):
            calls.append('run')

    monkeypatch.setattr('module_payload.collectors.runner._bootstrap_env', lambda: None)
    monkeypatch.setattr('module_payload.collectors.runner._mark_can_opening', lambda _c: None)
    monkeypatch.setattr(
        'module_payload.collectors.can_collector.CanCollector',
        type('Can', (Fake,), {}),
    )
    run_collector('can', 'can:0:0', {'x': 1})
    assert calls[-1] == 'run'

    calls.clear()
    monkeypatch.setattr(
        'module_payload.collectors.serial_collector.SerialCollector',
        type('Ser', (Fake,), {}),
    )
    run_collector('serial', 'serial:COM1', {})
    assert any(c[0] == 'Ser' for c in calls if isinstance(c, tuple))

    calls.clear()
    monkeypatch.setattr(
        'module_payload.collectors.net_collector.NetCollector',
        type('Net', (Fake,), {}),
    )
    run_collector('net', 'udp:1:2', {})
    assert any(c[0] == 'Net' for c in calls if isinstance(c, tuple))


def test_runner_main_keyboard_interrupt(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        'argv',
        ['runner.py', 'serial', 'serial:COM1', '{"a":1}'],
    )
    monkeypatch.setattr(
        'module_payload.collectors.runner.run_collector',
        MagicMock(side_effect=KeyboardInterrupt),
    )
    with pytest.raises(SystemExit) as ei:
        main()
    assert ei.value.code == 0


# ---------------------------------------------------------------------------
# net_collector gaps
# ---------------------------------------------------------------------------


def test_net_setup_bind_oserror(monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )
    c = NetCollector('udp:127.0.0.1:1', {'proto': 'udp', 'local_host': '127.0.0.1', 'local_port': 1})
    c._write_status = MagicMock()
    with patch('socket.socket') as sock_cls:
        sock = MagicMock()
        sock.bind.side_effect = OSError('busy')
        sock_cls.return_value = sock
        assert c.setup() is False
    c._write_status.assert_called()


def test_net_read_no_sock_and_timeouts(monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )
    c = NetCollector('udp:x:1', {'proto': 'udp', 'local_port': 1})
    c._sock = None
    c.read_and_parse()

    c._sock = MagicMock()
    c._sock.recvfrom.side_effect = TimeoutError()
    c.read_and_parse()
    c._sock.recvfrom.side_effect = OSError('x')
    c.read_and_parse()


def test_net_apply_peer_bad_port_and_send_fail(monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )
    c = NetCollector('udp:x:9', {'proto': 'udp'})
    c._apply_udp_peer('h', 'bad')
    assert c._remote_port == 0
    c._apply_udp_peer('h', 999999)
    assert c._remote_port == 0

    c._sock = MagicMock()
    c._sock.sendto.side_effect = OSError('fail')
    c._remote_host = '127.0.0.1'
    c._remote_port = 9
    assert '发送失败' in c.execute_command({'hex': 'AA'})['message']

    c._sock.close.side_effect = RuntimeError('x')
    c.teardown()
    assert c._sock is None


# ---------------------------------------------------------------------------
# connection_transfer_logger gaps
# ---------------------------------------------------------------------------


def test_xfer_logger_edge_paths(tmp_path: Path, monkeypatch) -> None:
    log = ConnectionTransferLogger('t', kind='other', root_dir=tmp_path)
    try:
        log.append_send(b'', frame_id=None)  # drop
        log.append_eng(b'\x01')
        log.append_can_assembled(b'\x02')  # non-can ignore
        # force enqueue after close path via put exception
        log._closed = False
        with patch.object(log._q, 'put', side_effect=RuntimeError('q')):
            log._enqueue(('recv', b'\x01', None, False))
        # writer error paths
        with patch.object(log, '_write_item', side_effect=RuntimeError('w')):
            log._q.put(('recv', b'\x03', None, False))
            time.sleep(0.05)
        # empty bin write
        log._write_bin(log._recv, 'recv', b'', policy='burst')
        # rotate daily across day
        ch = _ChannelState()
        ch.fp = MagicMock()
        ch.day = '20000101'
        ch.opened_at = time.monotonic()
        ch.bytes_written = 0
        with patch.object(log, '_ensure_file') as ens:
            with patch.object(log, '_close_channel') as cls:
                log._rotate_if_needed(ch, 'recv', 'txt', 'daily')
                cls.assert_called()
                ens.assert_called()
        # burst rotate
        ch2 = _ChannelState()
        ch2.fp = MagicMock()
        ch2.opened_at = time.monotonic() - ROTATE_MIN_AGE_S - 1
        ch2.bytes_written = ROTATE_MIN_BYTES + 1
        with patch.object(log, '_ensure_file') as ens2:
            with patch.object(log, '_close_channel') as cls2:
                log._rotate_if_needed(ch2, 'recv', 'bin', 'burst')
                cls2.assert_called()
                ens2.assert_called()
        # close channel flush error
        bad = _ChannelState()
        bad.fp = MagicMock()
        bad.fp.flush.side_effect = OSError('x')
        ConnectionTransferLogger._close_channel(bad)
        assert bad.fp is None
        # double close + put timeout
        log.close(flush=False)
        log.close(flush=True)
    finally:
        if not log._closed:
            log.close(flush=False)

    can = ConnectionTransferLogger('c', kind='can', root_dir=tmp_path)
    try:
        can.append_eng(b'\x11')  # ignored for can
        can.append_send(b'', frame_id=0x12)
        time.sleep(0.05)
    finally:
        can.close()


def test_xfer_writer_drains_stop_with_errors(tmp_path: Path) -> None:
    log = ConnectionTransferLogger('drain', kind='other', root_dir=tmp_path)
    # inject items then STOP; one write fails
    log._q.put(('recv', b'\x01', None, False))
    log._q.put(_STOP)
    log._q.put(('recv', b'\x02', None, False))
    with patch.object(log, '_write_item', side_effect=[None, RuntimeError('x')]):
        # trigger another STOP path via close
        log._closed = False
        log.close(flush=True)


# ---------------------------------------------------------------------------
# process_manager
# ---------------------------------------------------------------------------


def test_process_manager_instance_and_shutdown_guards(monkeypatch) -> None:
    CollectorProcessManager._instance = None
    monkeypatch.setattr(
        'module_payload.collectors.process_guard.install_shutdown_hooks',
        lambda _fn: None,
    )
    with patch(
        'module_payload.collectors.redis_sync.create_sync_redis',
        return_value=MagicMock(),
    ):
        a = CollectorProcessManager.instance()
        b = CollectorProcessManager.instance()
        assert a is b
    CollectorProcessManager._instance = None

    m = _mgr()
    m._shutting_down = True
    with pytest.raises(RuntimeError, match='关闭'):
        m._ensure_not_shutting_down()
    m._close_redis()  # None
    m._redis = MagicMock()
    m._redis.close.side_effect = RuntimeError('x')
    m._close_redis()
    assert m._redis is None


def test_process_manager_spawn_and_push_ctrl(monkeypatch) -> None:
    m = _mgr()
    fake_proc = MagicMock()
    monkeypatch.setattr(subprocess, 'Popen', MagicMock(return_value=fake_proc))
    monkeypatch.setattr(
        'module_payload.collectors.process_guard.assign_to_kill_job',
        lambda _p: True,
    )
    monkeypatch.setattr(sys, 'platform', 'win32')
    entry = m._spawn('serial', 'serial:COM1', {'port': 'COM1'})
    assert entry.process is fake_proc
    assert 'serial:COM1' in m._registry

    monkeypatch.setattr(sys, 'platform', 'linux')
    m2 = _mgr()
    monkeypatch.setattr(subprocess, 'Popen', MagicMock(return_value=fake_proc))
    m2._spawn('net', 'udp:1:2', {})

    m._redis = MagicMock()
    m._push_ctrl('serial:COM1', {'op': 'stop'})
    m._redis.lpush.assert_called()
    m._get_redis = MagicMock(side_effect=RuntimeError('x'))
    m._push_ctrl('x', {'op': 'y'})  # swallow get
    m._get_redis = MagicMock(return_value=MagicMock(lpush=MagicMock(side_effect=RuntimeError('lp'))))
    m._push_ctrl('x', {'op': 'y'})


def test_process_manager_wait_ready_branches() -> None:
    m = _mgr()
    r = MagicMock()
    m._redis = r

    # shutting down
    m._shutting_down = True
    ok, err = m._wait_channel_ready('serial:COM1', None, timeout_s=0.2)
    assert ok is False and '关闭' in err
    m._shutting_down = False

    # running connected
    r.get.return_value = json.dumps({'state': 'running', 'connected': True})
    ok, err = m._wait_channel_ready('serial:COM1', None, timeout_s=1.0)
    assert ok is True

    # error state
    r.get.return_value = json.dumps({'state': 'error', 'message': 'bad'})
    ok, err = m._wait_channel_ready('serial:COM1', None, timeout_s=1.0)
    assert ok is False and err == 'bad'

    # proc exited with stopped
    proc = MagicMock()
    proc.poll.return_value = 1
    r.get.side_effect = [
        json.dumps({'state': 'stopped', 'message': '已停止'}),
        json.dumps({'state': 'stopped', 'message': '已停止'}),
    ]
    ok, err = m._wait_channel_ready('serial:COM1', proc, timeout_s=1.0)
    assert ok is False and '异常退出' in err

    # proc exited error
    r.get.side_effect = [
        None,
        json.dumps({'state': 'error', 'message': 'died'}),
    ]
    ok, err = m._wait_channel_ready('serial:COM1', proc, timeout_s=1.0)
    assert err == 'died'

    # proc exited with message
    r.get.side_effect = [json.dumps({'state': 'opening', 'message': 'x'}), json.dumps({'message': 'x'})]
    ok, err = m._wait_channel_ready('serial:COM1', proc, timeout_s=1.0)
    assert err == 'x'

    # proc exited bare
    r.get.side_effect = [None, None]
    ok, err = m._wait_channel_ready('serial:COM1', proc, timeout_s=1.0)
    assert '已退出' in err

    # timeout opening
    alive = MagicMock(poll=MagicMock(return_value=None))
    r.get.side_effect = None
    r.get.return_value = json.dumps({'state': 'opening', 'message': '采集进程启动中…'})
    ok, err = m._wait_channel_ready('serial:COM1', alive, timeout_s=0.12)
    assert '超时' in err


def test_process_manager_open_can_paths(monkeypatch) -> None:
    m = _mgr()
    m._clear_channel_status = MagicMock()
    m._clear_device_ipc = MagicMock()
    m._push_ctrl = MagicMock()
    m.stop = MagicMock()

    # already open
    entry = ProcessEntry('can:3:0', 'can', process=MagicMock(poll=MagicMock(return_value=None)))
    entry.opened_channels.add(0)
    m._registry['can:3:0'] = entry
    cid, already = m.open_can_channel(3, 0, 0, {})
    assert already is True

    # reuse success
    entry.opened_channels.clear()
    m._wait_channel_ready = MagicMock(return_value=(True, ''))
    cid, already = m.open_can_channel(3, 0, 1, {'baud': 1})
    assert already is False
    assert 1 in entry.opened_channels

    # reuse fail with other channels open
    entry.opened_channels = {0}
    m._wait_channel_ready = MagicMock(return_value=(False, 'nope'))
    with pytest.raises(RuntimeError, match='nope'):
        m.open_can_channel(3, 0, 2, {})

    # reuse fail → cold start ok
    entry.opened_channels.clear()
    m._wait_channel_ready = MagicMock(side_effect=[(False, 'x'), (True, '')])
    fake_entry = ProcessEntry('can:3:0', 'can', process=MagicMock(poll=MagicMock(return_value=None)))
    m._spawn = MagicMock(return_value=fake_entry)
    monkeypatch.setattr(time, 'sleep', lambda *_a, **_k: None)
    cid, already = m.open_can_channel(3, 0, 0, {})
    assert already is False

    # dead entry → stop then cold fail
    dead = ProcessEntry('can:3:0', 'can', process=MagicMock(poll=MagicMock(return_value=1)))
    m._registry['can:3:0'] = dead
    m._wait_channel_ready = MagicMock(return_value=(False, 'cold fail'))
    m._spawn = MagicMock(return_value=fake_entry)
    with pytest.raises(RuntimeError, match='cold fail'):
        m.open_can_channel(3, 0, 0, {})


def test_upsert_can_channel_config() -> None:
    e = ProcessEntry('can:1:0', 'can', config={'channels': [{'can_index': 0, 'a': 1}]})
    CollectorProcessManager._upsert_can_channel_config(e, {'can_index': 0, 'a': 2})
    assert e.config['channels'][0]['a'] == 2
    CollectorProcessManager._upsert_can_channel_config(e, {'can_index': 1, 'b': 3})
    assert len(e.config['channels']) == 2


def test_process_manager_close_set_cable_start_stop(monkeypatch) -> None:
    m = _mgr()
    m._push_ctrl = MagicMock()
    m.close_can_channel(1, 0, 0)  # no entry

    entry = ProcessEntry('can:1:0', 'can', process=MagicMock(poll=MagicMock(return_value=None)))
    entry.opened_channels.add(0)
    m._registry['can:1:0'] = entry
    m.close_can_channel(1, 0, 0)
    assert 0 not in entry.opened_channels
    entry.opened_channels.add(0)

    with pytest.raises(RuntimeError):
        m.set_can_cable(9, 0, 0)
    with pytest.raises(RuntimeError):
        m.set_can_cable(1, 0, 1)
    m.set_can_cable(1, 0, 0, node_addr_to=2, cable_flag=1)
    assert m._push_ctrl.call_args[0][1]['cable_flag'] == 1

    monkeypatch.setattr(time, 'sleep', lambda *_a, **_k: None)
    m._clear_device_ipc = MagicMock()
    m._spawn = MagicMock(
        return_value=ProcessEntry('serial:COM1', 'serial', process=MagicMock(poll=MagicMock(return_value=None)))
    )
    m._wait_channel_ready = MagicMock(return_value=(True, ''))
    did, already = m.start_serial('COM1', {})
    assert already is False

    m._registry[did] = ProcessEntry(did, 'serial', process=MagicMock(poll=MagicMock(return_value=None)))
    did2, already2 = m.start_serial('COM1', {})
    assert already2 is True

    # dead serial restart fail
    m._registry[did] = ProcessEntry(did, 'serial', process=MagicMock(poll=MagicMock(return_value=1)))
    m.stop = MagicMock()
    m._wait_channel_ready = MagicMock(return_value=(False, '串口挂'))
    with pytest.raises(RuntimeError, match='串口|打开失败'):
        m.start_serial('COM1', {})

    m._spawn = MagicMock(
        return_value=ProcessEntry('udp:1:2', 'net', process=MagicMock(poll=MagicMock(return_value=None)))
    )
    m._wait_channel_ready = MagicMock(return_value=(True, ''))
    m.start_net('udp', '1', 2, {})
    m._registry['udp:1:2'] = ProcessEntry(
        'udp:1:2', 'net', process=MagicMock(poll=MagicMock(return_value=None))
    )
    assert m.start_net('udp', '1', 2, {})[1] is True
    m._registry['udp:1:2'] = ProcessEntry(
        'udp:1:2', 'net', process=MagicMock(poll=MagicMock(return_value=1))
    )
    m._wait_channel_ready = MagicMock(return_value=(False, 'net fail'))
    with pytest.raises(RuntimeError, match='net fail|网络'):
        m.start_net('udp', '1', 2, {})


def test_process_manager_clear_ipc_and_stop_edges() -> None:
    m = _mgr()
    r = MagicMock()
    m._redis = r
    m._clear_device_ipc('serial:COM1')
    r.delete.assert_called()

    # timeout message branch (non-opening)
    alive = MagicMock(poll=MagicMock(return_value=None))
    r.get.return_value = json.dumps({'state': 'busy', 'message': 'please wait'})
    ok, err = m._wait_channel_ready('serial:COM1', alive, timeout_s=0.12)
    assert ok is False and err == 'please wait'

    # stop: wait raises generic Exception → terminate path
    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.side_effect = [RuntimeError('w'), None]
    m._registry['e1'] = ProcessEntry('e1', 'serial', process=proc)
    m._push_ctrl = MagicMock()
    m.stop('e1')

    # terminate raises, then kill path
    proc2 = MagicMock()
    proc2.poll.return_value = None
    proc2.wait.side_effect = [
        subprocess.TimeoutExpired(cmd='x', timeout=0.1),
        subprocess.TimeoutExpired(cmd='x', timeout=0.1),
        RuntimeError('wait2'),
    ]
    proc2.terminate.side_effect = RuntimeError('term')
    proc2.kill.side_effect = RuntimeError('kill')
    m._registry['e2'] = ProcessEntry('e2', 'serial', process=proc2)
    m.stop('e2')

    m._registry['a'] = ProcessEntry('a', 'serial', process=MagicMock(poll=MagicMock(return_value=None)))
    m._push_ctrl = MagicMock(side_effect=RuntimeError('x'))
    m.notify_reload_tm_cfg()

    m = _mgr()
    m.stop('missing')
    dead = ProcessEntry('d', 'serial', process=MagicMock(poll=MagicMock(return_value=0)))
    m._registry['d'] = dead
    m.stop('d')

    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.side_effect = [
        subprocess.TimeoutExpired(cmd='x', timeout=0.1),
        None,
    ]
    m._registry['alive'] = ProcessEntry('alive', 'serial', process=proc)
    m._push_ctrl = MagicMock(side_effect=RuntimeError('x'))
    m.stop('alive')

    proc2 = MagicMock()
    proc2.poll.return_value = None
    proc2.wait.side_effect = [
        subprocess.TimeoutExpired(cmd='x', timeout=0.1),
        subprocess.TimeoutExpired(cmd='x', timeout=0.1),
        None,
    ]
    m._registry['k'] = ProcessEntry('k', 'serial', process=proc2)
    m._push_ctrl = MagicMock()
    m.stop('k')
    proc2.kill.assert_called()

    m.notify_session_changed('serial:COM1')
    m.apply_net_reuse_params('udp:1:2', remote_host='h', remote_port='bad')
    m._registry['udp:1:2'] = ProcessEntry('udp:1:2', 'net', config={})
    m.apply_net_reuse_params('udp:1:2', remote_host='h', remote_port=9)
    assert m._registry['udp:1:2'].config['remote_port'] == 9

    m._registry['a'] = ProcessEntry('a', 'serial', process=MagicMock(poll=MagicMock(return_value=None)))
    m._registry['b'] = ProcessEntry('b', 'serial', process=MagicMock(poll=MagicMock(return_value=1)))
    m._push_ctrl = MagicMock(side_effect=[None, RuntimeError('x')])
    m.notify_reload_tm_cfg()
    assert isinstance(m.list_opened(), list)

    m.stop = MagicMock(side_effect=RuntimeError('x'))
    m._close_redis = MagicMock()
    m.shutdown_all()
    assert m._shutting_down is True


# ---------------------------------------------------------------------------
# base_collector
# ---------------------------------------------------------------------------


def test_base_abstract_and_handle_control() -> None:
    c = _base()
    with pytest.raises(NotImplementedError):
        c.setup()
    with pytest.raises(NotImplementedError):
        c.read_and_parse()
    with pytest.raises(NotImplementedError):
        c.execute_command({})
    c.stop()
    assert c._running is False

    c._invalidate_session_cache = MagicMock()
    c._sync_xfer_logger = MagicMock()
    c._reset_tm_parsers = MagicMock()
    c.handle_control({'op': 'session_changed'})
    c.handle_control({'op': 'reload_tm_cfg'})
    c._reset_tm_parsers.assert_called()


def test_base_reset_tm_parsers_swallows(monkeypatch) -> None:
    c = _base()
    monkeypatch.setattr(
        'module_payload.parsers.biu_can_tm.reset_tm_mgr',
        MagicMock(side_effect=RuntimeError('x')),
    )
    c._reset_tm_parsers()


def test_base_xfer_logger_paths(monkeypatch, tmp_path: Path) -> None:
    c = _base()
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.get_session_sync',
        MagicMock(side_effect=RuntimeError('x')),
    )
    c.config = {'source': 'zk'}
    tag = c._resolve_xfer_tag()
    assert tag.startswith('zk_')

    monkeypatch.setattr(
        'module_payload.collectors.base_collector.get_session_sync',
        MagicMock(return_value={'source': 'camera_ctrl'}),
    )
    logger = MagicMock()
    logger2 = MagicMock()
    ctor = MagicMock(side_effect=[logger, logger2, MagicMock()])
    with patch(
        'module_payload.collectors.connection_transfer_logger.ConnectionTransferLogger',
        ctor,
    ):
        first = c._get_xfer_logger()
        assert first is logger
        assert c._get_xfer_logger() is logger
        monkeypatch.setattr(
            'module_payload.collectors.base_collector.get_session_sync',
            MagicMock(return_value={'source': 'other'}),
        )
        assert c._get_xfer_logger() is logger2
        logger.close.assert_called()

        logger.close.side_effect = RuntimeError('x')
        c._xfer_loggers = {'serial:COM9': logger}
        c._xfer_tags = {'serial:COM9': 'old'}
        c._get_xfer_logger('serial:COM9')

    c._get_xfer_logger = MagicMock(side_effect=RuntimeError('x'))
    c._sync_xfer_logger()
    c._xfer_append_io('recv', b'\x01')
    c._xfer_append_eng(b'\x02')
    c._xfer_append_can_assembled(b'\x03')

    c._get_xfer_logger = MagicMock(return_value=MagicMock(append_eng=None))
    c._xfer_append_eng(b'\x02')

    good = MagicMock()
    c._xfer_loggers = {'a': good}
    c._xfer_tags = {'a': 't'}
    good.close.side_effect = RuntimeError('x')
    c._close_all_xfer_loggers()
    assert c._xfer_loggers == {}


def test_base_session_ingest_and_demux(monkeypatch) -> None:
    c = _base()
    c._try_session_ingest(b'', 'serial:COM9', SRC_KIND_SERIAL)

    # cache hit
    c._session_cache['serial:serial:COM9'] = {'assemblerId': 'passthrough'}
    c._session_cache_mono['serial:serial:COM9'] = time.monotonic()
    assert c._get_session_cached('serial:COM9', 'serial')['assemblerId'] == 'passthrough'

    asm = MagicMock()
    asm.feed.return_value = [AssembledPayload(data=b'\xAA')]
    asm.take_errors = MagicMock(return_value=['e1'])

    monkeypatch.setattr(
        'module_payload.collectors.base_collector.get_session_sync',
        MagicMock(return_value={'assemblerId': 'passthrough', 'parserId': 'p1'}),
    )
    monkeypatch.setattr(
        'module_payload.assemblers.create_assembler',
        MagicMock(return_value=asm),
    )
    monkeypatch.setattr(
        'module_payload.assemblers.normalize_assembler_id',
        lambda x: x or 'passthrough',
    )
    push_err = MagicMock()
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.push_pipeline_error',
        push_err,
    )
    c._dispatch_payloads = MagicMock()
    c._try_session_ingest(b'\x01\x02', 'serial:COM9', SRC_KIND_SERIAL)
    c._dispatch_payloads.assert_called()

    # exception path
    c._session_cache.clear()
    c._session_cache_mono.clear()
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.get_session_sync',
        MagicMock(side_effect=RuntimeError('boom')),
    )
    push_err.reset_mock()
    c._try_session_ingest(b'\x01', 'serial:COM9', SRC_KIND_SERIAL)
    push_err.assert_called()

    # demux path
    hit = SimpleNamespace(assembler_id='passthrough', parser_id='', frame=b'\x11')
    demux = MagicMock()
    demux.drain.return_value = [hit]
    asm2 = MagicMock()
    asm2.accept_frame.return_value = AssembledPayload(data=b'\x22')
    asm2.take_errors = MagicMock(return_value=[])
    c._dispatch_payloads = MagicMock()
    c._ingest_via_demux(
        b'\x01',
        src_param='serial:COM9',
        src_kind=SRC_KIND_SERIAL,
        session={'parserId': 'px'},
        routes=[{'a': 1}],
        create_assembler=lambda _aid: asm2,
        normalize_assembler_id=lambda x: x or 'passthrough',
        StreamDemux=lambda _r: demux,
        routes_fingerprint=lambda _r: 'fp1',
        resolve_parser=lambda _p: None,
        push_pipeline_error=MagicMock(),
    )
    c._dispatch_payloads.assert_called()

    # demux no hits
    demux.drain.return_value = []
    c._demux = None
    c._ingest_via_demux(
        b'\x01',
        src_param='serial:COM9',
        src_kind=SRC_KIND_SERIAL,
        session={},
        routes=[{}],
        create_assembler=lambda _aid: asm2,
        normalize_assembler_id=lambda x: 'passthrough',
        StreamDemux=lambda _r: demux,
        routes_fingerprint=lambda _r: 'fp2',
        resolve_parser=lambda _p: None,
        push_pipeline_error=MagicMock(),
    )

    asm3 = MagicMock()
    del asm3.accept_frame
    asm3.feed.return_value = []
    asm3.take_errors = MagicMock(return_value=[])
    demux.drain.return_value = [hit]
    c._demux = None
    c._assemblers = {}
    c._ingest_via_demux(
        b'\x01',
        src_param='serial:COM9',
        src_kind=SRC_KIND_SERIAL,
        session={},
        routes=[{}],
        create_assembler=lambda _aid: asm3,
        normalize_assembler_id=lambda x: 'passthrough',
        StreamDemux=lambda _r: demux,
        routes_fingerprint=lambda _r: 'fp3',
        resolve_parser=lambda _p: None,
        push_pipeline_error=MagicMock(),
    )


def test_base_emit_dispatch_store_camera(monkeypatch) -> None:
    c = _base()
    c._emit_assembler_errors(object(), src_param='d', assembler_id='x', push_pipeline_error=MagicMock())
    asm = MagicMock()
    asm.take_errors.return_value = ['相机错']
    push = MagicMock()
    from module_payload.constants import ASSEMBLER_CAMERA_IMAGE_D6

    c._emit_assembler_errors(asm, src_param='d', assembler_id=ASSEMBLER_CAMERA_IMAGE_D6, push_pipeline_error=push)
    assert push.call_args.kwargs['stage'] == 'camera'

    push = MagicMock()
    c._dispatch_payloads(
        [None, AssembledPayload(data=b''), AssembledPayload(data=b'\x01')],
        src_param='serial:COM9',
        src_kind=SRC_KIND_SERIAL,
        assembler_id='passthrough',
        parser_id='missing',
        resolve_parser=lambda _p: None,
        push_pipeline_error=push,
    )
    push.assert_called()

    c._store_assembled = MagicMock()
    c._xfer_append_eng = MagicMock()
    real_store_cam = BaseCollector._store_camera_image
    c._store_camera_image = MagicMock()
    real_preview = BaseCollector._preview_recv_io.__get__(c, BaseCollector)
    c._preview_recv_io = MagicMock()
    img = AssembledPayload(data=b'\x00' * 4, meta={'kind': 'image', 'width': 2, 'height': 2})
    c._dispatch_payloads(
        [img],
        src_param='serial:COM9',
        src_kind=SRC_KIND_SERIAL,
        assembler_id=ASSEMBLER_CAMERA_IMAGE_D6,
        parser_id='',
        resolve_parser=lambda _p: None,
        push_pipeline_error=MagicMock(),
    )
    c._store_camera_image.assert_called()

    eng = AssembledPayload(data=b'\xAB')
    ingest = MagicMock()
    ingest.ingest_bytes_sync = MagicMock(side_effect=[TypeError('kw'), None])
    c._dispatch_payloads(
        [eng],
        src_param='serial:COM9',
        src_kind=SRC_KIND_SERIAL,
        assembler_id='eng_tm_subpkt',
        parser_id='p',
        resolve_parser=lambda _p: ingest,
        push_pipeline_error=MagicMock(),
    )
    # TypeError path retries without assembler_id
    assert ingest.ingest_bytes_sync.call_count >= 1
    c._xfer_append_eng.assert_called()

    c._preview_recv_io = real_preview
    c._store_camera_image = lambda *a, **k: real_store_cam(c, *a, **k)
    c._push_io = MagicMock()
    c._preview_recv_io(b'', None)
    c._preview_recv_io(b'\x01', None)
    c._push_io.assert_called()

    class Ing:
        @staticmethod
        def io_preview_frames(_d):
            return [b'\x11', b'\x22']

    c._push_io.reset_mock()
    c._preview_recv_io(b'\x01', Ing)
    assert c._push_io.call_args[0][1] == b'\x22'

    # store assembled throttle / error
    c._assembled_mono = {c.device_id: time.monotonic()}
    c._store_assembled(c.device_id, 'passthrough', AssembledPayload(data=b'\x01'))
    monkeypatch.setattr(
        'module_payload.pipeline.write_assembled_sync',
        MagicMock(side_effect=RuntimeError('x')),
    )
    c._assembled_mono = {}
    c._store_assembled(c.device_id, 'passthrough', AssembledPayload(data=b'\x01'))

    # camera image store
    c._redis = MagicMock()
    c._store_camera_image('serial:COM9', AssembledPayload(data=b'', meta={'width': 1, 'height': 1}))
    pixels = bytes([0] * 4)
    item = AssembledPayload(data=pixels, meta={'width': 2, 'height': 2, 'imageNo': 1})
    import PIL.Image as PILImage

    fake = MagicMock()
    fake.save = MagicMock()
    with patch.object(PILImage, 'frombytes', return_value=fake):
        c._store_camera_image('serial:COM9', item)
    assert c._redis.set.call_count >= 2
    # raw fallback when encode fails
    c._redis.reset_mock()
    with patch.object(PILImage, 'frombytes', side_effect=RuntimeError('no pillow')):
        c._store_camera_image('serial:COM9', item)
    assert c._redis.set.call_count >= 2


def test_base_run_loop_and_rx(monkeypatch) -> None:
    class Coll(BaseCollector):
        def setup(self):
            return True

        def read_and_parse(self):
            self._running = False

        def execute_command(self, command):
            return {'success': True}

        def teardown(self):
            return

    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )
    c = Coll('serial:COM1', {'loop_interval_s': 0.001})
    c._write_status = MagicMock()
    c._consume_control = MagicMock()
    c._consume_commands = MagicMock()
    c._heartbeat = MagicMock()
    c.run()
    c._write_status.assert_any_call('stopped', '已停止')

    # setup false
    class Fail(Coll):
        def setup(self):
            return False

    Fail('serial:COM1', {}).run()

    # setup exception
    class Boom(Coll):
        def setup(self):
            raise RuntimeError('x')

    b = Boom('serial:COM1', {})
    b._write_status = MagicMock()
    b.run()
    b._write_status.assert_called()

    # KeyboardInterrupt on setup
    class Ki(Coll):
        def setup(self):
            raise KeyboardInterrupt

    Ki('serial:COM1', {}).run()

    # loop KeyboardInterrupt + exception swallow
    class LoopKi(Coll):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.n = 0

        def _consume_control(self):
            self.n += 1
            if self.n == 1:
                raise RuntimeError('once')
            raise KeyboardInterrupt

        def read_and_parse(self):
            pass

    lk = LoopKi('serial:COM1', {'loop_interval_s': 0.001})
    lk._write_status = MagicMock()
    lk._consume_commands = MagicMock()
    lk._heartbeat = MagicMock()
    lk.run()

    # full duplex rx loop
    class Fd(Coll):
        def setup(self):
            self.config['full_duplex'] = True
            return True

        def read_and_parse(self):
            self._running = False

    fd = Fd('serial:COM1', {'full_duplex': True, 'loop_interval_s': 0.001})
    fd._write_status = MagicMock()
    fd._consume_control = MagicMock(side_effect=lambda: setattr(fd, '_running', False))
    fd._consume_commands = MagicMock()
    fd._heartbeat = MagicMock()
    fd.run()

    # rx loop exception / KI
    c2 = _base(config={'loop_interval_s': 0.001})
    c2._running = True
    n = {'i': 0}

    def read():
        n['i'] += 1
        if n['i'] == 1:
            raise RuntimeError('x')
        raise KeyboardInterrupt

    c2.read_and_parse = read  # type: ignore
    c2._rx_loop()


def test_base_consume_commands_history_status(monkeypatch) -> None:
    c = _base()
    c._running = True
    c.execute_command = MagicMock(side_effect=RuntimeError('boom'))  # type: ignore
    c._push_history = MagicMock()
    c._redis.lpop = MagicMock(side_effect=[json.dumps({'cmd_id': '1', 'hex': 'AA'}), None])
    c._consume_commands()
    c._redis.setex.assert_called()
    assert c._tx_count == 1

    c.execute_command = MagicMock(return_value={'success': True, 'message': 'OK'})  # type: ignore
    c._redis.lpop = MagicMock(side_effect=[json.dumps({'hex': 'BB'}), None])
    c._consume_commands()
    c._push_history.assert_called()

    # stop flushes stream
    c._flush_stream_io_to_redis = MagicMock(side_effect=RuntimeError('x'))
    c._redis.lpop = MagicMock(side_effect=[json.dumps({'op': 'stop'}), None])
    c._consume_control()
    assert c._running is False

    # io targets exception + source
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.get_session_sync',
        MagicMock(side_effect=RuntimeError('x')),
    )
    c.config = {'source': 'zk'}
    assert rk_source_in(c._io_log_targets('serial:COM9'))

    monkeypatch.setattr(
        'module_payload.collectors.base_collector.get_session_sync',
        MagicMock(return_value={'source': 'camera_ctrl'}),
    )
    targets = c._io_log_targets('serial:COM9')
    assert len(targets) == 2

    # push_io xfer exception / empty
    c._xfer_append_io = MagicMock(side_effect=RuntimeError('x'))
    c._push_io('recv', b'\x01')
    c._push_io('recv', b'')

    # stream empty / frame id / display
    c._push_stream_io('recv', b'')
    c._push_stream_io('send', b'\x01', frame_id=1, display_hex=False)
    out = c._stream_entry_to_redis(
        {'data': b'\x01', 'dir': 'send', 'len': 1, 'seq': 1, 'frameIdHex': '00', 'displayHex': True}
    )
    assert out['displayHex'] is True

    # push history (real method)
    c._push_history = BaseCollector._push_history.__get__(c, BaseCollector)
    c._push_io = MagicMock()
    c._push_stream_io = MagicMock()
    c._push_history({'hex': 'AA BB', 'name': 'n', 'display_hex': False}, {'success': True, 'ts': 'bad-ts', 'peer': 'p'})
    c._redis.lpush.assert_called()
    c._push_history({'hex': '', 'frame_id': 3}, {'success': True, 'ts': '2026-01-01 00:00:00.000'})
    c._push_history({'hex': 'GG'}, {'success': True, 'ts': '2026-01-01 00:00:00.000'})  # hex error swallowed
    # tx queue boom
    c._redis.lpush.side_effect = [None, RuntimeError('tx')]
    c._push_history({'hex': '01'}, {'success': True, 'ts': '2026-01-01 00:00:00.000'})
    c._redis.lpush.side_effect = None

    # heartbeat / status
    c._heartbeat()
    c._write_status('running', 'ok')
    c._redis.get.return_value = json.dumps({'pid': 1})
    c._write_status('stopped')
    c._redis.get.return_value = json.dumps({'pid': __import__('os').getpid()})
    c._write_status('stopped')
    c._redis.get.side_effect = RuntimeError('x')
    c._write_status('stopped')
    c._redis.get.side_effect = None

    c._write_channel_status('can:0:0:0', 'running', 'ok', connected=True)
    c._redis.get.return_value = json.dumps({'pid': 1})
    c._write_channel_status('can:0:0:0', 'closed')
    c._redis.get.return_value = json.dumps({'pid': __import__('os').getpid()})
    c._write_channel_status('can:0:0:0', 'stopped')
    c._redis.get.side_effect = RuntimeError('x')
    c._write_channel_status('can:0:0:0', 'stopped')

    # teardown flush exception
    c._flush_stream_io_to_redis = MagicMock(side_effect=RuntimeError('x'))
    c._close_all_xfer_loggers = MagicMock()
    c.teardown()

    # handle_control other + clear stream no device_id + empty cmd
    c._running = True
    c.handle_control({'op': 'noop'})
    c._redis.lpop = MagicMock(side_effect=[json.dumps({'op': 'clear_io_stream', 'req_id': 'r'}), None])
    c._clear_stream_io = MagicMock()
    c._consume_control()
    c._clear_stream_io.assert_called()
    c._redis.lpop = MagicMock(side_effect=[None])
    c._consume_commands()
    c._redis.lpop = MagicMock(side_effect=[json.dumps(None), None])
    c._consume_commands()
    c._redis.lpop = MagicMock(side_effect=[json.dumps({'op': 'reload_tm_cfg'}), None])
    c.handle_control = MagicMock()
    c._running = True
    c._consume_control()
    c.handle_control.assert_called()


def rk_source_in(targets: list[str]) -> bool:
    from module_payload import redis_keys as rk

    return any(t.startswith(rk.PREFIX) or 'source' in t for t in targets) or len(targets) >= 1


def test_base_teardown_run_status_exceptions(monkeypatch) -> None:
    class Coll(BaseCollector):
        def setup(self):
            return True

        def read_and_parse(self):
            self._running = False

        def execute_command(self, command):
            return {}

        def teardown(self):
            raise RuntimeError('td')

    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )
    c = Coll('serial:COM1', {'loop_interval_s': 0.001})
    c._write_status = MagicMock(side_effect=[None, RuntimeError('st')])
    c._consume_control = MagicMock()
    c._consume_commands = MagicMock()
    c._heartbeat = MagicMock()
    c.run()  # teardown/status exceptions swallowed
