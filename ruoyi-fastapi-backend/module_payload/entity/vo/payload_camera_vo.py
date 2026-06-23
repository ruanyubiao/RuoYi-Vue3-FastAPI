from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CameraStartModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    port: str
    resolution: str = Field(default='256×256')
    image_no: int = Field(default=1, ge=1, le=64)


class LvdsDataQueryModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str = Field(default='lvds:demo')
    signal: str
    limit: int = 2000
