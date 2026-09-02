"""SC-LINK41EP 串口遥测解释器（V1.6）：慢遥 0xD8、快遥 0xD9。

帧拆分与 ingest 在 CameraTmIngestBase；本模块绑定 V1.6 配置与表键 D8/D9。
"""

from __future__ import annotations

from typing import Any

from module_payload.cfg.payload_config_loader import CAMERA_TELE_METRY_CFG_NAME, PayloadConfigLoader
from module_payload.constants import PARSER_TM_XL_CAMERA
from module_payload.parsers.camera_tm_ingest_base import (
    D8_DATA_LEN,
    D8_FRAME_MIN,
    D9_DATA_LEN,
    D9_EXTENDED_DATA_LEN,
    D9_FRAME_LEN,
    D9_MUX_COUNT,
    D9_MUX_SLOT_LEN,
    FRAME_D9_HEADER,
    FRAME_HEADER,
    FRAME_TYPE_D8,
    FRAME_TYPE_D9,
    CameraTmIngestBase,
    ParsedXlCameraTm,
    _calc_checksum,
    _d9_build_extended_payload,
    _d9_camf011_bytes,
    _d9_mux_from_batch,
    _d9_mux_index,
    _ensure_bytes,
)
from module_payload.parsers.tm_ingest_batch import enqueue_prepared_many
from module_payload.parsers.tm_mgr_cache import TmMgrFileCache

# 兼容测试与其它模块从本文件 import 常量/工具
__all__ = [
    'D8_DATA_LEN',
    'D8_FRAME_MIN',
    'D9_DATA_LEN',
    'D9_EXTENDED_DATA_LEN',
    'D9_FRAME_LEN',
    'D9_MUX_COUNT',
    'D9_MUX_SLOT_LEN',
    'FRAME_D9_HEADER',
    'FRAME_HEADER',
    'FRAME_TYPE_D8',
    'FRAME_TYPE_D9',
    'ParsedXlCameraTm',
    'XlCameraTmIngest',
    '_TABLE_NAMES',
    '_calc_checksum',
    '_cam_tm_cache',
    '_d9_build_extended_payload',
    '_d9_camf011_bytes',
    '_d9_mux_cache',
    '_d9_mux_from_batch',
    '_d9_mux_index',
    '_ensure_bytes',
    '_get_cam_tm_mgr',
    'enqueue_prepared_many',
    'reset_xl_camera_tm_mgr',
]


class XlCameraTmIngest(CameraTmIngestBase):
    """V1.6：XL-Camera-TeleMetryCfg.json，表键 D8 / D9。"""

    PARSER_ID = PARSER_TM_XL_CAMERA
    TABLE_D8 = 'D8'
    TABLE_D9 = 'D9'
    _tm_file_cache = TmMgrFileCache()
    _table_names: dict[str, str] = {}
    _d9_mux_cache: dict[str, dict[int, bytes]] = {}

    @classmethod
    def _cfg_file_name(cls) -> str:
        return CAMERA_TELE_METRY_CFG_NAME

    @classmethod
    def _load_telemetry_cfg(cls, *, reload: bool = False) -> dict[str, Any]:
        return PayloadConfigLoader.get_camera_telemetry_cfg(reload=reload)


_TABLE_NAMES = XlCameraTmIngest._table_names
_d9_mux_cache = XlCameraTmIngest._d9_mux_cache
_cam_tm_cache = XlCameraTmIngest._tm_file_cache


def _get_cam_tm_mgr(*, reload: bool = False):
    """加载 XL-Camera-TeleMetryCfg.json 的 TeleMetryParser 管理器（进程内文件缓存）。"""
    return XlCameraTmIngest._get_tm_mgr(reload=reload)


def reset_xl_camera_tm_mgr() -> None:
    """清空相机遥测 TeleMetryCfgManager、表名缓存，以及 D9 mux last-known。

    关串口 / 热重载配置时调用，避免旧源的 mux 槽污染新会话。
    """
    XlCameraTmIngest.reset_mgr()
