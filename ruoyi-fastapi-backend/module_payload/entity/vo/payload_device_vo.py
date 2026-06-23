from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CanOpenModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    vendor: int = Field(default=0, description='CAN厂家 0=DEMO')
    dev_index: int = Field(default=0)
    can_index: int = Field(default=0)
    baud_rate: int = Field(default=500)
    node_addr_to: int = Field(default=0x0D)
    cable_flag: int = Field(default=0)


class SerialOpenModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    port: str
    baudrate: int = Field(default=2_000_000)
    mode: str = Field(default='camera', description='camera|raw')


class DeviceStatusQueryModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
