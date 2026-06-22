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

TELE_CONTROL_CFG_FILE = _CONFIG_DIR / 'TeleControlCfg.json'
TELE_METRY_CFG_FILE = _CONFIG_DIR / 'TeleMetryCfg.json'


class PayloadConfigLoader:
    """
    遥控/遥测配置文件加载器（带内存缓存，可重新加载）。

    - TeleControlCfg.json：遥控配置，构建指令树、组装 CAN 指令
    - TeleMetryCfg.json：遥测配置，解析遥测数据、生成遥测菜单/表单
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
    def get_telecontrol_cfg(cls, reload: bool = False) -> dict[str, Any]:
        """获取遥控配置。"""
        if reload or 'telecontrol' not in cls._cache:
            cls._cache['telecontrol'] = cls._load_json(TELE_CONTROL_CFG_FILE)
        return cls._cache['telecontrol']

    @classmethod
    def get_telemetry_cfg(cls, reload: bool = False) -> dict[str, Any]:
        """获取遥测配置。"""
        if reload or 'telemetry' not in cls._cache:
            cls._cache['telemetry'] = cls._load_json(TELE_METRY_CFG_FILE)
        return cls._cache['telemetry']

    @classmethod
    def reload_all(cls) -> None:
        """清空缓存，下次访问时重新加载。"""
        cls._cache.clear()
