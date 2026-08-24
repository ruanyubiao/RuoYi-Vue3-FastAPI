"""全双工采集：收发分线程，半双工保持单循环。"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from module_payload.collectors.base_collector import BaseCollector
from module_payload.collectors.duplex import coerce_full_duplex, resolve_full_duplex


def test_coerce_full_duplex() -> None:
    assert coerce_full_duplex(None) is None
    assert coerce_full_duplex(True) is True
    assert coerce_full_duplex(False) is False
    assert coerce_full_duplex('true') is True
    assert coerce_full_duplex('0') is False


def test_resolve_full_duplex_defaults_half() -> None:
    assert resolve_full_duplex(source='home') is False
    assert resolve_full_duplex(source='') is False
    assert resolve_full_duplex(explicit=False) is False
    assert resolve_full_duplex(explicit=True) is True


def test_resolve_full_duplex_from_connect_cfg() -> None:
    assert resolve_full_duplex(source='camera_ctrl') is True
    assert resolve_full_duplex(source='camera_image') is True
    assert resolve_full_duplex(source='biu_can_a') is False
    assert resolve_full_duplex(source='camera_ctrl', explicit=False) is False


def test_is_full_duplex_reads_config_and_channels() -> None:
    c = BaseCollector.__new__(BaseCollector)
    c.config = {'full_duplex': True}
    assert c._is_full_duplex() is True
    c.config = {'channels': [{'full_duplex': False}, {'fullDuplex': True}]}
    assert c._is_full_duplex() is True
    c.config = {'full_duplex': False, 'channels': []}
    assert c._is_full_duplex() is False


def test_full_duplex_rx_does_not_block_commands(monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )

    started = threading.Event()
    cmd_done = threading.Event()

    class Coll(BaseCollector):
        def setup(self) -> bool:
            return True

        def read_and_parse(self) -> None:
            started.set()
            time.sleep(0.35)

        def execute_command(self, command: dict) -> dict:
            cmd_done.set()
            return {'success': True}

        def _heartbeat(self) -> None:
            return

        def _consume_control(self) -> None:
            return

        def _consume_commands(self) -> None:
            self.execute_command({'hex': '00'})
            self._running = False

        def _write_status(self, *_a, **_k) -> None:
            return

        def teardown(self) -> None:
            return

    coll = Coll('serial:COM9', {'full_duplex': True, 'loop_interval_s': 0.01})
    t = threading.Thread(target=coll.run)
    t.start()
    assert cmd_done.wait(timeout=0.5)
    t.join(timeout=2.0)
    assert started.is_set()
    assert not t.is_alive()
