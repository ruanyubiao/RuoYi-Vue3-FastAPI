"""串口 RX 积压：丢弃硬件缓冲时同步清空组帧缓存。"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

from module_payload.collectors.base_collector import BaseCollector
from module_payload.collectors.serial_collector import MAX_WAITING, SerialCollector


class _Asm:
    def __init__(self) -> None:
        self.reset_calls = 0

    def reset(self) -> None:
        self.reset_calls += 1


class _Demux:
    def __init__(self) -> None:
        self.clear_calls = 0

    def clear(self) -> None:
        self.clear_calls += 1


class _Plugin:
    def __init__(self) -> None:
        self.reset_rx_calls = 0

    def reset_rx(self) -> None:
        self.reset_rx_calls += 1


def test_reset_rx_framing_clears_assembler_demux_plugin() -> None:
    c = BaseCollector.__new__(BaseCollector)
    c._pipeline_lock = threading.RLock()
    c._assembler = _Asm()
    extra = _Asm()
    c._assemblers = {'eng': extra}
    c._demux = _Demux()
    c._plugin = _Plugin()

    c._reset_rx_framing()

    assert c._assembler.reset_calls == 1
    assert extra.reset_calls == 1
    assert c._demux.clear_calls == 1
    assert c._plugin.reset_rx_calls == 1


def test_read_and_parse_overflow_drops_hw_and_framing() -> None:
    coll = SerialCollector.__new__(SerialCollector)
    coll._pipeline_lock = threading.RLock()
    coll._assembler = _Asm()
    coll._assemblers = {}
    coll._demux = _Demux()
    coll._plugin = None
    coll._ser = MagicMock()
    coll._running = True
    coll._cached_source = 'x'
    coll._plugin_id = None
    coll._port_still_present = lambda: True  # type: ignore[method-assign]
    coll._sync_plugin = lambda force_session=False: None  # type: ignore[method-assign]
    coll._in_waiting = lambda: MAX_WAITING + 1  # type: ignore[method-assign]
    coll._reset_input_buffer = MagicMock()  # type: ignore[method-assign]

    coll.read_and_parse()

    coll._reset_input_buffer.assert_called_once()
    assert coll._assembler.reset_calls == 1
    assert coll._demux.clear_calls == 1
    coll._ser.reset_input_buffer.assert_not_called()
    coll._ser.read.assert_not_called()
