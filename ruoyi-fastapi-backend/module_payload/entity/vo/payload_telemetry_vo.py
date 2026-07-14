from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class TelemetryTableQueryModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
    type: str


class CurveDataQueryModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
    type: str
    field: str
    limit: int = 600


class CurveBatchItemModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
    type: str
    field: str
    limit: int = 500
    since_t: int | None = None


class CurveBatchQueryModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    items: list[CurveBatchItemModel]


class HistoryCurveBatchItemModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
    type: str
    field: str
    start_t: int = Field(description='起始时间戳(ms)')
    end_t: int = Field(description='结束时间戳(ms)')
    limit: int = 50000


class HistoryCurveBatchQueryModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    items: list[HistoryCurveBatchItemModel]


class CanYcInjectModel(BaseModel):
    """开发测试：注入已组帧的 CAN 遥测复合帧 HEX。"""

    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str = Field(description='目标设备ID，如 can:0:0:0')
    hex: str = Field(description='完整 CAN 遥测复合帧 HEX（空格可选）')
