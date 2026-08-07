"""解释器注册表：parser_id → 解析/落库封装。未注册 / 未绑定则不解析。"""

from __future__ import annotations

from typing import Any

from module_payload.constants import (
    PARSER_CAMERA_SC_LINK41EP,
    PARSER_TM_CAN_BIU,
    PARSER_TM_CAN_XL,
    PARSER_XL_BOARD_TM,
)
from module_payload.parsers.camera_sc_link41ep import CameraScLink41epIngest
from module_payload.parsers.tm_can_yc_ingest import TmCanYcIngest
from module_payload.parsers.xl_board_tm import XlBoardTmIngest
from module_payload.parsers.xl_can_tm import XlCanTmIngest

# parser_id -> 封装类（含 parse / store / ingest）
PARSER_REGISTRY: dict[str, Any] = {
    PARSER_TM_CAN_BIU: TmCanYcIngest,
    PARSER_TM_CAN_XL: XlCanTmIngest,
    PARSER_CAMERA_SC_LINK41EP: CameraScLink41epIngest,
    PARSER_XL_BOARD_TM: XlBoardTmIngest,
}


def resolve_parser(parser_id: str | None) -> Any | None:
    if not parser_id:
        return None
    return PARSER_REGISTRY.get(parser_id)


def list_parsers() -> list[dict[str, str]]:
    return [
        {
            'id': PARSER_TM_CAN_BIU,
            'name': 'BIU-CAN遥测复合帧',
            'dataKind': 'tm',
        },
        {
            'id': PARSER_TM_CAN_XL,
            'name': 'XL-CAN遥测复合帧',
            'dataKind': 'tm',
        },
        {
            'id': PARSER_CAMERA_SC_LINK41EP,
            'name': '相机SC-LINK41EP(D8)',
            'dataKind': 'tm',
        },
        {
            'id': PARSER_XL_BOARD_TM,
            'name': 'XL单板遥测',
            'dataKind': 'tm',
        },
    ]
