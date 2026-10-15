"""遥控/遥测 JSON 配置加载：外部目录优先，带内存缓存。"""

from pathlib import Path
from typing import Any

from config.paths import ensure_config_dir, get_external_config_dir, list_config_names, resolve_config_file
from module_payload.protocol.protocol_catalog import (
    CAN_BUS_FAMILIES,
    bus_family_by_telemetry_cfg,
    family_from_cfg_name,
    require_bus_family,
)
from utils.log_util import logger
from utils.path_util import windows_basename

ensure_config_dir()  # 导入时整理外部覆盖层
CONFIG_DIR = get_external_config_dir()  # 外部可写配置目录

DEVICE_CONNECT_CFG_NAME = 'cfg_device_connect.json'  # 各来源默认连接参数


class _ResolvedCfg:
    """每次访问按 外部→包内 解析，兼容原 Path 用法。"""

    __slots__ = ('name',)

    def __init__(self, name: str):
        """按配置文件名构造延迟解析路径。"""
        self.name = name  # 配置文件名（不含路径）

    def _p(self) -> Path:
        """当前解析到的真实路径（外部优先）。"""
        return resolve_config_file(self.name)

    def exists(self) -> bool:
        """每次重新 resolve 后再判断（外部覆盖可能变化）。"""
        return self._p().is_file()

    def is_file(self) -> bool:
        """同 exists，兼容 Path.is_file。"""
        return self._p().is_file()

    def stat(self):
        """当前解析路径的 os.stat。"""
        return self._p().stat()

    def resolve(self) -> Path:
        """当前解析路径的绝对路径。"""
        return self._p().resolve()

    def __str__(self) -> str:
        """当前解析路径的字符串形式。"""
        return str(self._p())

    def __fspath__(self) -> str:
        """os.fspath 兼容，返回当前解析路径。"""
        return str(self._p())


DEVICE_CONNECT_CFG_FILE = _ResolvedCfg(DEVICE_CONNECT_CFG_NAME)


class PayloadConfigLoader:
    """
    遥控/遥测配置文件加载器（带内存缓存，可重新加载）。

    - *-TeleControlCfg.json：遥控配置，经 TeleControlCfgManager 按 cfgId 读
    - *-TeleMetryCfg.json：遥测配置（table），解析与表下拉；单板 / 相机与遥控同词干
    """

    _cache: dict[str, Any] = {}  # JSON 内存缓存，key 见 _cache_key_for_path

    @classmethod
    def _load_json(cls, file_path: Path) -> dict[str, Any]:
        """按文件名读 JSON；失败返回空 dict 并打日志。"""
        from config.paths import read_config_json

        name = Path(file_path).name
        name = windows_basename(name)  # 非 Windows 上兼容反斜杠路径
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
            """按绝对路径去重后加入扫描结果。"""
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
        """family 必须是已登记的总线族。空值或未知族报错。"""
        return require_bus_family(family).family

    @classmethod
    def family_from_tm_path(cls, path: Path) -> str:
        """文件名第一段转小写，必须落在总线清单里。"""
        return family_from_cfg_name(Path(path).name)

    @classmethod
    def get_telecontrol_cfg(cls, family: str | None, reload: bool = False) -> dict[str, Any]:
        """获取总线遥控配置。family 为空或未知时报错。"""
        from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, cfg_id_for_family

        fam = cls.normalize_family(family)
        tc = TeleControlCfgManager.get(cfg_id_for_family(fam), reload=reload)
        return tc.raw

    @classmethod
    def get_telemetry_cfg(cls, family: str | None, reload: bool = False) -> dict[str, Any]:
        """获取总线主遥测配置。family 为空或未知时报错。"""
        row = require_bus_family(family)
        cache_key = f'telemetry:{row.family}'
        if reload or cache_key not in cls._cache:
            path = resolve_config_file(row.telemetry_cfg)
            cls._cache[cache_key] = cls._load_json(path)
        return cls._cache[cache_key]

    @classmethod
    def get_board_telecontrol_cfg(cls, family: str, board: str, reload: bool = False) -> dict[str, Any]:
        """单板遥控配置（走 TeleControlCfgManager）。族 + 单板名未登记时抛 ValueError。"""
        from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, board_cfg_id

        return TeleControlCfgManager.get(board_cfg_id(family, board), reload=reload).raw

    @classmethod
    def get_board_telemetry_cfg(cls, family: str, board: str, reload: bool = False) -> dict[str, Any]:
        """单板遥测配置。族 + 单板名未登记时抛 ValueError。"""
        from module_payload.cfg.telecontrol_cfg import board_cfg_id

        return cls._paired_telemetry_cfg(board_cfg_id(family, board), reload=reload)

    @classmethod
    def _paired_telemetry_cfg(cls, cfg_id: str, *, reload: bool = False) -> dict[str, Any]:
        """遥控 cfgId 对应的同词干遥测 JSON；缓存键与按文件热重载一致。"""
        from module_payload.cfg.telecontrol_cfg import telemetry_cfg_for

        path = resolve_config_file(telemetry_cfg_for(cfg_id))
        return cls._cfg_by_cache_key(cls._cache_key_for_path(path), path, reload=reload)

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
    def _cfg_by_cache_key(cls, cache_key: str, file_path: Path, reload: bool = False) -> dict[str, Any]:
        """按 cache_key 读缓存，未命中则加载。"""
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

        每个总线族：先总线表，再该族在清单里登记的单板 / 相机遥测表。
        - 总线表 key=BIU:FF / XL:FF；单板/相机 key=本地表键（与 Redis data_sub 一致）
        """
        from module_payload.cfg.telecontrol_cfg import board_cfg_ids, telemetry_cfg_for

        want = cls.normalize_family(family) if family else None
        out: list[dict[str, Any]] = []

        for row in CAN_BUS_FAMILIES:
            if want and want != row.family:
                continue
            path = resolve_config_file(row.telemetry_cfg)
            if path.is_file():
                cfg = cls.get_telemetry_cfg(row.family, reload=reload)
                out.extend(
                    cls.tables_to_page_list(
                        cfg, family=row.family, source=row.telemetry_cfg, storage_key=True
                    )
                )
            for cid in board_cfg_ids(row.family):
                fname = telemetry_cfg_for(cid)
                if not resolve_config_file(fname).is_file():
                    continue
                cfg = cls._paired_telemetry_cfg(cid, reload=reload)
                out.extend(
                    cls.tables_to_page_list(cfg, family=row.family, source=fname, storage_key=False)
                )
        return out

    @classmethod
    def _file_mtime_str(cls, path: Path) -> str:
        """配置文件 mtime，供前端使 localStorage 失效。"""
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
            """打包表定义与来源文件时间戳。"""
            return {
                'table': found,
                'datetime': str((cfg or {}).get('datetime') or ''),
                'mtime': cls._file_mtime_str(path),
                'source': path.name,
            }

        # 总线键：只查对应主配置
        if fam_from_key or want:
            row = require_bus_family(want)
            path = resolve_config_file(row.telemetry_cfg)
            cfg = cls.get_telemetry_cfg(row.family, reload=reload)
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
            from module_payload.protocol.registry import reset_tm_caches

            reset_tm_caches()
        except Exception as e:
            logger.warning(f'重置遥测解析器缓存失败: {e}')

    @classmethod
    def _cache_key_for_path(cls, path: Path) -> str:
        """路径 → 缓存键；遥控走 Manager cfgId，遥测用 telemetry:{fam} 等。"""
        name = Path(path).name
        try:
            from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager

            tc_id = TeleControlCfgManager.cfg_id_for_path(path)
            if tc_id:
                return tc_id
        except Exception:
            pass
        known_names: dict[str, str] = {DEVICE_CONNECT_CFG_NAME: 'device_connect'}
        for row in CAN_BUS_FAMILIES:
            known_names[row.telemetry_cfg] = f'telemetry:{row.family}'
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
        # 遥控配置走 Manager，缓存键就是 cfgId
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
        bus_row = bus_family_by_telemetry_cfg(name)
        if bus_row is not None:
            cls._cache[f'telemetry:{bus_row.family}'] = data
        try:
            from module_payload.protocol.registry import reset_tm_caches

            reset_tm_caches(name)
        except Exception as e:
            logger.warning(f'重置解析器缓存失败 ({name}): {e}')
        return key
