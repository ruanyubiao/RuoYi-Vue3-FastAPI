from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class TelemetryTableQueryModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
    type: str


class CurveSubscribeModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
    type: str
    field: str
    enabled: bool = True


class CurveDataQueryModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
    type: str
    field: str
    limit: int = 600


class CanYcInjectModel(BaseModel):
    """开发测试：注入已组帧的 CAN 遥测复合帧 HEX。"""

    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str = Field(description='目标设备ID，如 can:0:0:0')
    hex: str = Field(description='完整 CAN 遥测复合帧 HEX（空格可选）')
