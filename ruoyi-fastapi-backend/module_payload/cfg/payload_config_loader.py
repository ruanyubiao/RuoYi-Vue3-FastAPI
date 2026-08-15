from pathlib import Path
from typing import Any

from config.paths import ensure_config_dir, get_external_config_dir, list_config_names, resolve_config_file
from utils.log_util import logger

ensure_config_dir()
CONFIG_DIR = get_external_config_dir()

TELE_CONTROL_CFG_NAME = 'BIU-TeleControlCfg.json'
TELE_METRY_CFG_NAME = 'BIU-TeleMetryCfg.json'
XL_TELE_CONTROL_CFG_NAME = 'XL-TeleControlCfg.json'
XL_TELE_METRY_CFG_NAME = 'XL-TeleMetryCfg.json'
CAMERA_TELE_CONTROL_CFG_NAME = 'XL-Camera-TeleControlCfg.json'
CAMERA_TELE_METRY_CFG_NAME = 'XL-Camera-TeleMetryCfg.json'
DEVICE_CONNECT_CFG_NAME = 'cfg_device_connect.json'


class _ResolvedCfg:
    """每次访问按 外部→包内 解析，兼容原 Path 用法。"""

    __slots__ = ('name',)

    def __init__(self, name: str):
        self.name = name

    def _p(self) -> Path:
        return resolve_config_file(self.name)

    def exists(self) -> bool:
        return self._p().is_file()

    def is_file(self) -> bool:
        return self._p().is_file()

    def stat(self):
        return self._p().stat()

    def resolve(self) -> Path:
        return self._p().resolve()

    def __str__(self) -> str:
        return str(self._p())

    def __fspath__(self) -> str:
        return str(self._p())


# BIU：星务/总线主配置；XL / XL-*：总线与各单板扩展配置
TELE_CONTROL_CFG_FILE = _ResolvedCfg(TELE_CONTROL_CFG_NAME)
TELE_METRY_CFG_FILE = _ResolvedCfg(TELE_METRY_CFG_NAME)
XL_TELE_CONTROL_CFG_FILE = _ResolvedCfg(XL_TELE_CONTROL_CFG_NAME)
XL_TELE_METRY_CFG_FILE = _ResolvedCfg(XL_TELE_METRY_CFG_NAME)
CAMERA_TELE_CONTROL_CFG_FILE = _ResolvedCfg(CAMERA_TELE_CONTROL_CFG_NAME)
CAMERA_TELE_METRY_CFG_FILE = _ResolvedCfg(CAMERA_TELE_METRY_CFG_NAME)

# XL 单板：热控电机 / CPA-ZK（值为文件名，读取时 resolve）
XL_BOARD_TELECONTROL_FILES = {
    'rkdj': 'XL-RKDJ-TeleControlCfg.json',
    'zk': 'XL-ZK-TeleControlCfg.json',
}
XL_BOARD_TELEMETRY_FILES = {
    'rkdj': 'XL-RKDJ-TeleMetryCfg.json',
    'zk': 'XL-ZK-TeleMetryCfg.json',
}
XL_BOARD_TM_TABLE = {
    'rkdj': 'RKDJ',
    'zk': 'ZK',
}

DEVICE_CONNECT_CFG_FILE = _ResolvedCfg(DEVICE_CONNECT_CFG_NAME)


class PayloadConfigLoader:
    """
    遥控/遥测配置文件加载器（带内存缓存，可重新加载）。

    - BIU-TeleControlCfg.json：遥控主配置
    - *-TeleMetryCfg.json：遥测配置（table），解析与表下拉
    """

    _cache: dict[str, Any] = {}

    @classmethod
    def _load_json(cls, file_path: Path) -> dict[str, Any]:
        from config.paths import read_config_json

        name = Path(file_path).name
        try:
            data = read_config_json(name)
        except FileNotFoundError:
            logger.error(f'配置文件不存在: {name}')
            return {}
        except Exception as e:
            logger.error(f'加载配置文件失败 {name}: {e}')
            return {}
        return data if isinstance(data, dict) else {}

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

        for name in list_config_names('*-TeleMetryCfg.json'):
            path = resolve_config_file(name)
            _add(cls._cache_key_for_path(path), path)
        return sources

    @classmethod
    def normalize_family(cls, family: str | None) -> str:
        key = (family or 'biu').strip().lower()
        return 'xl' if key == 'xl' else 'biu'

    @classmethod
    def family_from_tm_path(cls, path: Path) -> str:
        name = (path.name or '').upper()
        if name.startswith('BIU-'):
            return 'biu'
        if name.startswith('XL-'):
            return 'xl'
        return 'biu'

    @classmethod
    def get_telecontrol_cfg(cls, family: str | None = 'biu', reload: bool = False) -> dict[str, Any]:
        """获取 BIU / XL 总线遥控配置。"""
        from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, cfg_id_for_family

        fam = cls.normalize_family(family)
        tc = TeleControlCfgManager.get(cfg_id_for_family(fam), reload=reload)
        return tc.raw

    @classmethod
    def get_telemetry_cfg(cls, family: str | None = 'biu', reload: bool = False) -> dict[str, Any]:
        """获取 BIU / XL 主遥测配置。"""
        fam = cls.normalize_family(family)
        cache_key = f'telemetry:{fam}'
        if reload or cache_key not in cls._cache:
            path = resolve_config_file(XL_TELE_METRY_CFG_NAME if fam == 'xl' else TELE_METRY_CFG_NAME)
            cls._cache[cache_key] = cls._load_json(path)
        return cls._cache[cache_key]

    @classmethod
    def get_camera_telecontrol_cfg(cls, reload: bool = False) -> dict[str, Any]:
        """获取相机遥控配置（SC-LINK41EP）。"""
        from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, cfg_id_for_camera

        return TeleControlCfgManager.get(cfg_id_for_camera(), reload=reload).raw

    @classmethod
    def get_camera_telemetry_cfg(cls, reload: bool = False) -> dict[str, Any]:
        """获取相机遥测配置（SC-LINK41EP）。"""
        if reload or 'camera_telemetry' not in cls._cache:
            cls._cache['camera_telemetry'] = cls._load_json(resolve_config_file(CAMERA_TELE_METRY_CFG_NAME))
        return cls._cache['camera_telemetry']

    @classmethod
    def normalize_xl_board(cls, board: str) -> str:
        key = (board or '').strip().lower()
        if key not in XL_BOARD_TELECONTROL_FILES:
            raise ValueError(f'未知单板: {board}（支持: {", ".join(sorted(XL_BOARD_TELECONTROL_FILES))}）')
        return key

    @classmethod
    def get_xl_board_telecontrol_cfg(cls, board: str, reload: bool = False) -> dict[str, Any]:
        from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, cfg_id_for_board

        key = cls.normalize_xl_board(board)
        return TeleControlCfgManager.get(cfg_id_for_board(key), reload=reload).raw

    @classmethod
    def get_xl_board_telemetry_cfg(cls, board: str, reload: bool = False) -> dict[str, Any]:
        key = cls.normalize_xl_board(board)
        cache_key = f'xl_tm:{key}'
        if reload or cache_key not in cls._cache:
            cls._cache[cache_key] = cls._load_json(resolve_config_file(XL_BOARD_TELEMETRY_FILES[key]))
        return cls._cache[cache_key]

    @classmethod
    def get_device_connect_cfg(cls, reload: bool = False) -> dict[str, Any]:
        """获取设备默认连接配置（key=来源唯一标识；过滤 datetime 等非条目字段）。"""
        if reload or 'device_connect' not in cls._cache:
            cls._cache['device_connect'] = cls._load_json(resolve_config_file(DEVICE_CONNECT_CFG_NAME))
        data = cls._cache['device_connect']
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if isinstance(v, dict)}

    @classmethod
    def get_device_connect_entry(cls, key: str, *, reload: bool = False) -> dict[str, Any]:
        """取单个连接默认项；home 下可再带 kind（can/serial/udp）。"""
        cfg = cls.get_device_connect_cfg(reload=reload)
        name = (key or '').strip()
        if not name:
            return {}
        entry = cfg.get(name)
        return entry if isinstance(entry, dict) else {}

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
    def tables_to_page_list(
        cls,
        cfg: dict[str, Any],
        *,
        family: str | None = None,
        source: str | None = None,
        storage_key: bool = False,
    ) -> list[dict[str, Any]]:
        """从遥测配置的 table 派生前端下拉项。

        storage_key=True 时 key 为 BIU:FF / XL:FF（总线遥测表页/曲线）。
        """
        from module_payload.constants import make_bus_tm_key

        fam = cls.normalize_family(family) if family else None
        out: list[dict[str, Any]] = []
        for key, tbl in (cfg.get('table') or {}).items():
            local = str(key or '').upper()
            if not local:
                continue
            if not isinstance(tbl, dict):
                tbl = {}
            store_key = make_bus_tm_key(fam, local) if (storage_key and fam) else local
            item = {
                'id': str(tbl.get('id') or local).upper(),
                'key': store_key,
                'localKey': local,
                'name': tbl.get('name') or local,
            }
            if fam:
                item['family'] = fam
            if source:
                item['source'] = source
            out.append(item)
        return out

    @classmethod
    def merge_telemetry_pages(cls, reload: bool = False, family: str | None = None) -> list[dict[str, Any]]:
        """合并遥测表下拉（曲线/归档共用）。

        - XL 组：XL 总线 + 单板 RKDJ/ZK + 相机（4 份配置；相机含 D8/D9）
        - BIU 组：BIU 总线
        - 总线表 key=BIU:FF / XL:FF；单板/相机 key=本地表键（与 Redis data_sub 一致）
        - XL 组在前
        """
        want = cls.normalize_family(family) if family else None
        out: list[dict[str, Any]] = []

        if not want or want == 'xl':
            if XL_TELE_METRY_CFG_FILE.exists():
                cfg = cls.get_telemetry_cfg('xl', reload=reload)
                out.extend(
                    cls.tables_to_page_list(
                        cfg, family='xl', source=XL_TELE_METRY_CFG_FILE.name, storage_key=True
                    )
                )
            for board, fname in XL_BOARD_TELEMETRY_FILES.items():
                path = resolve_config_file(fname)
                if not path.is_file():
                    continue
                try:
                    cfg = cls.get_xl_board_telemetry_cfg(board, reload=reload)
                except ValueError:
                    continue
                out.extend(
                    cls.tables_to_page_list(
                        cfg, family='xl', source=fname, storage_key=False
                    )
                )
            if CAMERA_TELE_METRY_CFG_FILE.exists():
                cfg = cls.get_camera_telemetry_cfg(reload=reload)
                out.extend(
                    cls.tables_to_page_list(
                        cfg,
                        family='xl',
                        source=CAMERA_TELE_METRY_CFG_FILE.name,
                        storage_key=False,
                    )
                )

        if not want or want == 'biu':
            if TELE_METRY_CFG_FILE.exists():
                cfg = cls.get_telemetry_cfg('biu', reload=reload)
                out.extend(
                    cls.tables_to_page_list(
                        cfg, family='biu', source=TELE_METRY_CFG_FILE.name, storage_key=True
                    )
                )
        return out

    @classmethod
    def _file_mtime_str(cls, path: Path) -> str:
        try:
            from datetime import datetime

            return datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        except OSError:
            return ''

    @classmethod
    def find_telemetry_table_meta(
        cls, table_type: str, reload: bool = False, family: str | None = None
    ) -> dict[str, Any]:
        """查找表定义及来源时间戳：{table, datetime, mtime, source}。"""
        from module_payload.constants import split_tm_table_key

        fam_from_key, local = split_tm_table_key(table_type)
        if not local:
            return {'table': {}, 'datetime': '', 'mtime': '', 'source': ''}
        want = cls.normalize_family(family or fam_from_key) if (family or fam_from_key) else None

        def _pack(cfg: dict[str, Any], path: Path, found: dict[str, Any]) -> dict[str, Any]:
            return {
                'table': found,
                'datetime': str((cfg or {}).get('datetime') or ''),
                'mtime': cls._file_mtime_str(path),
                'source': path.name,
            }

        # 总线键：只查对应主配置
        if fam_from_key or want:
            fam = want or 'biu'
            path = resolve_config_file(XL_TELE_METRY_CFG_NAME if fam == 'xl' else TELE_METRY_CFG_NAME)
            cfg = cls.get_telemetry_cfg(fam, reload=reload)
            found = (cfg.get('table') or {}).get(local)
            if found:
                return _pack(cfg, path, found)
            if fam_from_key:
                return {'table': {}, 'datetime': '', 'mtime': '', 'source': ''}

        # 兼容无前缀：扫描全部 *-TeleMetryCfg（单板/相机等）
        for cache_key, path in cls.discover_telemetry_cfg_sources():
            cfg = cls._cfg_by_cache_key(cache_key, path, reload=reload)
            found = (cfg.get('table') or {}).get(local)
            if found:
                return _pack(cfg, path, found)
        return {'table': {}, 'datetime': '', 'mtime': '', 'source': ''}

    @classmethod
    def find_telemetry_table(
        cls, table_type: str, reload: bool = False, family: str | None = None
    ) -> dict[str, Any]:
        """按存储键（BIU:FF）或本地键查找表定义。"""
        return cls.find_telemetry_table_meta(table_type, reload=reload, family=family).get('table') or {}
    @classmethod
    def reload_all(cls) -> None:
        """清空 JSON 缓存；并重置主进程内 TeleMetryParser 管理器。"""
        cls._cache.clear()
        try:
            from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager

            TeleControlCfgManager._instances.clear()
        except Exception:
            pass
        try:
            from module_payload.parsers import camera_sc_link41ep as cam_ingest
            from module_payload.parsers import tm_can_yc_ingest as can_ingest
            from module_payload.parsers import xl_board_tm as xl_ingest
            from module_payload.parsers import xl_can_tm as xl_can_ingest

            can_ingest.reset_tm_mgr()
            xl_can_ingest.reset_tm_mgr()
            cam_ingest.reset_cam_tm_mgr()
            xl_ingest.reset_xl_board_tm_mgr()
        except Exception as e:
            logger.warning(f'重置遥测解析器缓存失败: {e}')

    @classmethod
    def _cache_key_for_path(cls, path: Path) -> str:
        name = Path(path).name
        try:
            from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager

            tc_id = TeleControlCfgManager.cfg_id_for_path(path)
            if tc_id:
                return tc_id
        except Exception:
            pass
        known_names: dict[str, str] = {
            TELE_METRY_CFG_NAME: 'telemetry:biu',
            XL_TELE_METRY_CFG_NAME: 'telemetry:xl',
            CAMERA_TELE_METRY_CFG_NAME: 'camera_telemetry',
            DEVICE_CONNECT_CFG_NAME: 'device_connect',
        }
        for board, fname in XL_BOARD_TELEMETRY_FILES.items():
            known_names[fname] = f'xl_tm:{board}'
        if name in known_names:
            return known_names[name]
        if name.endswith('-TeleMetryCfg.json'):
            return f'tm:{Path(name).stem}'
        if name.endswith('-TeleControlCfg.json'):
            from module_payload.cfg.telecontrol_cfg import cfg_id_from_filename

            return cfg_id_from_filename(name)
        return f'file:{Path(name).stem}'

    @classmethod
    def reload_file(cls, path: Path) -> str:
        """从磁盘重新读入单个配置文件到缓存，并按需重置对应解析器。返回 cache key。"""
        path = resolve_config_file(Path(path).name)
        # 遥控配置走 Manager，保证 cfgId 与 telecontrol:{fam} 等别名一致
        try:
            from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager

            tc_id = TeleControlCfgManager.cfg_id_for_path(path)
            if tc_id:
                return TeleControlCfgManager.reload(tc_id)
        except Exception:
            pass

        key = cls._cache_key_for_path(path)
        data = cls._load_json(path)
        cls._cache[key] = data
        name = path.name
        if name == TELE_METRY_CFG_NAME:
            cls._cache['telemetry:biu'] = data
        elif name == XL_TELE_METRY_CFG_NAME:
            cls._cache['telemetry:xl'] = data
        try:
            if name == TELE_METRY_CFG_NAME:
                from module_payload.parsers import tm_can_yc_ingest as can_ingest

                can_ingest.reset_tm_mgr()
            elif name == XL_TELE_METRY_CFG_NAME:
                from module_payload.parsers import xl_can_tm as xl_can_ingest

                xl_can_ingest.reset_tm_mgr()
            elif name == CAMERA_TELE_METRY_CFG_NAME:
                from module_payload.parsers import camera_sc_link41ep as cam_ingest

                cam_ingest.reset_cam_tm_mgr()
            elif name in XL_BOARD_TELEMETRY_FILES.values():
                from module_payload.parsers import xl_board_tm as xl_ingest

                xl_ingest.reset_xl_board_tm_mgr()
        except Exception as e:
            logger.warning(f'重置解析器缓存失败 ({name}): {e}')
        return key
