"""解释器注册表：parser_id → 解析/落库封装。未注册 / 未绑定则不解析。"""

from __future__ import annotations

from typing import Any

from module_payload.constants import (
    PARSER_TM_CAN_BIU,
    PARSER_TM_CAN_XL,
    PARSER_TM_CAN_YJ216,
    PARSER_TM_XL_CPAZX,
    PARSER_TM_XL_BOARD,
    PARSER_TM_XL_CAMERA,
    PARSER_TM_XL_CAMERA_V17,
)
from module_payload.parsers.biu_can_tm import BiuCanTmIngest
from module_payload.parsers.xl_cpazx_tm import XlCpazxTmIngest
from module_payload.parsers.xl_board_tm import XlBoardTmIngest
from module_payload.parsers.xl_camera_tm import XlCameraTmIngest
from module_payload.parsers.xl_camera_tm_v17 import XlCameraTmV17Ingest
from module_payload.parsers.xl_can_tm import XlCanTmIngest
from module_payload.parsers.yj216_can_tm import Yj216CanTmIngest
from module_payload.protocol_catalog import list_parser_items

# parser_id -> 封装类（含 parse / store / ingest）
PARSER_REGISTRY: dict[str, Any] = {
    PARSER_TM_CAN_BIU: BiuCanTmIngest,
    PARSER_TM_CAN_XL: XlCanTmIngest,
    PARSER_TM_CAN_YJ216: Yj216CanTmIngest,
    PARSER_TM_XL_CAMERA: XlCameraTmIngest,
    PARSER_TM_XL_CAMERA_V17: XlCameraTmV17Ingest,
    PARSER_TM_XL_BOARD: XlBoardTmIngest,
    PARSER_TM_XL_CPAZX: XlCpazxTmIngest,
}


def resolve_parser(parser_id: str | None) -> Any | None:
    """按 parser_id 取 ingest 类；空或未注册返回 None。"""
    if not parser_id:
        return None
    return PARSER_REGISTRY.get(parser_id)


def list_parsers() -> list[dict[str, str]]:
    """前端绑定解释器用的 id/name/dataKind 列表。"""
    return list_parser_items()
