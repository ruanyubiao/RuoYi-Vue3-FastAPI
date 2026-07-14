"""解释器注册表：parser_id → 解析类。未注册 / 未绑定则不解析。"""

from __future__ import annotations

from typing import Any, Callable

from module_payload.constants import PARSER_TM_CAN_YC

# parser_id -> callable 或类型（后续扩展具体 Parser 类）
PARSER_REGISTRY: dict[str, Any] = {
    PARSER_TM_CAN_YC: 'tm_can_yc',  # 占位：实际解析仍走 TeleMetryCfgManager
}


def resolve_parser(parser_id: str | None) -> Any | None:
    if not parser_id:
        return None
    return PARSER_REGISTRY.get(parser_id)


def list_parsers() -> list[dict[str, str]]:
    return [
        {'id': PARSER_TM_CAN_YC, 'name': 'CAN遥测复合帧(TeleMetryCfg)', 'dataKind': 'tm'},
    ]
