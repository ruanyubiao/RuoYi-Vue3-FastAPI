import json
import os
from pathlib import Path
from typing import Any

from utils.log_util import logger

# 后端项目根目录：module_payload/cfg/payload_config_loader.py -> parents[2]
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_DIR = _BACKEND_ROOT / 'assets' / 'config'

# 允许通过环境变量覆盖配置目录
_CONFIG_DIR = Path(os.environ.get('PAYLOAD_CONFIG_DIR', str(_DEFAULT_CONFIG_DIR)))
CONFIG_DIR = _CONFIG_DIR

# BIU：星务/总线主配置；XL-*：各单板扩展配置
TELE_CONTROL_CFG_FILE = _CONFIG_DIR / 'BIU-TeleControlCfg.json'
TELE_METRY_CFG_FILE = _CONFIG_DIR / 'BIU-TeleMetryCfg.json'
CAMERA_TELE_CONTROL_CFG_FILE = _CONFIG_DIR / 'XL-Camera-TeleControlCfg.json'
CAMERA_TELE_METRY_CFG_FILE = _CONFIG_DIR / 'XL-Camera-TeleMetryCfg.json'

# XL 单板：热控电机 / CPA-ZK
XL_BOARD_TELECONTROL_FILES = {
    'rkdj': _CONFIG_DIR / 'XL-RKDJ-TeleControlCfg.json',
    'zk': _CONFIG_DIR / 'XL-ZK-TeleControlCfg.json',
}
XL_BOARD_TELEMETRY_FILES = {
    'rkdj': _CONFIG_DIR / 'XL-RKDJ-TeleMetryCfg.json',
    'zk': _CONFIG_DIR / 'XL-ZK-TeleMetryCfg.json',
}
XL_BOARD_TM_TABLE = {
    'rkdj': 'RKDJ',
    'zk': 'ZK',
}


class PayloadConfigLoader:
    """
    遥控/遥测配置文件加载器（带内存缓存，可重新加载）。

    - BIU-TeleControlCfg.json：遥控主配置
    - *-TeleMetryCfg.json：遥测配置（table），解析与表下拉
    """

    _cache: dict[str, Any] = {}

    @classmethod
    def _load_json(cls, file_path: Path) -> dict[str, Any]:
        if not file_path.exists():
            logger.error(f'配置文件不存在: {file_path}')
            return {}
        try:
            with open(file_path, encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f'加载配置文件失败 {file_path}: {e}')
            return {}

    @classmethod
    def discover_telemetry_cfg_sources(cls) -> list[tuple[str, Path]]:
        """
        扫描 config 目录 ``*-TeleMetryCfg.json``（含 BIU-/XL-），按文件名排序。
        同 table key 合并时保留先出现的源。
        """
        sources: list[tuple[str, Path]] = []
        seen: set[Path] = set()

        def _add(cache_key: str, path: Path) -> None:
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved in seen:
                return
            if not path.exists():
                return
            seen.add(resolved)
            sources.append((cache_key, path))

        for path in sorted(_CONFIG_DIR.glob('*-TeleMetryCfg.json'), key=lambda p: p.name.lower()):
            _add(cls._cache_key_for_path(path), path)
        return sources

    @classmethod
    def get_telecontrol_cfg(cls, reload: bool = False) -> dict[str, Any]:
        """获取 BIU 遥控配置。"""
        if reload or 'telecontrol' not in cls._cache:
            cls._cache['telecontrol'] = cls._load_json(TELE_CONTROL_CFG_FILE)
        return cls._cache['telecontrol']

    @classmethod
    def get_telemetry_cfg(cls, reload: bool = False) -> dict[str, Any]:
        """获取 BIU 主遥测配置。"""
        if reload or 'telemetry' not in cls._cache:
            cls._cache['telemetry'] = cls._load_json(TELE_METRY_CFG_FILE)
        return cls._cache['telemetry']

    @classmethod
    def get_camera_telecontrol_cfg(cls, reload: bool = False) -> dict[str, Any]:
        """获取相机遥控配置（SC-LINK41EP）。"""
        if reload or 'camera_telecontrol' not in cls._cache:
            cls._cache['camera_telecontrol'] = cls._load_json(CAMERA_TELE_CONTROL_CFG_FILE)
        return cls._cache['camera_telecontrol']

    @classmethod
    def get_camera_telemetry_cfg(cls, reload: bool = False) -> dict[str, Any]:
        """获取相机遥测配置（SC-LINK41EP）。"""
        if reload or 'camera_telemetry' not in cls._cache:
            cls._cache['camera_telemetry'] = cls._load_json(CAMERA_TELE_METRY_CFG_FILE)
        return cls._cache['camera_telemetry']

    @classmethod
    def normalize_xl_board(cls, board: str) -> str:
        key = (board or '').strip().lower()
        if key not in XL_BOARD_TELECONTROL_FILES:
            raise ValueError(f'未知单板: {board}（支持: {", ".join(sorted(XL_BOARD_TELECONTROL_FILES))}）')
        return key

    @classmethod
    def get_xl_board_telecontrol_cfg(cls, board: str, reload: bool = False) -> dict[str, Any]:
        key = cls.normalize_xl_board(board)
        cache_key = f'xl_tc:{key}'
        if reload or cache_key not in cls._cache:
            cls._cache[cache_key] = cls._load_json(XL_BOARD_TELECONTROL_FILES[key])
        return cls._cache[cache_key]

    @classmethod
    def get_xl_board_telemetry_cfg(cls, board: str, reload: bool = False) -> dict[str, Any]:
        key = cls.normalize_xl_board(board)
        cache_key = f'xl_tm:{key}'
        if reload or cache_key not in cls._cache:
            cls._cache[cache_key] = cls._load_json(XL_BOARD_TELEMETRY_FILES[key])
        return cls._cache[cache_key]

    @classmethod
    def xl_board_tm_table_key(cls, board: str) -> str:
        return XL_BOARD_TM_TABLE[cls.normalize_xl_board(board)]

    @classmethod
    def _cfg_by_cache_key(cls, cache_key: str, file_path: Path, reload: bool = False) -> dict[str, Any]:
        if reload or cache_key not in cls._cache:
            cls._cache[cache_key] = cls._load_json(file_path)
        return cls._cache[cache_key]

    @classmethod
    def iter_telemetry_cfgs(cls, reload: bool = False):
        """按目录扫描结果顺序产出各遥测配置 dict。"""
        for cache_key, path in cls.discover_telemetry_cfg_sources():
            yield cls._cfg_by_cache_key(cache_key, path, reload=reload)

    @classmethod
    def tables_to_page_list(cls, cfg: dict[str, Any]) -> list[dict[str, Any]]:
        """从遥测配置的 table 派生前端下拉项 [{id, key, name}, ...]（不再读 page 字段）。"""
        out: list[dict[str, Any]] = []
        for key, tbl in (cfg.get('table') or {}).items():
            k = str(key or '').upper()
            if not k:
                continue
            if not isinstance(tbl, dict):
                tbl = {}
            out.append(
                {
                    'id': str(tbl.get('id') or k).upper(),
                    'key': k,
                    'name': tbl.get('name') or k,
                }
            )
        return out

    @classmethod
    def merge_telemetry_pages(cls, reload: bool = False) -> list[dict[str, Any]]:
        """合并多配置文件 table 派生的表列表；同 key 只保留首次出现。"""
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for cfg in cls.iter_telemetry_cfgs(reload=reload):
            for p in cls.tables_to_page_list(cfg):
                key = p['key']
                if key in seen:
                    continue
                seen.add(key)
                merged.append(p)
        return merged

    @classmethod
    def find_telemetry_table(cls, table_type: str, reload: bool = False) -> dict[str, Any]:
        """按 table key 在合并源中查找表定义。"""
        key = (table_type or '').upper()
        if not key:
            return {}
        for cfg in cls.iter_telemetry_cfgs(reload=reload):
            found = (cfg.get('table') or {}).get(key)
            if found:
                return found
        return {}

    @classmethod
    def reload_all(cls) -> None:
        """清空 JSON 缓存；并重置主进程内 TeleMetryParser 管理器。"""
        cls._cache.clear()
        try:
            from module_payload.parsers import camera_sc_link41ep as cam_ingest
            from module_payload.parsers import tm_can_yc_ingest as can_ingest
            from module_payload.parsers import xl_board_tm as xl_ingest

            can_ingest.reset_tm_mgr()
            cam_ingest.reset_cam_tm_mgr()
            xl_ingest.reset_xl_board_tm_mgr()
        except Exception as e:
            logger.warning(f'重置遥测解析器缓存失败: {e}')

    @classmethod
    def _cache_key_for_path(cls, path: Path) -> str:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        known: dict[Path, str] = {
            TELE_CONTROL_CFG_FILE.resolve(): 'telecontrol',
            TELE_METRY_CFG_FILE.resolve(): 'telemetry',
            CAMERA_TELE_CONTROL_CFG_FILE.resolve(): 'camera_telecontrol',
            CAMERA_TELE_METRY_CFG_FILE.resolve(): 'camera_telemetry',
        }
        for board, p in XL_BOARD_TELECONTROL_FILES.items():
            try:
                known[p.resolve()] = f'xl_tc:{board}'
            except OSError:
                known[p] = f'xl_tc:{board}'
        for board, p in XL_BOARD_TELEMETRY_FILES.items():
            try:
                known[p.resolve()] = f'xl_tm:{board}'
            except OSError:
                known[p] = f'xl_tm:{board}'
        if resolved in known:
            return known[resolved]
        name = path.name
        if name.endswith('-TeleMetryCfg.json'):
            return f'tm:{path.stem}'
        if name.endswith('-TeleControlCfg.json'):
            return f'tc:{path.stem}'
        return f'file:{path.stem}'

    @classmethod
    def reload_file(cls, path: Path) -> str:
        """从磁盘重新读入单个配置文件到缓存，并按需重置对应解析器。返回 cache key。"""
        path = Path(path)
        key = cls._cache_key_for_path(path)
        data = cls._load_json(path)
        cls._cache[key] = data
        try:
            resolved = path.resolve()
            if resolved == TELE_METRY_CFG_FILE.resolve():
                from module_payload.parsers import tm_can_yc_ingest as can_ingest

                can_ingest.reset_tm_mgr()
            elif resolved == CAMERA_TELE_METRY_CFG_FILE.resolve():
                from module_payload.parsers import camera_sc_link41ep as cam_ingest

                cam_ingest.reset_cam_tm_mgr()
            elif path.name in ('XL-RKDJ-TeleMetryCfg.json', 'XL-ZK-TeleMetryCfg.json'):
                from module_payload.parsers import xl_board_tm as xl_ingest

                xl_ingest.reset_xl_board_tm_mgr()
        except Exception as e:
            logger.warning(f'重置解析器缓存失败 ({path.name}): {e}')
        return key
