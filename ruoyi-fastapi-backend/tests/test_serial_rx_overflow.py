"""串口 RX 积压：丢硬件缓冲时必须同步清空组帧 / 分流 / 插件缓存。"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

from module_payload.collectors.base_collector import BaseCollector
from module_payload.collectors.plugins.base import TickResult
from module_payload.collectors.serial_collector import (
    DEFAULT_BAUDRATE,
    MAX_WAITING,
    RX_CACHE_S,
    SerialCollector,
    rx_waiting_limit_bytes,
)


class _Asm:
    def __init__(self, *, boom: bool = False) -> None:
        self.reset_calls = 0
        self.boom = boom

    def reset(self) -> None:
        self.reset_calls += 1
        if self.boom:
            raise RuntimeError('assembler reset failed')


class _Demux:
    def __init__(self, *, boom: bool = False) -> None:
        self.clear_calls = 0
        self.boom = boom

    def clear(self) -> None:
        self.clear_calls += 1
        if self.boom:
            raise RuntimeError('demux clear failed')


class _Plugin:
    def __init__(self, *, boom: bool = False) -> None:
        self.reset_rx_calls = 0
        self.boom = boom

    def reset_rx(self) -> None:
        self.reset_rx_calls += 1
        if self.boom:
            raise RuntimeError('plugin reset_rx failed')


def _base(**kwargs) -> BaseCollector:
    c = BaseCollector.__new__(BaseCollector)
    c._pipeline_lock = threading.RLock()
    c._assembler = kwargs.pop('assembler', _Asm())
    c._assemblers = kwargs.pop('assemblers', {})
    c._demux = kwargs.pop('demux', _Demux())
    c._plugin = kwargs.pop('plugin', None)
    for key, val in kwargs.items():
        setattr(c, key, val)
    return c


def _serial(**kwargs) -> SerialCollector:
    coll = SerialCollector.__new__(SerialCollector)
    coll.device_id = 'serial:COM4'
    coll.config = {}
    coll._pipeline_lock = threading.RLock()
    coll._assembler = _Asm()
    coll._assemblers = {}
    coll._demux = _Demux()
    coll._plugin = None
    coll._plugin_id = None
    coll._ser = MagicMock()
    coll._running = True
    coll._cached_source = 'camera_ctrl'
    coll._max_waiting = MAX_WAITING
    coll._rx_count = 0
    coll._port_still_present = lambda: True  # type: ignore[method-assign]
    coll._sync_plugin = lambda force_session=False: None  # type: ignore[method-assign]
    coll._in_waiting = lambda: 0  # type: ignore[method-assign]
    coll._reset_input_buffer = MagicMock()  # type: ignore[method-assign]
    coll._read_serial = MagicMock(return_value=b'')  # type: ignore[method-assign]
    coll._push_io = MagicMock()  # type: ignore[method-assign]
    coll._push_stream_io = MagicMock()  # type: ignore[method-assign]
    coll._xfer_append_io = MagicMock()  # type: ignore[method-assign]
    coll._try_session_ingest = MagicMock()  # type: ignore[method-assign]
    for key, val in kwargs.items():
        setattr(coll, key, val)
    return coll


def test_max_waiting_is_5s_at_2m_8o1() -> None:
    # 1 start + 8 data + 1 parity + 1 stop = 11 bit/字节；2e6/11*5 ≈ 909091
    expect = rx_waiting_limit_bytes(DEFAULT_BAUDRATE)
    assert expect == 909091
    assert MAX_WAITING == expect
    assert RX_CACHE_S == 5.0


def test_rx_waiting_limit_scales_with_baud_and_parity() -> None:
    assert rx_waiting_limit_bytes(2_000_000, parity='N') == 1_000_000
    # 相机口 11Mbps 8O1、5 秒 ≈ 5MB
    assert rx_waiting_limit_bytes(11_000_000) == 5_000_000


def test_reset_rx_framing_clears_assembler_demux_plugin() -> None:
    extra = _Asm()
    plugin = _Plugin()
    c = _base(assemblers={'eng': extra}, plugin=plugin)

    c._reset_rx_framing()

    assert c._assembler.reset_calls == 1
    assert extra.reset_calls == 1
    assert c._demux.clear_calls == 1
    assert plugin.reset_rx_calls == 1


def test_reset_rx_framing_skips_missing_and_noncallable() -> None:
    c = _base(assembler=object(), assemblers=None, demux=object(), plugin=object())
    c._reset_rx_framing()


def test_reset_rx_framing_swallows_reset_errors() -> None:
    extra = _Asm(boom=True)
    c = _base(
        assembler=_Asm(boom=True),
        assemblers={'x': extra},
        demux=_Demux(boom=True),
        plugin=_Plugin(boom=True),
    )
    c._reset_rx_framing()
    assert c._assembler.reset_calls == 1
    assert extra.reset_calls == 1
    assert c._demux.clear_calls == 1
    assert c._plugin.reset_rx_calls == 1


def test_drop_rx_overflow_resets_hw_then_framing() -> None:
    coll = _serial()
    coll._reset_rx_framing = MagicMock()  # type: ignore[method-assign]
    coll._drop_rx_overflow()
    coll._reset_input_buffer.assert_called_once()
    coll._reset_rx_framing.assert_called_once()


def test_read_and_parse_overflow_drops_hw_and_framing() -> None:
    coll = _serial(_in_waiting=lambda: MAX_WAITING + 1)

    coll.read_and_parse()

    coll._reset_input_buffer.assert_called_once()
    assert coll._assembler.reset_calls == 1
    assert coll._demux.clear_calls == 1
    coll._ser.reset_input_buffer.assert_not_called()
    coll._read_serial.assert_not_called()
    coll._try_session_ingest.assert_not_called()
    coll._push_io.assert_not_called()


def test_read_and_parse_equal_max_waiting_still_reads() -> None:
    """阈值是严格大于，等于 MAX_WAITING 时继续读。"""
    chunks = [b'\x01\x02', b'']

    def _in_waiting() -> int:
        return MAX_WAITING if chunks[0] else 0

    coll = _serial(
        _in_waiting=_in_waiting,
        _read_serial=MagicMock(side_effect=lambda n: chunks.pop(0) if chunks else b''),
    )
    coll.read_and_parse()
    coll._reset_input_buffer.assert_not_called()
    coll._try_session_ingest.assert_called()
    coll._xfer_append_io.assert_called()
    coll._push_stream_io.assert_called()
    coll._push_io.assert_not_called()


def test_read_and_parse_empty_waiting_returns() -> None:
    coll = _serial(_in_waiting=lambda: 0)
    coll.read_and_parse()
    coll._reset_input_buffer.assert_not_called()
    coll._read_serial.assert_not_called()


def test_read_and_parse_port_gone_skips() -> None:
    coll = _serial(_port_still_present=lambda: False)
    coll._in_waiting = MagicMock(side_effect=AssertionError('should not read'))
    coll.read_and_parse()


def test_read_and_parse_no_serial_skips() -> None:
    coll = _serial(_ser=None, _in_waiting=lambda: MAX_WAITING + 1)
    coll.read_and_parse()
    coll._reset_input_buffer.assert_not_called()


def test_plugin_owns_loop_skips_overflow_path() -> None:
    class OwnLoop:
        def tick(self, ctx):
            return TickResult(owns_loop=True)

    coll = _serial(
        _plugin=OwnLoop(),
        _plugin_ctx=lambda: None,  # type: ignore[method-assign]
        _in_waiting=lambda: MAX_WAITING + 1,
    )
    coll.read_and_parse()
    coll._reset_input_buffer.assert_not_called()
    coll._read_serial.assert_not_called()


def test_overflow_also_resets_plugin_rx() -> None:
    class Idle(_Plugin):
        def tick(self, ctx):
            return TickResult(owns_loop=False)

    plugin = Idle()
    coll = _serial(
        _plugin=plugin,
        _plugin_ctx=lambda: None,  # type: ignore[method-assign]
        _in_waiting=lambda: MAX_WAITING + 1,
    )
    coll.read_and_parse()
    assert plugin.reset_rx_calls == 1
