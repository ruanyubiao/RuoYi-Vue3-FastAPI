"""硬件枚举超时与降级。"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

from module_payload.collectors.hw_probe import call_with_timeout
from module_payload.collectors.serial_ports import list_ports

def test_call_with_timeout_raises_on_slow_probe() -> None:
    def slow() -> str:
        time.sleep(0.2)
        return 'ok'

    with patch('module_payload.collectors.hw_probe.HW_PROBE_TIMEOUT_SEC', 0.05):
        try:
            call_with_timeout(slow, timeout=0.05, label='test_slow')
            assert False, 'should timeout'
        except TimeoutError:
            pass


def test_list_ports_merges_pyserial_and_registry() -> None:
    fake = [SimpleNamespace(device='COM1', description='uart')]
    with (
        patch('serial.tools.list_ports.comports', return_value=fake),
        patch('module_payload.collectors.serial_ports._ports_from_registry', return_value=['com1', 'COM10']),
    ):
        ports = list_ports()
    assert [p.device for p in ports] == ['COM1', 'COM10']
    assert ports[0].description == 'uart'
    assert ports[1].description == ''