"""
串口采集进程骨架（含相机图像采集）。

参考 test/showimg/serial_image_viewer.py（EB 90 协议、整图重组）与 RS422 协议。
依赖库 ``pyserial`` 在方法内延迟导入。打开即开进程，关闭即关进程。
"""

from __future__ import annotations

from typing import Any

from module_payload.collectors.base_collector import BaseCollector


class SerialCollector(BaseCollector):
    """串口采集进程：初始化串口、读取二进制数据/图像、执行串口指令。"""

    def __init__(self, device_id: str, config: dict[str, Any]) -> None:
        super().__init__(device_id, config)
        self._ser = None  # serial.Serial

    def setup(self) -> bool:
        # TODO(P4): import serial; serial.Serial(port, baudrate, bytesize, parity, stopbits, timeout)
        raise NotImplementedError('SerialCollector.setup 待 P4 实现')

    def read_and_parse(self) -> None:
        # TODO(P4): 按 EB 90 协议重组整图，写 image_key；或解析 RS422 遥测
        raise NotImplementedError('SerialCollector.read_and_parse 待 P4 实现')

    def execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        # TODO(P4): 写串口指令并回执
        raise NotImplementedError('SerialCollector.execute_command 待 P4 实现')

    def teardown(self) -> None:
        # TODO(P4): self._ser.close()
        ...
