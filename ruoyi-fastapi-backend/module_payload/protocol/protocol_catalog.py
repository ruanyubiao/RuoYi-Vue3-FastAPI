"""CAN 总线族、帧插件与遥控配置清单。

加一套 CAN 总线只在 ``CAN_BUS_FAMILIES`` 加一行族名，再写 ``module_payload.protocol.<族>.can`` 协议包。
列表、报错文案、配置文件名从这里过滤，不在各函数里写死族名。
``module`` 是协议模块路径；``protocol.registry`` 按它加载 ``BINDINGS``，这里不放类对象。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from utils.path_util import windows_basename


@dataclass(frozen=True)
class CanBusFamily:
    """一条 CAN 总线。只登记小写族名；id、配置文件名、gpcan 协议名、协议包路径都由族名推出。"""

    family: str
    parser_name: str = ''  # 解释器显示名；空则为「{族名大写}-CAN遥测复合帧」

    def __post_init__(self) -> None:
        if not self.parser_name:
            object.__setattr__(self, 'parser_name', f'{self.storage_prefix}-CAN遥测复合帧')

    @property
    def storage_prefix(self) -> str:
        """遥测存储键前缀，如 ``YJ216:FF`` 的 ``YJ216``。"""
        return self.family.upper()

    @property
    def gpcan_protocol(self) -> str:
        """gpcan ``CanProtocolType`` 成员名。"""
        return self.family.upper()

    @property
    def assembler_id(self) -> str:
        return f'can_{self.family}'

    @property
    def assembler_name(self) -> str:
        return f'CAN-{self.storage_prefix}'

    @property
    def assembler_desc(self) -> str:
        return f'gpcan {self.gpcan_protocol} 协议组帧（仅 CAN）'

    @property
    def parser_id(self) -> str:
        return f'tm_can_{self.family}'

    @property
    def telecontrol_cfg(self) -> str:
        return f'{self.storage_prefix}-TeleControlCfg.json'

    @property
    def telemetry_cfg(self) -> str:
        return f'{self.storage_prefix}-TeleMetryCfg.json'

    @property
    def telecontrol_protocol(self) -> str:
        """遥控封帧协议 id，与组装器 id 相同。"""
        return self.assembler_id

    @property
    def module(self) -> str:
        return f'module_payload.protocol.{self.family}.can'


@dataclass(frozen=True)
class Plugin:
    """非总线组装器或解释器。``can_name`` 非空时，CAN 列表用这套文案。"""

    role: str
    id: str
    name: str
    desc: str = ''
    can_name: str = ''
    can_desc: str = ''
    data_kind: str = 'tm'  # 组装器写 image 表示产出图像
    module: str = ''


@dataclass(frozen=True)
class TelecontrolPlugin:
    """非总线的遥控配置（单板、相机）：一份 JSON 对应一种封帧协议。

    文件名 ``<族>-<单板>-TeleControlCfg.json``；遥测配置是同词干的 ``-TeleMetryCfg.json``，遥测表键为单板名大写。
    """

    cfg_file: str
    protocol: str
    module: str


@dataclass(frozen=True)
class SerialStreamPluginSpec:
    """串口采集插件。哪个 source 挂上它写在连接预设的 pluginId，不写在这里。"""

    id: str
    module: str
    read_timeout: float = 0.1


CAN_BUS_FAMILIES: tuple[CanBusFamily, ...] = (
    CanBusFamily(family='biu'),
    CanBusFamily(family='xl'),
    CanBusFamily(family='yj216', parser_name='YJ216-CAN实时遥测'),
)

DEFAULT_BUS_FAMILY = 'biu'  # 会话未指定 CAN 组装器、定时操作未指定族时用它

PLUGINS: tuple[Plugin, ...] = (
    Plugin(
        role='assembler',
        id='passthrough',
        name='透传（默认）',
        desc='每次收到的数据视为完整载荷',
        can_name='透传',
        can_desc='不做协议组帧；CanProtocolClient 协议类型 NONE（便于 CAN 裸测）',
        module='module_payload.protocol.passthrough',
    ),
    Plugin(
        role='assembler',
        id='eng_tm_subpkt',
        name='工程遥测子包(LVDS)',
        desc='表格4 0x1BCF 子包拼装（子包数目=总包数）；单绑定时内置定头定长定尾拆帧，demux 路径用 accept_frame',
        module='module_payload.protocol.xl.eng',
    ),
    Plugin(
        role='assembler',
        id='camera_image_d6',
        name='相机图像(D6)',
        desc='接收完整 D6 应答帧按序号拼图（粘包拆帧由 camera_image 插件完成）',
        data_kind='image',
        module='module_payload.protocol.xl.camera.image_d6',
    ),
    Plugin(
        role='assembler',
        id='camera_image_d6_v17',
        name='相机图像(D6 V1.7)',
        desc='V1.7 D6 应答：按有效长度字段截取像素后拼图',
        data_kind='image',
        module='module_payload.protocol.xl.camera_v17.image_d6',
    ),
    Plugin(role='parser', id='tm_xl_camera', name='XL相机遥测帧', module='module_payload.protocol.xl.camera.tm'),
    Plugin(
        role='parser',
        id='tm_xl_camera_v17',
        name='XL相机V1.7遥测帧',
        module='module_payload.protocol.xl.camera_v17.tm',
    ),
    Plugin(role='parser', id='tm_xl_board', name='XL单板遥测', module='module_payload.protocol.xl.board.tm'),
    Plugin(role='parser', id='tm_xl_cpazx', name='XL CPA指向遥测', module='module_payload.protocol.xl.cpazx.tm'),
    Plugin(role='parser', id='tm_yj216_rs422', name='YJ216 RS422遥测', module='module_payload.protocol.yj216.rs422.tm'),
)

TELECONTROL_PLUGINS: tuple[TelecontrolPlugin, ...] = (
    TelecontrolPlugin(
        cfg_file='XL-RKDJ-TeleControlCfg.json',
        protocol='xl_board',
        module='module_payload.protocol.xl.board.tc',
    ),
    TelecontrolPlugin(
        cfg_file='XL-ZK-TeleControlCfg.json',
        protocol='xl_board',
        module='module_payload.protocol.xl.board.tc',
    ),
    TelecontrolPlugin(
        cfg_file='XL-DJ-TeleControlCfg.json',
        protocol='xl_board',
        module='module_payload.protocol.xl.board.tc',
    ),
    TelecontrolPlugin(
        cfg_file='XL-CPAZX-TeleControlCfg.json',
        protocol='xl_cpazx',
        module='module_payload.protocol.xl.cpazx.tc',
    ),
    TelecontrolPlugin(
        cfg_file='XL-Camera-TeleControlCfg.json',
        protocol='camera',
        module='module_payload.protocol.xl.camera.tc',
    ),
    TelecontrolPlugin(
        cfg_file='XL-Camera-V17-TeleControlCfg.json',
        protocol='camera_v17',
        module='module_payload.protocol.xl.camera_v17.tc',
    ),
    TelecontrolPlugin(
        cfg_file='YJ216-RS422-TeleControlCfg.json',
        protocol='yj216_rs422',
        module='module_payload.protocol.yj216.rs422.tc',
    ),
)

SERIAL_STREAM_PLUGINS: tuple[SerialStreamPluginSpec, ...] = (
    SerialStreamPluginSpec(
        id='camera_image',
        module='module_payload.collectors.plugins.camera_image',
        read_timeout=0.02,
    ),
)


def serial_stream_plugin(plugin_id: str | None) -> SerialStreamPluginSpec | None:
    """按插件 id 取采集插件行。空或未知返回 None。"""
    pid = (plugin_id or '').strip()
    if not pid:
        return None
    for row in SERIAL_STREAM_PLUGINS:
        if row.id == pid:
            return row
    return None


def bus_family_names() -> tuple[str, ...]:
    """已登记总线族名，顺序与 ``CAN_BUS_FAMILIES`` 一致。"""
    return tuple(row.family for row in CAN_BUS_FAMILIES)


def require_bus_family(key: str | None) -> CanBusFamily:
    """按 family 取行。空或未知抛 ValueError。"""
    text = (key or '').strip().lower()
    if not text:
        raise ValueError('未指定总线族')
    for row in CAN_BUS_FAMILIES:
        if row.family == text:
            return row
    raise ValueError(f'未知总线族: {key}')


def bus_assembler_id(family: str | None) -> str:
    """总线族 → 组装器 id。空或未知抛 ValueError。"""
    return require_bus_family(family).assembler_id


def bus_parser_id(family: str | None) -> str:
    """总线族 → 解释器 id。空或未知抛 ValueError。"""
    return require_bus_family(family).parser_id


def bus_family_by_assembler(assembler_id: str | None) -> CanBusFamily | None:
    """组装器 id → 总线族；透传和其它插件返回 None。"""
    aid = (assembler_id or '').strip()
    for row in CAN_BUS_FAMILIES:
        if row.assembler_id == aid:
            return row
    return None


def is_bus_family(key: str | None) -> bool:
    """是否已登记的总线族。空或未知返回 False，不抛错。"""
    text = (key or '').strip().lower()
    return any(row.family == text for row in CAN_BUS_FAMILIES)


def is_can_assembler(assembler_id: str | None) -> bool:
    """CAN 连接允许的组装器：各总线族，或带 CAN 文案的插件（透传）。"""
    aid = (assembler_id or '').strip()
    if bus_family_by_assembler(aid) is not None:
        return True
    return any(row.role == 'assembler' and row.id == aid and row.can_name for row in PLUGINS)


def bus_family_by_telemetry_cfg(filename: str) -> CanBusFamily | None:
    """遥测配置文件名 → 总线族。"""
    name = Path(filename or '').name
    name = windows_basename(name)  # 非 Windows 上兼容反斜杠路径
    for row in CAN_BUS_FAMILIES:
        if row.telemetry_cfg == name:
            return row
    return None


def family_from_cfg_name(filename: str) -> str:
    """文件名第一段转小写，必须是已登记的总线族。``XL-Camera-*.json`` → ``xl``。"""
    head = windows_basename(Path(filename or '').name).split('-', 1)[0].strip().lower()
    return require_bus_family(head).family


def _assembler_plugins() -> list[Plugin]:
    return [row for row in PLUGINS if row.role == 'assembler']


def _bus_assembler_item(row: CanBusFamily) -> dict[str, str]:
    return {
        'id': row.assembler_id,
        'name': row.assembler_name,
        'desc': row.assembler_desc,
        'srcKind': 'can',
    }


def list_assembler_items(src_kind: str | None = None) -> list[dict[str, str]]:
    """组装器下拉。can：透传 + 各总线族；其它连接：非总线组装器；空：两者都要。"""
    kind = (src_kind or '').strip().lower()
    plugins = _assembler_plugins()
    if kind == 'can':
        head = [
            {'id': row.id, 'name': row.can_name, 'desc': row.can_desc, 'srcKind': 'can'}
            for row in plugins
            if row.can_name
        ]
        return head + [_bus_assembler_item(row) for row in CAN_BUS_FAMILIES]
    general = [{'id': row.id, 'name': row.name, 'desc': row.desc} for row in plugins]
    if kind:
        return general
    return general + [_bus_assembler_item(row) for row in CAN_BUS_FAMILIES]


def list_parser_items() -> list[dict[str, str]]:
    """解释器下拉：总线族在前，其余插件在后。"""
    items = [{'id': row.parser_id, 'name': row.parser_name, 'dataKind': 'tm'} for row in CAN_BUS_FAMILIES]
    items.extend(
        {'id': row.id, 'name': row.name, 'dataKind': row.data_kind} for row in PLUGINS if row.role == 'parser'
    )
    return items


def can_only_assembler_message() -> str:
    """CAN 连接允许的组装器名称，由清单拼出。"""
    names = [item['name'] for item in list_assembler_items('can')]
    return 'CAN 连接仅支持 ' + ' / '.join(names)


def _plugin_id(plugin_id: str) -> str:
    return next(row.id for row in PLUGINS if row.id == plugin_id)


ASSEMBLER_PASSTHROUGH = _plugin_id('passthrough')
ASSEMBLER_ENG_TM_SUBPKT = _plugin_id('eng_tm_subpkt')
ASSEMBLER_CAMERA_IMAGE_D6 = _plugin_id('camera_image_d6')
ASSEMBLER_CAMERA_IMAGE_D6_V17 = _plugin_id('camera_image_d6_v17')
DEFAULT_CAN_ASSEMBLER = bus_assembler_id(DEFAULT_BUS_FAMILY)

PARSER_TM_XL_CAMERA = _plugin_id('tm_xl_camera')
PARSER_TM_XL_CAMERA_V17 = _plugin_id('tm_xl_camera_v17')
PARSER_TM_XL_BOARD = _plugin_id('tm_xl_board')
PARSER_TM_XL_CPAZX = _plugin_id('tm_xl_cpazx')
PARSER_TM_YJ216_RS422 = _plugin_id('tm_yj216_rs422')
