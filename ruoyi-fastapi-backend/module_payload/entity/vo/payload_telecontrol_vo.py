from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class TelecontrolAssembleModel(BaseModel):
    """遥控组帧请求：orderId 或分量列表。"""

    model_config = ConfigDict(alias_generator=to_camel)

    order_id: str | None = None
    components: list[dict[str, Any]] = Field(default_factory=list)
    values: list[Any] = Field(default_factory=list)
    family: str | None = Field(default='biu', description='协议族 biu|xl，映射 cfgId biu-tc|xl-tc')


class TelecontrolSendModel(BaseModel):
    """遥控下发请求：已组帧 Hex 或按 order 组帧后发送。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    device_id: str
    order_id: str | None = None
    name: str | None = None
    hex: str | None = None
    components: list[dict[str, Any]] | None = None
    values: list[Any] | None = None
    broadcast: bool = False
    append_checksum: bool = False
    family: str | None = Field(default='biu', description='协议族 biu|xl；按 order 组帧时使用')
    remote_host: str | None = Field(default=None, description='UDP 等：本次发送目标主机')
    remote_port: int | None = Field(default=None, description='UDP 等：本次发送目标端口')
    display_hex: bool | None = Field(
        default=None, description='原始发送：True=按 HEX 展示发送日志，False=按 ASCII；默认 True'
    )


class CanRawSendModel(BaseModel):
    """CAN 原始帧下发（帧 ID + 数据 Hex）。"""

    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
    frame_id_hex: str = Field(description='32位帧ID，连续8个十六进制字符，不含空格')
    data_hex: str = Field(default='', description='数据HEX，空白分割token，token奇数补0，最多8字节，不足前补0')


class ControlOpModel(BaseModel):
    """控制开关操作请求。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    op: str
    device_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
