"""SC-LINK41EP V1.7 串口遥测解释器：慢遥 0xD8、快遥 0xD9。

帧拆分与 ingest 在 CameraTmIngestBase；本模块绑定 V1.7 配置与表键 D8V17/D9V17。
线上帧类型仍为 0xD8/0xD9。
"""

from __future__ import annotations

from typing import Any

from module_payload.cfg.payload_config_loader import PayloadConfigLoader
from module_payload.cfg.telecontrol_cfg import board_cfg_id, telemetry_cfg_for
from module_payload.constants import PARSER_TM_XL_CAMERA_V17
from module_payload.protocol.xl.camera.tm_base import (
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
from module_payload.protocol.hooks import FilePlaySpec, ProtocolBindings, method_extract
from module_payload.protocol.xl.camera.tm import XlCameraTmIngest
from module_payload.tm.tm_mgr_cache import TmMgrFileCache

CFG_TABLE_D8 = 'D8V17'
CFG_TABLE_D9 = 'D9V17'
CFG_FILE = telemetry_cfg_for(board_cfg_id('xl', 'camera-v17'))

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
        return CFG_FILE

    @classmethod
    def _load_telemetry_cfg(cls, *, reload: bool = False) -> dict[str, Any]:
        return PayloadConfigLoader.get_board_telemetry_cfg('xl', 'camera-v17', reload=reload)


def reset_xl_camera_tm_v17_mgr() -> None:
    """清空 V1.7 相机遥测 TeleMetryCfgManager、表名缓存，以及 D9 mux last-known。"""
    XlCameraTmV17Ingest.reset_mgr()


# 线上帧与 V1.6 相同，文件回放沿用 V1.6 的拆帧，只换字段配置
BINDINGS = ProtocolBindings(
    ingest=XlCameraTmV17Ingest,
    reset_tm=reset_xl_camera_tm_v17_mgr,
    tm_cfg_files=(CFG_FILE,),
    fileplay_tables={
        CFG_TABLE_D8: FilePlaySpec(
            'camera_d8', method_extract(XlCameraTmIngest, 'extract_d8_frames'), XlCameraTmV17Ingest
        ),
        CFG_TABLE_D9: FilePlaySpec(
            'camera_d9', method_extract(XlCameraTmIngest, 'extract_d9_frames'), XlCameraTmV17Ingest, parse_span=8
        ),
    },
)
