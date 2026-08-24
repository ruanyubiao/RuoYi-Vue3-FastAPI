from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class SerialOpenModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    port: str
    baudrate: int = Field(default=2_000_000)
    data_bits: int = Field(default=8, description='数据位(5/6/7/8)')
    stop_bits: float = Field(default=1, description='停止位(1/1.5/2)')
    parity: str = Field(default='N', description='校验位 N/E/O/M/S')
    flow_control: str = Field(default='none', description='流控制 none/xonxoff/rtscts/dsrdtr')
    parser_id: str | None = Field(default=None, description='打开时绑定的解释器；默认不绑定')
    assembler_id: str | None = Field(default='passthrough', description='打开时绑定的组装器；默认透传')
    routes: list[dict] | None = Field(
        default=None,
        description='可选混流分流路由表；非空时 ingest 按路由拆帧喂多组装器',
    )
    source: str | None = Field(
        default=None,
        description='连接来源页标识，如 home / camera_ctrl / camera_image',
    )
    full_duplex: bool | None = Field(
        default=None,
        description='全双工时采集进程收发分线程；默认按连接配置，缺省半双工',
    )


class CanOpenModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    vendor: int = Field(default=3, description='CAN厂家，默认 ZLG')
    dev_index: int = Field(default=0)
    can_index: int = Field(default=0)
    baud_rate: int = Field(default=500)
    node_addr_to: int = Field(default=0x0D)
    cable_flag: int | None = Field(
        default=None, description='线缆 0=A / 1=B；首页新建不传（None）'
    )
    parser_id: str | None = Field(
        default='tm_can_biu', description='打开时绑定的解释器；默认 BIU-CAN 遥测复合帧'
    )
    assembler_id: str | None = Field(
        default='can_biu',
        description='打开时绑定的组装器；CAN 仅支持 can_biu / can_xl，默认 CAN-BIU',
    )
    routes: list[dict] | None = Field(
        default=None,
        description='可选混流分流路由表',
    )
    source: str | None = Field(default='home', description='连接来源页标识')
    full_duplex: bool | None = Field(
        default=None,
        description='全双工时采集进程收发分线程；CAN 默认半双工',
    )


class CanCableUpdateModel(BaseModel):
    """热更新已打开 CAN 通道的业务线缆参数。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    device_id: str | None = Field(default=None, description='通道 id，如 can:3:0:0；与 vendor/dev/can 二选一')
    vendor: int | None = None
    dev_index: int | None = None
    can_index: int | None = None
    node_addr_to: int | None = Field(default=None, description='目标地址，如 0x0D / 0x0C')
    cable_flag: int | None = Field(default=None, description='线缆 0=A / 1=B')


class NetOpenModel(BaseModel):
    """UDP/网络连接：绑定本机地址与端口。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    proto: str = Field(default='udp', description='协议，首版仅 udp')
    local_host: str = Field(default='0.0.0.0', description='本机绑定地址')
    local_port: int = Field(description='本机绑定端口')
    remote_host: str | None = Field(default=None, description='默认远程主机（可选）')
    remote_port: int | None = Field(default=None, description='默认远程端口（可选）')
    parser_id: str | None = Field(default=None, description='打开时绑定的解释器；默认不绑定')
    assembler_id: str | None = Field(default='passthrough', description='打开时绑定的组装器；默认透传')
    routes: list[dict] | None = Field(
        default=None,
        description='可选混流分流路由表（如工程遥测 + 其它帧）',
    )
    source: str | None = Field(default='home', description='连接来源页标识')
    full_duplex: bool | None = Field(
        default=None,
        description='全双工时采集进程收发分线程；网口默认半双工',
    )


class DeviceBindParserModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    src_param: str = Field(description='来源参数，如 can:0:0:0 / serial:COM3')
    src_kind: str | None = Field(default=None, description='来源类型，可省略由 srcParam 推断')
    parser_id: str | None = Field(default=None, description='解释器ID；空或不传表示解绑')
    assembler_id: str | None = Field(default=None, description='组装器ID；与 updateAssembler 配合')
    update_assembler: bool = Field(
        default=True,
        description='是否同时更新组装器；首页修改弹窗传 true',
    )
    routes: list[dict] | None = Field(
        default=None,
        description='混流路由表；传数组则写入（空数组清除，走单组装器）',
    )
    update_routes: bool = Field(
        default=False,
        description='是否更新 routes；为 true 或 routes 非 None 时写入',
    )
    source: str | None = Field(
        default=None,
        description='可选：同时更新连接来源页标识',
    )


class DeviceStatusQueryModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
