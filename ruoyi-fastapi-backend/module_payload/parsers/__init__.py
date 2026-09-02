"""解释器注册表：parser_id → 解析/落库封装。未注册 / 未绑定则不解析。"""

from __future__ import annotations

from typing import Any

from module_payload.constants import (
    PARSER_TM_CAN_BIU,
    PARSER_TM_CAN_XL,
    PARSER_TM_XL_BOARD,
    PARSER_TM_XL_CAMERA,
    PARSER_TM_XL_CAMERA_V17,
)
from module_payload.parsers.biu_can_tm import BiuCanTmIngest
from module_payload.parsers.xl_board_tm import XlBoardTmIngest
from module_payload.parsers.xl_camera_tm import XlCameraTmIngest
from module_payload.parsers.xl_camera_tm_v17 import XlCameraTmV17Ingest
from module_payload.parsers.xl_can_tm import XlCanTmIngest

# parser_id -> 封装类（含 parse / store / ingest）
PARSER_REGISTRY: dict[str, Any] = {
    PARSER_TM_CAN_BIU: BiuCanTmIngest,
    PARSER_TM_CAN_XL: XlCanTmIngest,
    PARSER_TM_XL_CAMERA: XlCameraTmIngest,
    PARSER_TM_XL_CAMERA_V17: XlCameraTmV17Ingest,
    PARSER_TM_XL_BOARD: XlBoardTmIngest,
}


def resolve_parser(parser_id: str | None) -> Any | None:
    """按 parser_id 取 ingest 类；空或未注册返回 None。"""
    if not parser_id:
        return None
    return PARSER_REGISTRY.get(parser_id)


def list_parsers() -> list[dict[str, str]]:
    """前端绑定解释器用的 id/name/dataKind 列表。"""
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
            'id': PARSER_TM_XL_CAMERA,
            'name': 'XL相机遥测帧',
            'dataKind': 'tm',
        },
        {
            'id': PARSER_TM_XL_CAMERA_V17,
            'name': 'XL相机V1.7遥测帧',
            'dataKind': 'tm',
        },
        {
            'id': PARSER_TM_XL_BOARD,
            'name': 'XL单板遥测',
            'dataKind': 'tm',
        },
    ]
