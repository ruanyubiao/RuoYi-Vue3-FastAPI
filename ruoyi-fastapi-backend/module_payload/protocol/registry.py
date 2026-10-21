"""协议注册表：按 ``protocol_catalog`` 的模块路径加载各协议的 ``BINDINGS``。

采集、发送、文件回放、遥控组帧都经这里查找，本文件不写总线族名。
新增协议只在目录表加一行，并在协议模块里导出 ``BINDINGS``。
目录表在调用时读取，不在导入时拍快照。
"""

from __future__ import annotations

import importlib
from functools import cache
from typing import TYPE_CHECKING, Any

from module_payload.constants import ASSEMBLER_PASSTHROUGH, SRC_KIND_CAN
from module_payload.protocol import protocol_catalog as catalog
from module_payload.protocol.base import AssembledPayload, BaseAssembler
from module_payload.protocol.can_feed import can_feed_class
from module_payload.protocol.hooks import FilePlaySpec, ProtocolBindings

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_TIMED_TM_INTERVAL_S = 1.0  # 协议没给 timed_tm 时的定时遥测间隔

__all__ = [
    'CAMERA_IMAGE_ASSEMBLER_IDS',
    'DEFAULT_TIMED_TM_INTERVAL_S',
    'AssembledPayload',
    'BaseAssembler',
    'build_can_command',
    'bus_bindings',
    'create_assembler',
    'fileplay_tables',
    'list_assemblers',
    'list_parsers',
    'load_bindings',
    'normalize_assembler_id',
    'reset_tm_caches',
    'resolve_assembler_cls',
    'resolve_node_addr',
    'resolve_parser',
    'resolve_telecontrol',
    'timed_tm_request',
    'validate_assembler_for_src',
]


@cache
def load_bindings(module: str) -> ProtocolBindings:
    """导入协议模块并取 ``BINDINGS``；模块没导出时抛 ValueError。"""
    bindings = getattr(importlib.import_module(module), 'BINDINGS', None)
    if not isinstance(bindings, ProtocolBindings):
        raise ValueError(f'协议模块未导出 BINDINGS: {module}')
    return bindings


def _plugin(role: str, plugin_id: str) -> catalog.Plugin | None:
    return next((row for row in catalog.PLUGINS if row.role == role and row.id == plugin_id), None)


def _ingest_modules() -> list[str]:
    """所有带解释器的模块：各总线族 + 解释器插件。"""
    modules = [row.module for row in catalog.CAN_BUS_FAMILIES]
    modules.extend(row.module for row in catalog.PLUGINS if row.role == 'parser')
    return modules


# ---------------------------------------------------------------------------
# 组装器
# ---------------------------------------------------------------------------

# 产出图像的组装器 id（目录表 data_kind=image）
CAMERA_IMAGE_ASSEMBLER_IDS = frozenset(
    row.id for row in catalog.PLUGINS if row.role == 'assembler' and row.data_kind == 'image'
)


@cache
def _can_feed_cls(family: str, assembler_id: str, gpcan_protocol: str) -> type[BaseAssembler]:
    return can_feed_class(family, assembler_id, gpcan_protocol)


def normalize_assembler_id(assembler_id: str | None) -> str:
    """空 id 归一成透传。"""
    aid = (assembler_id or '').strip()
    return aid or ASSEMBLER_PASSTHROUGH


def resolve_assembler_cls(assembler_id: str | None) -> type[BaseAssembler] | None:
    """按 id 取组装器类；未知返回 None。"""
    aid = normalize_assembler_id(assembler_id)
    row = catalog.bus_family_by_assembler(aid)
    if row is not None:
        cls = load_bindings(row.module).assembler_cls
        return cls or _can_feed_cls(row.family, row.assembler_id, row.gpcan_protocol)
    plugin = _plugin('assembler', aid)
    if plugin is None:
        return None
    return load_bindings(plugin.module).assembler_cls


def create_assembler(assembler_id: str | None = None) -> BaseAssembler:
    """实例化组装器；未知 id 抛 ValueError。"""
    cls = resolve_assembler_cls(assembler_id)
    if cls is None:
        raise ValueError(f'未知组装器: {assembler_id}')
    return cls()


def validate_assembler_for_src(assembler_id: str | None, src_kind: str | None = None) -> str:
    """校验组装器与连接类型是否匹配；返回归一化 id。"""
    aid = normalize_assembler_id(assembler_id)
    if resolve_assembler_cls(aid) is None:
        raise ValueError(f'未知组装器: {assembler_id}')
    kind = (src_kind or '').strip().lower()
    can_only = catalog.bus_family_by_assembler(aid) is not None
    if can_only and kind and kind != SRC_KIND_CAN:
        raise ValueError(f'{aid} 仅可用于 CAN 连接')
    if kind == SRC_KIND_CAN and not can_only and aid != ASSEMBLER_PASSTHROUGH:
        raise ValueError(catalog.can_only_assembler_message())
    return aid


def list_assemblers(*, src_kind: str | None = None) -> list[dict[str, str]]:
    """列出组装器。can：透传加各总线族；其它连接只要非总线组装器。"""
    return catalog.list_assembler_items(src_kind)


# ---------------------------------------------------------------------------
# 解释器
# ---------------------------------------------------------------------------


def resolve_parser(parser_id: str | None) -> Any | None:
    """按 parser_id 取 ingest 类；空或未登记返回 None。"""
    if not parser_id:
        return None
    for row in catalog.CAN_BUS_FAMILIES:
        if row.parser_id == parser_id:
            return load_bindings(row.module).ingest
    plugin = _plugin('parser', parser_id)
    return load_bindings(plugin.module).ingest if plugin is not None else None


def list_parsers() -> list[dict[str, str]]:
    """前端绑定解释器用的 id/name/dataKind 列表。"""
    return catalog.list_parser_items()


def reset_cfg_derived(cfg_file: str) -> None:
    """配置文件 mtime 变了：只清读这个文件的协议的派生缓存，不动会话状态。"""
    for module in _ingest_modules():
        bindings = load_bindings(module)
        if bindings.reset_cfg_derived is not None and cfg_file in bindings.tm_cfg_files:
            bindings.reset_cfg_derived()


def reset_tm_caches(cfg_file: str | None = None) -> None:
    """清各解释器的遥测配置缓存。给了文件名就只清读这个文件的解释器。"""
    for module in _ingest_modules():
        bindings = load_bindings(module)
        if bindings.reset_tm is None:
            continue
        if cfg_file is None or cfg_file in bindings.tm_cfg_files:
            bindings.reset_tm()


def fileplay_tables() -> dict[str, FilePlaySpec]:
    """非总线表的文件回放规格：本地表键 → 规格。"""
    out: dict[str, FilePlaySpec] = {}
    for module in _ingest_modules():
        out.update(load_bindings(module).fileplay_tables)
    return out


# ---------------------------------------------------------------------------
# 遥控组帧
# ---------------------------------------------------------------------------


def resolve_telecontrol(protocol: str) -> Callable[..., dict[str, Any]]:
    """遥控封帧协议 id → 组帧函数 (order, values, **kwargs)；未知抛 ValueError。"""
    module = next(
        (row.module for row in catalog.CAN_BUS_FAMILIES if row.telecontrol_protocol == protocol),
        None,
    )
    if module is None:
        module = next((row.module for row in catalog.TELECONTROL_PLUGINS if row.protocol == protocol), None)
    assemble = load_bindings(module).assemble if module else None
    if assemble is None:
        raise ValueError(f'未知遥控封帧协议: {protocol}')
    return assemble


# ---------------------------------------------------------------------------
# 总线族：CAN 发送、定时遥测、线缆地址
# ---------------------------------------------------------------------------


def bus_bindings(family: str | None) -> ProtocolBindings:
    """总线族 → 钩子。空或未知族抛 ValueError。"""
    return load_bindings(catalog.require_bus_family(family).module)


def _bus_bindings_for_assembler(assembler_id: str | None) -> ProtocolBindings | None:
    row = catalog.bus_family_by_assembler(assembler_id)
    return load_bindings(row.module) if row is not None else None


def build_can_command(assembler_id: str | None, builder: Any, raw: bytes, *, broadcast: bool) -> Any:
    """业务指令组 CAN 帧。协议没给 build_can_command 时用 gpcan 的普通遥控 / 广播。"""
    bindings = _bus_bindings_for_assembler(assembler_id)
    hook = bindings.build_can_command if bindings is not None else None
    if hook is not None:
        return hook(builder, raw, broadcast=broadcast)
    if broadcast:
        return builder.build_broadcast(raw)
    return builder.build_telecommand(raw)


def timed_tm_request(family: str | None, tick: int) -> tuple[float, dict[str, Any]]:
    """第 tick 次定时遥测：(间隔秒, build_telemetry_request 参数)。"""
    hook = bus_bindings(family).timed_tm
    if hook is None:
        return DEFAULT_TIMED_TM_INTERVAL_S, {}
    return hook(tick)


def resolve_node_addr(assembler_id: str | None, requested: Any) -> Any:
    """线缆目标地址。协议给了 node_addr 就用它的，否则原样返回请求值。"""
    bindings = _bus_bindings_for_assembler(assembler_id)
    if bindings is None or bindings.node_addr is None:
        return requested
    return bindings.node_addr(requested)
