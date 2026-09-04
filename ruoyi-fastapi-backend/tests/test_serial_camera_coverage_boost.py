"""serial_collector 与 camera_image 插件覆盖率补齐。"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from module_payload.assemblers.base import AssembledPayload
from module_payload.collectors.plugins.base import FilterResult, SerialPluginContext, TickResult
from module_payload.collectors.plugins.camera_image import (
    FAIL_SLEEP_S,
    FRAME_FAIL_RETRY,
    CameraImageSerialPlugin,
)
from module_payload.collectors.serial_collector import (
    BACKLOG_BYTES,
    MAX_WAITING,
    SerialCollector,
    rx_waiting_limit_bytes,
)
from module_payload.constants import ASSEMBLER_CAMERA_IMAGE_D6_V17


def _serial(**kwargs) -> SerialCollector:
    coll = SerialCollector.__new__(SerialCollector)
    coll.device_id = 'serial:COM4'
    coll.config = kwargs.pop('config', {'port': 'COM4', 'baudrate': 2_000_000})
    coll._pipeline_lock = __import__('threading').RLock()
    coll._assembler = None
    coll._assemblers = {}
    coll._demux = None
    coll._plugin = None
    coll._plugin_id = None
    coll._ser = MagicMock()
    coll._running = True
    coll._redis = MagicMock()
    coll._cached_source = None
    coll._last_port_check = 0.0
    coll._max_waiting = MAX_WAITING
    coll._rx_count = 0
    coll._xfer_loggers = {}
    coll._xfer_tags = {}
    coll._session_cache = {}
    coll._session_cache_mono = {}
    for k, v in kwargs.items():
        setattr(coll, k, v)
    return coll


def _ctx(**kwargs) -> SerialPluginContext:
    redis = kwargs.get('redis')
    if redis is None:
        redis = MagicMock()
        redis.get.return_value = None
    return SerialPluginContext(
        device_id=kwargs.get('device_id', 'serial:COM4'),
        redis=redis,
        config=kwargs.get('config', {}),
        is_running=kwargs.get('is_running', lambda: True),
        read_serial=kwargs.get('read_serial', lambda n: b''),
        write_serial=kwargs.get('write_serial', lambda data: None),
        in_waiting=kwargs.get('in_waiting', lambda: 0),
        reset_input_buffer=kwargs.get('reset_input_buffer', lambda: None),
        push_io=kwargs.get('push_io', lambda *a, **k: None),
        write_status=kwargs.get('write_status', lambda *a, **k: None),
        poll_control=kwargs.get('poll_control', lambda: None),
    )


# ---- serial_collector ----


def test_rx_waiting_limit_zero_inputs() -> None:
    assert rx_waiting_limit_bytes(0) == 0
    assert rx_waiting_limit_bytes(100, seconds=0) == 0


def test_port_name_and_lost_errors() -> None:
    c = _serial(config={}, device_id='serial:COM7')
    assert c._port_name() == 'COM7'
    assert SerialCollector._is_port_lost_error(OSError('x')) is True
    assert SerialCollector._is_port_lost_error(PermissionError()) is True
    assert SerialCollector._is_port_lost_error(TimeoutError()) is True

    class Serialish(Exception):
        pass

    assert SerialCollector._is_port_lost_error(Serialish()) is True
    assert SerialCollector._is_port_lost_error(ValueError('x')) is False

    with patch.dict('sys.modules', {'serial': MagicMock()}):
        import serial as serial_mod

        class SE(Exception):
            pass

        serial_mod.SerialException = SE
        assert SerialCollector._is_port_lost_error(SE('gone')) is True


def test_fatal_disconnect_and_port_present(monkeypatch) -> None:
    c = _serial()
    c._write_status = MagicMock(side_effect=RuntimeError('x'))
    c._ser.close.side_effect = RuntimeError('c')
    c._fatal_disconnect(RuntimeError(''))
    assert c._running is False
    assert c._ser is None

    c = _serial()
    c._write_status = MagicMock()
    c._fatal_disconnect('拔掉了')
    c._write_status.assert_called()

    c = _serial()
    c._last_port_check = time.monotonic()
    assert c._port_still_present() is True

    c._last_port_check = 0.0
    c.config = {'port': ''}
    c.device_id = 'serial:'
    assert c._port_still_present() is True

    c = _serial()
    c._last_port_check = 0.0
    monkeypatch.setattr(
        'serial.tools.list_ports.comports',
        MagicMock(side_effect=RuntimeError('x')),
    )
    assert c._port_still_present() is True

    c = _serial()
    c._last_port_check = 0.0
    c._fatal_disconnect = MagicMock()
    monkeypatch.setattr(
        'serial.tools.list_ports.comports',
        MagicMock(return_value=[SimpleNamespace(device='COM9')]),
    )
    assert c._port_still_present() is False
    c._fatal_disconnect.assert_called()

    c = _serial()
    c._last_port_check = 0.0
    monkeypatch.setattr(
        'serial.tools.list_ports.comports',
        MagicMock(return_value=[SimpleNamespace(device='COM4')]),
    )
    assert c._port_still_present() is True


def test_setup_open_fail_and_buffer(monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )
    c = SerialCollector('serial:COM4', {'port': 'COM4', 'source': 'home'})
    c._write_status = MagicMock()
    with patch('serial.Serial', side_effect=OSError('busy')):
        assert c.setup() is False

    ser = MagicMock()
    ser.set_buffer_size.side_effect = RuntimeError('no')
    with (
        patch('serial.Serial', return_value=ser),
        patch.object(SerialCollector, '_sync_plugin', return_value=None),
    ):
        assert c.setup() is True


def test_serial_io_helpers() -> None:
    c = _serial(_ser=None)
    assert c._read_serial(1) == b''
    assert c._in_waiting() == 0
    c._write_serial(b'\x01')  # no ser

    c = _serial()
    c._ser.read.return_value = b'\xAA'
    assert c._read_serial(1) == b'\xAA'
    c._ser.read.side_effect = OSError('x')
    c._fatal_disconnect = MagicMock()
    assert c._read_serial(1) == b''
    c._fatal_disconnect.assert_called()

    c = _serial()
    c._write_serial(b'')
    c._ser.write.side_effect = OSError('x')
    c._fatal_disconnect = MagicMock()
    with pytest.raises(OSError):
        c._write_serial(b'\x01')
    c._fatal_disconnect.assert_called()

    c = _serial()
    c._ser.write.side_effect = ValueError('y')
    with pytest.raises(ValueError):
        c._write_serial(b'\x01')

    c = _serial()
    c._ser.in_waiting = 5
    assert c._in_waiting() == 5

    class BoomSer:
        @property
        def in_waiting(self):
            raise OSError('x')

        def reset_input_buffer(self):
            raise OSError('x')

    c = _serial()
    c._ser = BoomSer()
    c._fatal_disconnect = MagicMock()
    assert c._in_waiting() == 0
    c._fatal_disconnect.assert_called()

    c = _serial()
    c._ser = BoomSer()
    c._fatal_disconnect = MagicMock()
    c._reset_input_buffer()
    c._fatal_disconnect.assert_called()
    c._ser = None
    c._reset_input_buffer()


def test_sync_plugin_and_handle_control(monkeypatch) -> None:
    c = _serial()
    c._read_session_source = MagicMock(return_value='camera_image')  # type: ignore
    plugin = MagicMock()
    plugin.on_session_refresh = MagicMock(side_effect=RuntimeError('x'))
    monkeypatch.setattr(
        'module_payload.collectors.plugins.registry.resolve_plugin_id_for_source',
        lambda s: 'camera_image' if s else None,
    )
    monkeypatch.setattr(
        'module_payload.collectors.plugins.registry.create_serial_plugin',
        lambda _id: plugin,
    )
    c._plugin_ctx = MagicMock(return_value=_ctx())  # type: ignore
    c._sync_plugin(source='camera_image', force_session=True)
    assert c._plugin is plugin

    # same id refresh
    c._sync_plugin(source='camera_image', force_session=True)
    plugin.on_session_refresh.assert_called()

    # detach old + none want
    plugin.on_detach.side_effect = RuntimeError('d')
    monkeypatch.setattr(
        'module_payload.collectors.plugins.registry.resolve_plugin_id_for_source',
        lambda s: None,
    )
    c._sync_plugin(source='home', force_session=True)
    assert c._plugin is None

    # create returns None
    monkeypatch.setattr(
        'module_payload.collectors.plugins.registry.resolve_plugin_id_for_source',
        lambda s: 'camera_image',
    )
    monkeypatch.setattr(
        'module_payload.collectors.plugins.registry.create_serial_plugin',
        lambda _id: None,
    )
    c._sync_plugin(source='camera_image', force_session=True)

    # cached source path
    c._cached_source = 'zk'
    monkeypatch.setattr(
        'module_payload.collectors.plugins.registry.resolve_plugin_id_for_source',
        lambda s: None,
    )
    c._sync_plugin(force_session=False)

    c._invalidate_session_cache = MagicMock()
    c._sync_plugin = MagicMock()
    c._sync_xfer_logger = MagicMock()
    c._reset_tm_parsers = MagicMock()
    c.handle_control({'op': 'session_changed'})
    c.handle_control({'op': 'reload_tm_cfg'})
    c._plugin = MagicMock(handle_control=MagicMock(return_value=True))
    c.handle_control({'op': 'other'})


def test_read_and_parse_filter_and_backlog() -> None:
    class Plug:
        def tick(self, ctx):
            return TickResult(owns_loop=False)

        def filter_rx(self, ctx, data):
            return FilterResult(passthrough=b'', consume=True)

    chunks = [b'\x01\x02', b'\x03']
    waits = [BACKLOG_BYTES, BACKLOG_BYTES, 0]

    c = _serial(
        _plugin=Plug(),
        _plugin_ctx=lambda: _ctx(),  # type: ignore
        _port_still_present=lambda: True,  # type: ignore
        _sync_plugin=lambda force_session=False: None,  # type: ignore
        _in_waiting=lambda: waits.pop(0) if waits else 0,  # type: ignore
        _read_serial=MagicMock(side_effect=lambda n: chunks.pop(0) if chunks else b''),  # type: ignore
        _xfer_append_io=MagicMock(),  # type: ignore
        _push_stream_io=MagicMock(),  # type: ignore
        _try_session_ingest=MagicMock(),  # type: ignore
    )
    c.read_and_parse()
    c._try_session_ingest.assert_not_called()

    class PassPlug:
        def tick(self, ctx):
            return TickResult(owns_loop=False)

        def filter_rx(self, ctx, data):
            return FilterResult(passthrough=b'\xEE', consume=False)

    c2 = _serial(
        _plugin=PassPlug(),
        _plugin_ctx=lambda: _ctx(),  # type: ignore
        _port_still_present=lambda: True,  # type: ignore
        _sync_plugin=lambda force_session=False: None,  # type: ignore
        _in_waiting=lambda: 10,  # type: ignore
        _read_serial=MagicMock(side_effect=[b'\x01', b'']),  # type: ignore
        _xfer_append_io=MagicMock(),  # type: ignore
        _push_stream_io=MagicMock(),  # type: ignore
        _try_session_ingest=MagicMock(),  # type: ignore
    )
    c2.read_and_parse()
    c2._try_session_ingest.assert_called()

    c3 = _serial(
        _port_still_present=lambda: True,  # type: ignore
        _sync_plugin=lambda force_session=False: None,  # type: ignore
        _in_waiting=MagicMock(side_effect=OSError('lost')),  # type: ignore
        _is_port_lost_error=lambda e: True,  # type: ignore
        _fatal_disconnect=MagicMock(),  # type: ignore
    )
    c3.read_and_parse()
    c3._fatal_disconnect.assert_called()


def test_execute_and_teardown() -> None:
    c = _serial(_ser=None)
    assert c.execute_command({'hex': 'AA'})['success'] is False

    c = _serial()
    c._write_serial = MagicMock()  # type: ignore
    assert c.execute_command({'hex': 'AA'})['success'] is True

    c._write_serial = MagicMock(side_effect=OSError('lost'))  # type: ignore
    c._fatal_disconnect = MagicMock()  # type: ignore
    c._is_port_lost_error = lambda e: True  # type: ignore
    out = c.execute_command({'hex': 'AA'})
    assert out['success'] is False and '断开' in out['message']

    c._write_serial = MagicMock(side_effect=ValueError('bad'))  # type: ignore
    c._is_port_lost_error = lambda e: False  # type: ignore
    assert 'bad' in c.execute_command({'hex': 'AA'})['message']

    c = _serial()
    c._plugin = MagicMock()
    c._plugin.on_detach.side_effect = RuntimeError('x')
    c._ser.close.side_effect = RuntimeError('c')
    with patch.object(SerialCollector.__mro__[1], 'teardown', return_value=None):
        c.teardown()
    assert c._ser is None


# ---- camera_image ----


def test_camera_merge_resolve_wh_and_tick() -> None:
    p = CameraImageSerialPlugin()
    ctx = _ctx()
    ctx.redis.get.side_effect = RuntimeError('x')
    # get_session_sync may not use redis.get — patch it
    with patch(
        'module_payload.collectors.plugins.camera_image.get_session_sync',
        side_effect=RuntimeError('x'),
    ):
        cfg = p._merge_session_cfg(ctx)
    assert isinstance(cfg, dict)

    assert CameraImageSerialPlugin._resolve_wh('bad×') == (400, 400)
    assert CameraImageSerialPlugin._resolve_wh('××') == (400, 400)
    assert CameraImageSerialPlugin._resolve_wh('notint') == (400, 400)
    assert CameraImageSerialPlugin._resolve_wh('80×80')[0] == 80

    p._need_clear = True
    p._enabled = False
    p._clear_image_cache = MagicMock()
    status = MagicMock()
    ctx = _ctx(write_status=status)
    assert p.tick(ctx).owns_loop is False
    p._clear_image_cache.assert_called()
    status.assert_called()

    p._enabled = True
    p._acquire_image_once = MagicMock()
    assert p.tick(ctx).owns_loop is True


def test_camera_clear_poll_flush_recv() -> None:
    p = CameraImageSerialPlugin()
    reset = MagicMock(side_effect=RuntimeError('x'))
    redis = MagicMock()
    redis.delete.side_effect = RuntimeError('d')
    CameraImageSerialPlugin._clear_image_cache(
        _ctx(reset_input_buffer=reset, redis=redis)
    )

    p._last_ctrl_poll = time.monotonic()
    poll = MagicMock()
    p._maybe_poll_control(_ctx(poll_control=poll))
    poll.assert_not_called()
    p._last_ctrl_poll = 0.0
    p._maybe_poll_control(_ctx(poll_control=poll))
    poll.assert_called()

    p._pending_io = []
    p._flush_pending_io(_ctx())
    p._pending_io = [('recv', b'\x01', 't')]
    push = MagicMock(side_effect=[TypeError('sig'), None])
    p._flush_pending_io(_ctx(push_io=push))
    push = MagicMock(side_effect=RuntimeError('x'))
    p._pending_io = [('recv', b'\x01', 't')]
    p._flush_pending_io(_ctx(push_io=push))

    # timeout recv
    p._enabled = True
    assert p._recv_response(_ctx(read_serial=lambda n: b''), timeout_s=0.01) is None

    # disabled mid-read
    p._enabled = False
    assert p._recv_response(_ctx(is_running=lambda: True), timeout_s=0.05) is None


def test_camera_pull_one_frame_paths(monkeypatch) -> None:
    p = CameraImageSerialPlugin()
    p._enabled = True
    ctx = _ctx(is_running=lambda: False)
    assert p._pull_one_frame(ctx, 0x80, 0, 1) is None

    p._enabled = True
    ctx = _ctx()
    p._recv_response = MagicMock(return_value=None)  # type: ignore
    monkeypatch.setattr(
        'module_payload.collectors.plugins.camera_image.build_request_frame',
        lambda *a, **k: b'\xEB\x90',
    )
    assert p._pull_one_frame(ctx, 0x80, 0, 1, clear_rx=True) is None
    assert p._last_pull_errors

    # soft errors retry then succeed True
    p._assembler = MagicMock()
    p._assembler.accept_frame.side_effect = [None, True]
    # accept_frame returning True is weird — use AssembledPayload for done
    done = AssembledPayload(data=b'\x00' * 4, meta={'width': 2, 'height': 2})
    p._assembler.accept_frame.side_effect = [None, done]
    p._assembler.take_errors.side_effect = [['校验错误'], []]
    p._recv_response = MagicMock(return_value=b'\x11' * 10)  # type: ignore
    ctx.reset_input_buffer = MagicMock(side_effect=RuntimeError('x'))
    out = p._pull_one_frame(ctx, 0x80, 0, 1, clear_rx=True)
    assert out is done

    # hard error
    p._assembler.accept_frame.return_value = None
    p._assembler.accept_frame.side_effect = None
    p._assembler.take_errors.return_value = ['序号错误']
    p._assembler.take_errors.side_effect = None
    with patch(
        'module_payload.collectors.plugins.camera_image.push_pipeline_error'
    ) as pe:
        assert p._pull_one_frame(ctx, 0x80, 0, 1) is None
        pe.assert_called()

    # mid progress True
    p._assembler.accept_frame.return_value = None
    p._assembler.take_errors.return_value = []
    assert p._pull_one_frame(ctx, 0x40, 1, 1) is True


def test_camera_fail_store_acquire(monkeypatch) -> None:
    p = CameraImageSerialPlugin()
    p._enabled = False
    p._fail(_ctx(), 'x')  # early

    p._enabled = True
    p._once = True
    p._flush_pending_io = MagicMock()
    p._set_image_phase = MagicMock()
    with (
        patch('module_payload.collectors.plugins.camera_image.push_pipeline_error'),
        patch('module_payload.collectors.plugins.camera_image.time.sleep'),
    ):
        p._fail(_ctx(write_status=MagicMock()), 'fail once')
    assert p._enabled is False

    p._enabled = True
    p._once = False
    with (
        patch('module_payload.collectors.plugins.camera_image.push_pipeline_error'),
        patch('module_payload.collectors.plugins.camera_image.time.sleep') as sl,
    ):
        p._fail(_ctx(write_status=MagicMock()), 'fail cont')
        sl.assert_called_with(FAIL_SLEEP_S)

    # store image invalid / png / raw
    p._store_image(_ctx(), AssembledPayload(data=b'', meta={'width': 0, 'height': 0}))
    redis = MagicMock()
    status = MagicMock()
    item = AssembledPayload(data=bytes(4), meta={'width': 2, 'height': 2, 'imageNo': 0})
    import PIL.Image as PILImage

    with patch.object(PILImage, 'frombytes', return_value=MagicMock(save=MagicMock())):
        p._store_image(_ctx(redis=redis, write_status=status), item)
    assert redis.set.call_count >= 2

    with patch.object(PILImage, 'frombytes', side_effect=RuntimeError('no pillow')):
        p._store_image(_ctx(redis=redis, write_status=status), item)

    # acquire stop mid-plan
    p._cfg = {'resolution': '8', 'image_no': 1}
    p._enabled = True
    p._assembler = MagicMock()
    monkeypatch.setattr(
        'module_payload.collectors.plugins.camera_image.plan_d6_image_requests',
        lambda n: [(0x80, 0), (0x40, 1), (0x01, 2)],
    )
    p._pull_one_frame = MagicMock(side_effect=lambda *a, **k: setattr(p, '_enabled', False) or None)  # type: ignore
    p._clear_image_cache = MagicMock()
    p._set_image_phase = MagicMock()
    p._acquire_image_once(_ctx(write_status=MagicMock()))
    p._clear_image_cache.assert_called()

    # first frame fail
    p._enabled = True
    p._last_pull_errors = ['等待应答超时']
    p._pull_one_frame = MagicMock(return_value=None)  # type: ignore
    p._fail = MagicMock()
    p._acquire_image_once(_ctx(write_status=MagicMock()))
    p._fail.assert_called()
    assert '首帧' in p._fail.call_args[0][1]

    # finish on AssembledPayload
    p._enabled = True
    done = AssembledPayload(data=bytes(4), meta={'width': 2, 'height': 2})
    p._pull_one_frame = MagicMock(return_value=done)  # type: ignore
    p._finish_image = MagicMock()
    p._acquire_image_once(_ctx(write_status=MagicMock()))
    p._finish_image.assert_called()

    # empty plan
    monkeypatch.setattr(
        'module_payload.collectors.plugins.camera_image.plan_d6_image_requests',
        lambda n: [],
    )
    p._enabled = True
    p._fail = MagicMock()
    p._acquire_image_once(_ctx(write_status=MagicMock()))
    p._fail.assert_called()

    # all True then incomplete
    monkeypatch.setattr(
        'module_payload.collectors.plugins.camera_image.plan_d6_image_requests',
        lambda n: [(0x80, 0), (0x01, 1)],
    )
    p._enabled = True
    p._pull_one_frame = MagicMock(return_value=True)  # type: ignore
    p._fail = MagicMock()
    p._acquire_image_once(_ctx(write_status=MagicMock()))
    assert '完整拼图' in p._fail.call_args[0][1]

    # stop after poll every 32 frames
    plan = [(0x40, i) for i in range(33)]
    plan[0] = (0x80, 0)
    plan[-1] = (0x01, 32)
    monkeypatch.setattr(
        'module_payload.collectors.plugins.camera_image.plan_d6_image_requests',
        lambda n: plan,
    )
    n = {'i': 0}

    def pull(*a, **k):
        n['i'] += 1
        if n['i'] >= 32:
            p._enabled = False
            return True
        return True

    p._enabled = True
    p._pull_one_frame = pull  # type: ignore
    p._clear_image_cache = MagicMock()
    p._maybe_poll_control = MagicMock()
    p._acquire_image_once(_ctx(write_status=MagicMock()))
    p._clear_image_cache.assert_called()


def test_camera_finish_image_modes(monkeypatch) -> None:
    p = CameraImageSerialPlugin()
    p._enabled = True
    p._once = True
    p._frame_idx = 2
    p._flush_pending_io = MagicMock()
    p._store_image = MagicMock()
    status = MagicMock()
    item = AssembledPayload(data=bytes(4), meta={'width': 2, 'height': 2})
    monkeypatch.setattr(
        'module_payload.collectors.plugins.camera_image.time.sleep',
        MagicMock(),
    )
    p._finish_image(_ctx(write_status=status), item, time.perf_counter())
    p._store_image.assert_called()
    assert p._enabled is False

    p._enabled = False
    p._clear_image_cache = MagicMock()
    p._finish_image(_ctx(), item, time.perf_counter())
    p._clear_image_cache.assert_called()

    p._enabled = True
    p._once = False
    p._store_image = MagicMock()
    sleep = MagicMock()
    monkeypatch.setattr(
        'module_payload.collectors.plugins.camera_image.time.sleep',
        sleep,
    )
    p._finish_image(_ctx(write_status=MagicMock()), item, time.perf_counter())
    sleep.assert_called()


def test_camera_on_session_refresh_v17() -> None:
    p = CameraImageSerialPlugin()
    ctx = _ctx(config={'source': 'camera_image_v17', 'assemblerId': ASSEMBLER_CAMERA_IMAGE_D6_V17})
    with patch(
        'module_payload.collectors.plugins.camera_image.get_session_sync',
        return_value={'assemblerId': ASSEMBLER_CAMERA_IMAGE_D6_V17, 'source': 'camera_image_v17'},
    ):
        p.on_session_refresh(ctx)
    assert p._assembler_id == ASSEMBLER_CAMERA_IMAGE_D6_V17


def test_camera_recv_partial_and_mid_stop(monkeypatch) -> None:
    from module_payload.assemblers.camera_image_d6 import FRAME_SIZE, FRAME_HEADER, calc_checksum, DATA_CHUNK_SIZE

    p = CameraImageSerialPlugin()
    p._enabled = True
    # build one valid full response and feed in chunks
    data = bytes(DATA_CHUNK_SIZE)
    body = bytes([0xD6, 0x80, 0x01, 0x01, 0, 0, 1]) + data
    frame = FRAME_HEADER + body + bytes([calc_checksum(body)])
    chunks = [frame[:10], frame[10:]]

    def read(n):
        return chunks.pop(0) if chunks else b''

    got = p._recv_response(_ctx(read_serial=read), timeout_s=1.0)
    assert got == frame

    # stop while waiting (enabled cleared after empty read)
    p._enabled = True
    n = {'i': 0}

    def read2(n_bytes):
        n['i'] += 1
        if n['i'] > 1:
            p._enabled = False
        return b''

    assert p._recv_response(_ctx(read_serial=read2, is_running=lambda: True), timeout_s=0.2) is None

    # mid-plan disable via poll every 32 frames (covers idx&0x1F poll stop)
    plan = [(0x80, 0)] + [(0x40, i) for i in range(1, 40)]
    monkeypatch.setattr(
        'module_payload.collectors.plugins.camera_image.plan_d6_image_requests',
        lambda _n: plan,
    )
    p._cfg = {'resolution': '8', 'image_no': 1}
    p._enabled = True
    p._assembler = MagicMock()
    p._set_image_phase = MagicMock()
    p._clear_image_cache = MagicMock()
    p._pull_one_frame = MagicMock(return_value=True)  # type: ignore

    def poll_stop(_ctx):
        p._enabled = False

    p._maybe_poll_control = poll_stop  # type: ignore
    p._acquire_image_once(_ctx(write_status=MagicMock()))
    p._clear_image_cache.assert_called()

    # top-of-loop clear when already disabled before first frame
    p._enabled = False
    p._clear_image_cache.reset_mock()
    p._acquire_image_once(_ctx(write_status=MagicMock()))
    p._clear_image_cache.assert_called()

    # last-frame fail label
    p._enabled = True
    p._last_pull_errors = ['尾错']
    monkeypatch.setattr(
        'module_payload.collectors.plugins.camera_image.plan_d6_image_requests',
        lambda _n: [(0x80, 0), (0x01, 1)],
    )
    p._pull_one_frame = MagicMock(side_effect=[True, None])  # type: ignore
    p._fail = MagicMock()
    p._acquire_image_once(_ctx(write_status=MagicMock()))
    assert '尾帧' in p._fail.call_args[0][1]

    # mid-frame fail label
    p._enabled = True
    monkeypatch.setattr(
        'module_payload.collectors.plugins.camera_image.plan_d6_image_requests',
        lambda _n: [(0x80, 0), (0x40, 1), (0x01, 2)],
    )
    p._pull_one_frame = MagicMock(side_effect=[True, None])  # type: ignore
    p._fail = MagicMock()
    p._acquire_image_once(_ctx(write_status=MagicMock()))
    assert '中间帧' in p._fail.call_args[0][1]

    # disable between pull returns
    p._enabled = True
    monkeypatch.setattr(
        'module_payload.collectors.plugins.camera_image.plan_d6_image_requests',
        lambda _n: [(0x80, 0), (0x01, 1)],
    )

    def pull_then_stop(*_a, **_k):
        p._enabled = False
        return True

    p._pull_one_frame = pull_then_stop  # type: ignore
    p._clear_image_cache = MagicMock()
    p._acquire_image_once(_ctx(write_status=MagicMock()))
    p._clear_image_cache.assert_called()


def test_set_image_phase_swallows() -> None:
    p = CameraImageSerialPlugin()
    redis = MagicMock()
    redis.set.side_effect = RuntimeError('x')
    p._set_image_phase(_ctx(redis=redis), 'acquiring', 'm', extra={'a': 1})
