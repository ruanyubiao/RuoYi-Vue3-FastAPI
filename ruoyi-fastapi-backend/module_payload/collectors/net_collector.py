"""
网络采集进程：首版实现 UDP 绑定本机地址/端口，收发数据报并写 IO 日志。
"""

from __future__ import annotations

import socket
from typing import Any

from module_payload.collectors.base_collector import BaseCollector


class NetCollector(BaseCollector):
    """网络采集：UDP（TCP 后续扩展）。"""

    def __init__(self, device_id: str, config: dict[str, Any]) -> None:
        super().__init__(device_id, config)
        self._sock: socket.socket | None = None
        self._remote_host = ''
        self._remote_port = 0

    def setup(self) -> bool:
        proto = str(self.config.get('proto') or 'udp').lower()
        if proto != 'udp':
            self._write_status('error', f'暂不支持协议: {proto}')
            return False
        local_host = self.config.get('local_host') or '0.0.0.0'
        local_port = int(self.config.get('local_port') or 0)
        if local_port <= 0 or local_port > 65535:
            self._write_status('error', '本机端口无效')
            return False
        self._remote_host = str(self.config.get('remote_host') or '')
        self._remote_port = int(self.config.get('remote_port') or 0)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((local_host, local_port))
            sock.settimeout(0.05)
            self._sock = sock
        except OSError as e:
            self._write_status('error', f'UDP 绑定失败: {e}')
            return False
        return True

    def read_and_parse(self) -> None:
        if not self._sock:
            return
        try:
            data, addr = self._sock.recvfrom(65535)
        except (socket.timeout, TimeoutError):
            return
        except OSError:
            return
        if data:
            peer = f'{addr[0]}:{addr[1]}'
            self._push_io('recv', data, peer=peer)
            self._rx_count += 1
            from module_payload.constants import SRC_KIND_UDP

            self._try_session_ingest(data, self.device_id, SRC_KIND_UDP)

    def execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        if not self._sock:
            return {'success': False, 'message': 'UDP 未就绪'}
        hex_text = command.get('hex', '') or ''
        try:
            raw = bytes.fromhex(hex_text.replace(' ', ''))
        except ValueError:
            return {'success': False, 'message': 'HEX 格式错误'}
        if not raw:
            return {'success': False, 'message': '数据为空'}
        host = str(command.get('remote_host') or self._remote_host or '').strip()
        port = int(command.get('remote_port') or self._remote_port or 0)
        if not host or port <= 0:
            return {'success': False, 'message': '请指定远程主机 host:端口'}
        try:
            self._sock.sendto(raw, (host, port))
        except OSError as e:
            return {'success': False, 'message': f'发送失败: {e}'}
        # 发送日志由 BaseCollector._push_history → _push_io 统一写入
        return {'success': True, 'message': 'OK', 'peer': f'{host}:{port}'}

    def teardown(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
