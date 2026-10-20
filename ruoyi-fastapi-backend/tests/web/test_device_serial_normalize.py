"""串口物理参数归一化与一致性比对。"""

from __future__ import annotations

from module_payload.service.device_serial import DeviceSerialMixin


def test_norm_parity_aliases() -> None:
    assert DeviceSerialMixin._norm_parity('NONE') == 'N'
    assert DeviceSerialMixin._norm_parity('even') == 'E'
    assert DeviceSerialMixin._norm_parity('ODD') == 'O'
    assert DeviceSerialMixin._norm_parity('MARK') == 'M'
    assert DeviceSerialMixin._norm_parity('SPACE') == 'S'
    assert DeviceSerialMixin._norm_parity('') == 'N'


def test_norm_flow_aliases() -> None:
    assert DeviceSerialMixin._norm_flow('NONE') == 'NONE'
    assert DeviceSerialMixin._norm_flow('XONXOFF') == 'XON/XOFF'
    assert DeviceSerialMixin._norm_flow('RTS/CTS') == 'RTS/CTS'
    assert DeviceSerialMixin._norm_flow('dtr-dsr') == 'DTR/DSR'
    assert DeviceSerialMixin._norm_flow('') == 'NONE'


def test_serial_config_matches_same_aliases() -> None:
    running = {
        'baudrate': 115200,
        'data_bits': 8,
        'stop_bits': 1,
        'parity': 'EVEN',
        'flow_control': 'XONXOFF',
    }
    requested = {
        'baudrate': 115200,
        'data_bits': 8,
        'stop_bits': 1.0,
        'parity': 'E',
        'flow_control': 'XON/XOFF',
    }
    assert DeviceSerialMixin._serial_config_matches(running, requested) is True


def test_serial_config_matches_baud_mismatch() -> None:
    running = {'baudrate': 9600, 'data_bits': 8, 'stop_bits': 1, 'parity': 'N', 'flow_control': 'NONE'}
    requested = {'baudrate': 115200, 'data_bits': 8, 'stop_bits': 1, 'parity': 'N', 'flow_control': 'NONE'}
    assert DeviceSerialMixin._serial_config_matches(running, requested) is False


def test_serial_config_matches_invalid_number() -> None:
    running = {'baudrate': 'bad', 'data_bits': 8, 'stop_bits': 1, 'parity': 'N', 'flow_control': 'NONE'}
    requested = {'baudrate': 9600, 'data_bits': 8, 'stop_bits': 1, 'parity': 'N', 'flow_control': 'NONE'}
    assert DeviceSerialMixin._serial_config_matches(running, requested) is False
