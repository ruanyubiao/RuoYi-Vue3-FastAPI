"""
网络采集进程：首版实现 UDP 绑定本机地址/端口，收发数据报并写 IO 日志。
"""

from __future__ import annotations

import socket
from typing import Any

from module_payload.collectors.base_collector import BaseCollector


class NetCollector(BaseCollector):
    """网络采集：UDP 绑定本机地址/端口（TCP 后续扩展）。"""

    def __init__(self, device_id: str, config: dict[str, Any]) -> None:
        """初始化套接字与默认对端。"""
        super().__init__(device_id, config)
        self._sock: socket.socket | None = None  # UDP 套接字
        self._remote_host = ''  # 默认发送对端
        self._remote_port = 0

    def setup(self) -> bool:
        """绑定本机 UDP 端口；非 udp 协议直接失败。"""
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
        """收一包 UDP：写 IO 日志并交给会话入库。"""
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

    def _apply_udp_peer(self, remote_host: Any, remote_port: Any) -> None:
        """复用连接时按本页参数更新默认发送对端（不改本机绑定）。"""
        self._remote_host = str(remote_host or '').strip()
        try:
            self._remote_port = int(remote_port if remote_port is not None else 0)
        except (TypeError, ValueError):
            self._remote_port = 0
        if self._remote_port < 0 or self._remote_port > 65535:
            self._remote_port = 0
        self.config['remote_host'] = self._remote_host
        self.config['remote_port'] = self._remote_port

    def handle_control(self, msg: dict[str, Any]) -> None:
        """会话重绑时可携带 remote_host/remote_port，写入默认对端。"""
        op = msg.get('op')
        if op in ('session_changed', 'rebind', 'source_changed', 'set_udp_peer'):
            if 'remote_host' in msg or 'remote_port' in msg:
                self._apply_udp_peer(msg.get('remote_host'), msg.get('remote_port'))
        super().handle_control(msg)

    def execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        """把指令 HEX 发到远程 host:端口；日志由 `_push_history` 统一写。"""
        if not self._sock:
            return {'success': False, 'message': 'UDP 未就绪'}
        hex_text = command.get('hex', '') or ''
        try:
            from module_payload.cfg.hex_text import hex_to_bytes

            raw = hex_to_bytes(hex_text)
        except ValueError:
            return {'success': False, 'message': 'HEX 格式错误'}
        if not raw:
            return {'success': False, 'message': '数据为空'}
        host = str(command.get('remote_host') or self._remote_host or '').strip()
        port = int(command.get('remote_port') or self._remote_port or 0)
        if not host or port <= 0:
            return {'success': False, 'message': '请指定远程地址和端口'}
        try:
            self._sock.sendto(raw, (host, port))
        except OSError as e:
            return {'success': False, 'message': f'发送失败: {e}'}
        # 发送日志由 BaseCollector._push_history → _push_io 统一写入
        return {'success': True, 'message': 'OK', 'peer': f'{host}:{port}'}

    def teardown(self) -> None:
        """关闭 UDP 套接字并刷盘。"""
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        super().teardown()
