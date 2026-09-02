"""SC-LINK41EP V1.7 串口遥测解释器：慢遥 0xD8、快遥 0xD9。

帧拆分与 ingest 在 CameraTmIngestBase；本模块绑定 V1.7 配置与表键 D8V17/D9V17。
线上帧类型仍为 0xD8/0xD9。
"""

from __future__ import annotations

from typing import Any

from module_payload.cfg.payload_config_loader import CAMERA_V17_TELE_METRY_CFG_NAME, PayloadConfigLoader
from module_payload.constants import PARSER_TM_XL_CAMERA_V17
from module_payload.parsers.camera_tm_ingest_base import (
    D8_DATA_LEN,
    D8_FRAME_MIN,
    D9_DATA_LEN,
    D9_EXTENDED_DATA_LEN,
    D9_FRAME_LEN,
    FRAME_D9_HEADER,
    FRAME_HEADER,
    FRAME_TYPE_D8,
    FRAME_TYPE_D9,
    CameraTmIngestBase,
    ParsedXlCameraTm,
    _calc_checksum,
)
from module_payload.parsers.tm_mgr_cache import TmMgrFileCache

CFG_TABLE_D8 = 'D8V17'
CFG_TABLE_D9 = 'D9V17'

__all__ = [
    'CFG_TABLE_D8',
    'CFG_TABLE_D9',
    'D8_DATA_LEN',
    'D8_FRAME_MIN',
    'D9_DATA_LEN',
    'D9_EXTENDED_DATA_LEN',
    'D9_FRAME_LEN',
    'FRAME_D9_HEADER',
    'FRAME_HEADER',
    'FRAME_TYPE_D8',
    'FRAME_TYPE_D9',
    'ParsedXlCameraTm',
    'XlCameraTmV17Ingest',
    '_calc_checksum',
    'reset_xl_camera_tm_v17_mgr',
]


class XlCameraTmV17Ingest(CameraTmIngestBase):
    """V1.7：XL-Camera-V17-TeleMetryCfg.json，表键 D8V17 / D9V17。"""

    PARSER_ID = PARSER_TM_XL_CAMERA_V17
    TABLE_D8 = CFG_TABLE_D8
    TABLE_D9 = CFG_TABLE_D9
    _tm_file_cache = TmMgrFileCache()
    _table_names: dict[str, str] = {}
    _d9_mux_cache: dict[str, dict[int, bytes]] = {}

    @classmethod
    def _cfg_file_name(cls) -> str:
        return CAMERA_V17_TELE_METRY_CFG_NAME

    @classmethod
    def _load_telemetry_cfg(cls, *, reload: bool = False) -> dict[str, Any]:
        return PayloadConfigLoader.get_camera_v17_telemetry_cfg(reload=reload)


def reset_xl_camera_tm_v17_mgr() -> None:
    """清空 V1.7 相机遥测 TeleMetryCfgManager、表名缓存，以及 D9 mux last-known。"""
    XlCameraTmV17Ingest.reset_mgr()
