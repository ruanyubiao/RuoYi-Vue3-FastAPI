"""
CAN 采集进程骨架。

进程粒度：``vendor`` + ``dev_index`` 相同的同一张 CAN 卡，所有通道(``can_index``)共用一个进程；
通过引用计数管理，卡上所有通道关闭后才回收进程（见 doc/02-数据采集层设计.md）。

依赖库 ``gpcan`` 在方法内延迟导入（whl/gpcan-1.0.0-py3-none-any.whl）。
"""

from __future__ import annotations

from typing import Any

from module_payload.collectors.base_collector import BaseCollector


class CanCollector(BaseCollector):
    """CAN 采集进程：一张卡一个进程，内部维护多个已打开通道。"""

    def __init__(self, device_id: str, config: dict[str, Any]) -> None:
        super().__init__(device_id, config)
        self._client = None  # gpcan.CanClient
        self._opened_channels: set[int] = set()

    def setup(self) -> bool:
        # TODO(P1): 延迟导入并初始化 CanClient
        # from gpcan import CanClient, CanCardParam, CanMsgParam, CanSendParam, CanRetCode
        # self._client = CanClient(vendor, CanCardParam(...), CanMsgParam(...), CanSendParam(...))
        # return self._client.init_can() == CanRetCode.CAN_RET_CODE_OK and self._client.open_can() == ...
        raise NotImplementedError('CanCollector.setup 待 P1 实现')

    def read_and_parse(self) -> None:
        # TODO(P1): client.recv_msg(64) -> 取数据类型字节 -> telemetryparser 解析 -> 写 telemetry_key/curve_key
        raise NotImplementedError('CanCollector.read_and_parse 待 P1 实现')

    def execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        # TODO(P1): HEX->字节; 按 broadcast/all_channel 选择 send_msg/send; 返回 {success, message}
        raise NotImplementedError('CanCollector.execute_command 待 P1 实现')

    def teardown(self) -> None:
        # TODO(P1): client.close_can(); client.deinit_can()
        ...

    def open_channel(self, can_index: int) -> None:
        """向当前卡进程追加打开一个通道。"""
        # TODO(P1): client.open_can(can_index); self._opened_channels.add(can_index)
        ...

    def close_channel(self, can_index: int) -> bool:
        """关闭一个通道，返回该卡是否已无打开通道(可回收进程)。"""
        self._opened_channels.discard(can_index)
        return len(self._opened_channels) == 0
