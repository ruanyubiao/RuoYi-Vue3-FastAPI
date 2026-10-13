"""总线族与非总线插件清单。

加一套 CAN 总线只在 ``BUS_FAMILIES`` 加一行。列表、报错文案、配置文件名从这里过滤，
不在各函数里写死族名。解释器类和组装器类仍在各自注册表里按 id 绑定。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BusFamily:
    """一条 CAN 总线族。字段都是字符串。"""

    family: str
    storage_prefix: str
    assembler_id: str
    assembler_name: str
    assembler_desc: str
    parser_id: str
    parser_name: str
    telecontrol_cfg: str
    telemetry_cfg: str
    gpcan_protocol: str
    telecontrol_protocol: str


@dataclass(frozen=True)
class Plugin:
    """非总线组装器或解释器。``can_name`` 非空时，CAN 列表用这套文案。"""

    role: str
    id: str
    name: str
    desc: str = ''
    can_name: str = ''
    can_desc: str = ''
    data_kind: str = 'tm'


BUS_FAMILIES: tuple[BusFamily, ...] = (
    BusFamily(
        family='biu',
        storage_prefix='BIU',
        assembler_id='can_biu',
        assembler_name='CAN-BIU',
        assembler_desc='gpcan BIU 协议组帧（仅 CAN）',
        parser_id='tm_can_biu',
        parser_name='BIU-CAN遥测复合帧',
        telecontrol_cfg='BIU-TeleControlCfg.json',
        telemetry_cfg='BIU-TeleMetryCfg.json',
        gpcan_protocol='BIU',
        telecontrol_protocol='can_biu',
    ),
    BusFamily(
        family='xl',
        storage_prefix='XL',
        assembler_id='can_xl',
        assembler_name='CAN-XL',
        assembler_desc='gpcan XL 协议组帧（仅 CAN）',
        parser_id='tm_can_xl',
        parser_name='XL-CAN遥测复合帧',
        telecontrol_cfg='XL-TeleControlCfg.json',
        telemetry_cfg='XL-TeleMetryCfg.json',
        gpcan_protocol='XL',
        telecontrol_protocol='can_xl',
    ),
    BusFamily(
        family='yj216',
        storage_prefix='YJ216',
        assembler_id='can_yj216',
        assembler_name='CAN-YJ216',
        assembler_desc='gpcan YJ216 协议组帧（仅 CAN）',
        parser_id='tm_can_yj216',
        parser_name='YJ216-CAN实时遥测',
        telecontrol_cfg='YJ216-TeleControlCfg.json',
        telemetry_cfg='YJ216-TeleMetryCfg.json',
        gpcan_protocol='YJ216',
        telecontrol_protocol='can_yj216',
    ),
)

PLUGINS: tuple[Plugin, ...] = (
    Plugin(
        role='assembler',
        id='passthrough',
        name='透传（默认）',
        desc='每次收到的数据视为完整载荷',
        can_name='透传',
        can_desc='不做协议组帧；CanProtocolClient 协议类型 NONE（便于 CAN 裸测）',
    ),
    Plugin(
        role='assembler',
        id='eng_tm_subpkt',
        name='工程遥测子包(LVDS)',
        desc='表格4 0x1BCF 子包拼装（子包数目=总包数）；单绑定时内置定头定长定尾拆帧，demux 路径用 accept_frame',
    ),
    Plugin(
        role='assembler',
        id='camera_image_d6',
        name='相机图像(D6)',
        desc='接收完整 D6 应答帧按序号拼图（粘包拆帧由 camera_image 插件完成）',
    ),
    Plugin(
        role='assembler',
        id='camera_image_d6_v17',
        name='相机图像(D6 V1.7)',
        desc='V1.7 D6 应答：按有效长度字段截取像素后拼图',
    ),
    Plugin(role='parser', id='tm_xl_camera', name='XL相机遥测帧'),
    Plugin(role='parser', id='tm_xl_camera_v17', name='XL相机V1.7遥测帧'),
    Plugin(role='parser', id='tm_xl_board', name='XL单板遥测'),
    Plugin(role='parser', id='tm_xl_cpazx', name='XL CPA指向遥测'),
)


def require_bus_family(key: str | None) -> BusFamily:
    """按 family 取行。空或未知抛 ValueError。"""
    text = (key or '').strip().lower()
    if not text:
        raise ValueError('未指定总线族')
    for row in BUS_FAMILIES:
        if row.family == text:
            return row
    raise ValueError(f'未知总线族: {key}')


def bus_family_by_assembler(assembler_id: str | None) -> BusFamily | None:
    """组装器 id → 总线族；透传和其它插件返回 None。"""
    aid = (assembler_id or '').strip()
    for row in BUS_FAMILIES:
        if row.assembler_id == aid:
            return row
    return None


def is_bus_family(key: str | None) -> bool:
    """是否已登记的总线族。空或未知返回 False，不抛错。"""
    text = (key or '').strip().lower()
    return any(row.family == text for row in BUS_FAMILIES)


def is_can_assembler(assembler_id: str | None) -> bool:
    """CAN 连接允许的组装器：各总线族，或带 CAN 文案的插件（透传）。"""
    aid = (assembler_id or '').strip()
    if bus_family_by_assembler(aid) is not None:
        return True
    return any(row.role == 'assembler' and row.id == aid and row.can_name for row in PLUGINS)


def bus_family_by_telemetry_cfg(filename: str) -> BusFamily | None:
    """遥测配置文件名 → 总线族。"""
    name = Path(filename or '').name
    for row in BUS_FAMILIES:
        if row.telemetry_cfg == name:
            return row
    return None


def family_from_cfg_name(filename: str) -> str:
    """文件名第一段转小写，必须是已登记的总线族。``XL-Camera-*.json`` → ``xl``。"""
    head = Path(filename or '').name.split('-', 1)[0].strip().lower()
    return require_bus_family(head).family


def _assembler_plugins() -> list[Plugin]:
    return [row for row in PLUGINS if row.role == 'assembler']


def _bus_assembler_item(row: BusFamily) -> dict[str, str]:
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
        return head + [_bus_assembler_item(row) for row in BUS_FAMILIES]
    general = [{'id': row.id, 'name': row.name, 'desc': row.desc} for row in plugins]
    if kind:
        return general
    return general + [_bus_assembler_item(row) for row in BUS_FAMILIES]


def list_parser_items() -> list[dict[str, str]]:
    """解释器下拉：总线族在前，其余插件在后。"""
    items = [{'id': row.parser_id, 'name': row.parser_name, 'dataKind': 'tm'} for row in BUS_FAMILIES]
    items.extend(
        {'id': row.id, 'name': row.name, 'dataKind': row.data_kind} for row in PLUGINS if row.role == 'parser'
    )
    return items


def can_only_assembler_message() -> str:
    """CAN 连接允许的组装器名称，由清单拼出。"""
    names = [item['name'] for item in list_assembler_items('can')]
    return 'CAN 连接仅支持 ' + ' / '.join(names)


def _row_attr(family: str, attr: str) -> str:
    return getattr(require_bus_family(family), attr)


ASSEMBLER_PASSTHROUGH = next(row.id for row in PLUGINS if row.id == 'passthrough')
ASSEMBLER_ENG_TM_SUBPKT = next(row.id for row in PLUGINS if row.id == 'eng_tm_subpkt')
ASSEMBLER_CAMERA_IMAGE_D6 = next(row.id for row in PLUGINS if row.id == 'camera_image_d6')
ASSEMBLER_CAMERA_IMAGE_D6_V17 = next(row.id for row in PLUGINS if row.id == 'camera_image_d6_v17')
ASSEMBLER_CAN_BIU = _row_attr('biu', 'assembler_id')
ASSEMBLER_CAN_XL = _row_attr('xl', 'assembler_id')
ASSEMBLER_CAN_YJ216 = _row_attr('yj216', 'assembler_id')

PARSER_TM_CAN_BIU = _row_attr('biu', 'parser_id')
PARSER_TM_CAN_XL = _row_attr('xl', 'parser_id')
PARSER_TM_CAN_YJ216 = _row_attr('yj216', 'parser_id')
PARSER_TM_XL_CAMERA = next(row.id for row in PLUGINS if row.id == 'tm_xl_camera')
PARSER_TM_XL_CAMERA_V17 = next(row.id for row in PLUGINS if row.id == 'tm_xl_camera_v17')
PARSER_TM_XL_BOARD = next(row.id for row in PLUGINS if row.id == 'tm_xl_board')
PARSER_TM_XL_CPAZX = next(row.id for row in PLUGINS if row.id == 'tm_xl_cpazx')
