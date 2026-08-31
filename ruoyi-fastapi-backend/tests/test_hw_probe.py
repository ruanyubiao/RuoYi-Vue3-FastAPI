"""硬件枚举超时与降级。"""

from __future__ import annotations

import time
from unittest.mock import patch

from module_payload.hw_probe import call_with_timeout
from module_payload.service.device_can import DeviceCanMixin
from module_payload.service.device_serial import DeviceSerialMixin

def test_call_with_timeout_raises_on_slow_probe() -> None:
    def slow() -> str:
        time.sleep(0.2)
        return 'ok'

    with patch('module_payload.hw_probe.HW_PROBE_TIMEOUT_SEC', 0.05):
        try:
            call_with_timeout(slow, timeout=0.05, label='test_slow')
            assert False, 'should timeout'
        except TimeoutError:
            pass


def test_list_can_vendors_returns_empty_on_timeout() -> None:
    def slow_sdk() -> list[dict]:
        time.sleep(0.2)
        return []

    with patch.object(DeviceCanMixin, '_build_can_vendors_from_sdk', side_effect=slow_sdk):
        with patch('module_payload.service.device_can.HW_PROBE_TIMEOUT_SEC', 0.05):
            result = DeviceCanMixin.list_can_vendors()
    assert result['vendors'] == []
    assert result['defaultVendor'] == 0


def test_list_serial_ports_returns_empty_on_timeout() -> None:
    def slow_ports() -> list:
        time.sleep(0.2)
        return []

    with patch.object(DeviceSerialMixin, '_enumerate_serial_ports', side_effect=slow_ports):
        with patch('module_payload.service.device_serial.HW_PROBE_TIMEOUT_SEC', 0.05):
            ports = DeviceSerialMixin.list_serial_ports()
    assert ports == []