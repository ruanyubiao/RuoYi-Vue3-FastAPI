"""运行时数据目录：源码目录就地读写；wheel 安装后写到用户数据目录。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def get_package_root() -> Path:
    """安装包或源码树根目录（含 app.py / assets）。"""
    return Path(__file__).resolve().parent.parent


def is_source_checkout(root: Path | None = None) -> bool:
    """源码/Docker 工作副本：根目录有 pyproject.toml 或 .env.dev。"""
    root = root or get_package_root()
    return (root / 'pyproject.toml').is_file() or (root / '.env.dev').is_file()


def get_runtime_data_dir() -> Path:
    """
    可写数据根目录。

    优先 ``PGT_DATA_DIR``；源码目录用项目根；安装后的 wheel 用 ``%LOCALAPPDATA%/pgt``。
    """
    override = os.environ.get('PGT_DATA_DIR', '').strip()
    if override:
        path = Path(override).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
    root = get_package_root()
    if is_source_checkout(root):
        return root
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local'))
    else:
        base = Path(os.environ.get('XDG_DATA_HOME') or (Path.home() / '.local' / 'share'))
    data = (base / 'pgt').resolve()
    data.mkdir(parents=True, exist_ok=True)
    return data


def get_config_dir() -> Path:
    override = os.environ.get('PAYLOAD_CONFIG_DIR', '').strip()
    if override:
        return Path(override).expanduser().resolve()
    return get_runtime_data_dir() / 'assets' / 'config'


def ensure_config_dir() -> Path:
    """保证配置目录存在；安装环境下把包内默认 JSON 拷到用户目录（已有文件不覆盖）。"""
    dest = get_config_dir()
    dest.mkdir(parents=True, exist_ok=True)
    src = get_package_root() / 'assets' / 'config'
    if src.is_dir() and src.resolve() != dest.resolve():
        for src_file in src.glob('*.json'):
            target = dest / src_file.name
            if not target.exists():
                shutil.copy2(src_file, target)
    return dest
