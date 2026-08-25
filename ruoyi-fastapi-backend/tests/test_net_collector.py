"""UDP 网口采集：绑定、收发、设备 ID 无 net: 前缀。"""

from __future__ import annotations

import socket
from unittest.mock import MagicMock

from module_payload.collectors.net_collector import NetCollector
from module_payload import redis_keys as rk


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _collector(monkeypatch, **cfg) -> NetCollector:
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )
    port = cfg.get('local_port', _free_udp_port())
    host = cfg.get('local_host', '127.0.0.1')
    proto = cfg.get('proto', 'udp')
    device_id = rk.net_id(proto, host, port)
    coll = NetCollector(
        device_id,
        {
            'proto': proto,
            'local_host': host,
            'local_port': port,
            'remote_host': cfg.get('remote_host', '127.0.0.1'),
            'remote_port': cfg.get('remote_port', port),
            **{k: v for k, v in cfg.items() if k not in ('local_port', 'local_host', 'proto', 'remote_host', 'remote_port')},
        },
    )
    coll._push_io = MagicMock()  # type: ignore[method-assign]
    coll._try_session_ingest = MagicMock()  # type: ignore[method-assign]
    coll._write_status = MagicMock()  # type: ignore[method-assign]
    return coll


def test_net_id_not_prefixed(monkeypatch) -> None:
    c = _collector(monkeypatch, local_port=34567)
    assert c.device_id == 'udp:127.0.0.1:34567'
    assert not c.device_id.startswith('net:')


def test_setup_rejects_non_udp(monkeypatch) -> None:
    c = _collector(monkeypatch, proto='tcp', local_port=34568)
    assert c.setup() is False
    c._write_status.assert_called()


def test_setup_rejects_bad_port(monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: MagicMock(),
    )
    c = NetCollector('udp:127.0.0.1:0', {'proto': 'udp', 'local_host': '127.0.0.1', 'local_port': 0})
    c._write_status = MagicMock()  # type: ignore[method-assign]
    assert c.setup() is False


def test_udp_loopback_send_recv(monkeypatch) -> None:
    c = _collector(monkeypatch)
    assert c.setup() is True
    try:
        sent = c.execute_command({'hex': 'AA BB CC'})
        assert sent['success'] is True
        c.read_and_parse()
        c._try_session_ingest.assert_called()
        data = c._try_session_ingest.call_args.args[0]
        assert data == bytes([0xAA, 0xBB, 0xCC])
        c._push_io.assert_called()
        c._try_session_ingest.reset_mock()
        sent_odd = c.execute_command({'hex': 'A B'})
        assert sent_odd['success'] is True
        c.read_and_parse()
        assert c._try_session_ingest.call_args.args[0] == bytes([0x0A, 0x0B])
    finally:
        c.teardown()


def test_execute_requires_peer_and_hex(monkeypatch) -> None:
    c = _collector(monkeypatch, remote_host='', remote_port=0)
    assert c.setup() is True
    try:
        assert c.execute_command({'hex': 'ZZ'})['success'] is False
        assert c.execute_command({'hex': ''})['success'] is False
        assert '远程' in c.execute_command({'hex': 'AA'})['message']
    finally:
        c.teardown()
