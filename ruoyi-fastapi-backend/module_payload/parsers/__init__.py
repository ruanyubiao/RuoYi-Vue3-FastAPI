"""解释器注册表：parser_id → 解析/落库封装。未注册 / 未绑定则不解析。"""

from __future__ import annotations

from typing import Any

from module_payload.constants import PARSER_TM_CAN_YC
from module_payload.parsers.tm_can_yc_ingest import TmCanYcIngest

# parser_id -> 封装类（含 parse / store / ingest）
PARSER_REGISTRY: dict[str, Any] = {
    PARSER_TM_CAN_YC: TmCanYcIngest,
}


def resolve_parser(parser_id: str | None) -> Any | None:
    if not parser_id:
        return None
    return PARSER_REGISTRY.get(parser_id)


def list_parsers() -> list[dict[str, str]]:
    return [
        {
            'id': PARSER_TM_CAN_YC,
            'name': 'CAN遥测复合帧',
            'dataKind': 'tm',
        },
    ]
