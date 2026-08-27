"""设备服务门面：拆 mixin 后公开方法名不变。"""

from __future__ import annotations

from module_payload.service.payload_device_service import PayloadDeviceService

_PUBLIC = (
    'is_session_device_alive',
    'list_alive_sessions',
    'list_can_vendors',
    'list_can_channels',
    'open_can',
    'close_can',
    'set_can_cable',
    'list_serial_ports',
    'list_serial_opened',
    'open_serial',
    'close_serial',
    'list_local_addresses',
    'list_net_opened',
    'open_net',
    'close_net',
    'close_all',
    'get_io_log',
    'clear_io_log',
    'get_device_status',
    'get_snapshot',
)


def test_payload_device_service_public_methods() -> None:
    for name in _PUBLIC:
        assert callable(getattr(PayloadDeviceService, name)), name
