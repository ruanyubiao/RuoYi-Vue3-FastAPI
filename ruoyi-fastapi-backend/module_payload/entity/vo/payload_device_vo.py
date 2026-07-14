from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CanOpenModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    vendor: int = Field(default=3, description='CAN厂家，默认 ZLG')
    dev_index: int = Field(default=0)
    can_index: int = Field(default=0)
    baud_rate: int = Field(default=500)
    node_addr_to: int = Field(default=0x0D)
    cable_flag: int = Field(default=0)
    parser_id: str | None = Field(
        default='tm_can_yc', description='打开时绑定的解释器；空字符串表示不绑定'
    )


class SerialOpenModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    port: str
    baudrate: int = Field(default=2_000_000)
    mode: str = Field(default='camera', description='camera|raw')
    data_bits: int = Field(default=8, description='数据位(5/6/7/8)')
    stop_bits: float = Field(default=1, description='停止位(1/1.5/2)')
    parity: str = Field(default='N', description='校验位 N/E/O/M/S')
    flow_control: str = Field(default='none', description='流控制 none/xonxoff/rtscts/dsrdtr')
    parser_id: str | None = Field(default=None, description='打开时绑定的解释器；默认不绑定')


class DeviceBindParserModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    src_param: str = Field(description='来源参数，如 can:0:0:0 / serial:COM3')
    src_kind: str | None = Field(default=None, description='来源类型，可省略由 srcParam 推断')
    parser_id: str | None = Field(default=None, description='解释器ID；空或不传表示解绑')


class DeviceStatusQueryModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
