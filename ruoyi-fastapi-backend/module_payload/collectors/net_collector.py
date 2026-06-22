"""
网络采集进程骨架。

配置 IP/端口/协议(TCP/UDP)，建立连接、实时收包、就地解析、执行网络指令；
TCP 支持断线自动重连。每个连接一个进程。依赖标准库 ``socket``。
"""

from __future__ import annotations

from typing import Any

from module_payload.collectors.base_collector import BaseCollector


class NetCollector(BaseCollector):
    """网络采集进程：TCP/UDP 收发与就地解析。"""

    def __init__(self, device_id: str, config: dict[str, Any]) -> None:
        super().__init__(device_id, config)
        self._sock = None  # socket.socket

    def setup(self) -> bool:
        # TODO(P5+): 建立 TCP/UDP socket；TCP 连接失败重试
        raise NotImplementedError('NetCollector.setup 待后续实现')

    def read_and_parse(self) -> None:
        # TODO(P5+): recv -> 自定义协议解析(待确认) -> 写 Redis
        raise NotImplementedError('NetCollector.read_and_parse 待后续实现')

    def execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        # TODO(P5+): 通过 TCP/UDP 发送指令并回执
        raise NotImplementedError('NetCollector.execute_command 待后续实现')

    def teardown(self) -> None:
        # TODO(P5+): self._sock.close()
        ...
