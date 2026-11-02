"""指令应答策略基类。

各协议在自己的目录实现子类，并挂到 ``ProtocolBindings.ack_policy``。
采集进程用 ``describe_send`` 决定要不要等，用 ``classify_rx`` 认出应答帧。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

EXPECT_NONE = 'none'
EXPECT_ALWAYS = 'always'
EXPECT_ON_ERROR = 'on_error'

ACK_NONE = 'none'
ACK_PENDING = 'pending'
ACK_OK = 'ok'
ACK_ERROR = 'error'
ACK_TIMEOUT = 'timeout'

ACK_TIMEOUT_MS = 2000

MSG_ACK_OK = '应答成功'
MSG_ACK_TIMEOUT = '应答超时'
MSG_NO_ERROR_ACK = '无错误应答'


@dataclass(frozen=True, slots=True)
class AckHit:
    """一帧已识别的应答。``status`` 为 ``ok`` 或 ``error``。"""

    corr_id: str
    status: str
    message: str
    hex_text: str


class AckPolicy:
    """协议应答策略。无状态，采集侧按类实例化。"""

    def describe_send(self, cmd: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, str]:
        """这条发送是否等待应答。

        返回 ``expectAck``（``none`` / ``always`` / ``on_error``）和 ``corrId``。
        默认不等待。
        """
        _ = (cmd, context)
        return {'expectAck': EXPECT_NONE, 'corrId': ''}

    def classify_rx(self, frame: Any) -> AckHit | None:
        """收包是应答则返回 ``AckHit``，否则 ``None``（继续走遥测）。"""
        _ = frame
        return None
