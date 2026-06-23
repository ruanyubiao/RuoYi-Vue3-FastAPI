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
