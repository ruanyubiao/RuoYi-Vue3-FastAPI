"""运行时数据目录与配置文件查找：源码就地读写；wheel 安装后外部覆盖层可写。"""

from __future__ import annotations

import filecmp
import json
import logging
import os
import re
from pathlib import Path

_LOG = logging.getLogger(__name__)
_DT_DIGITS_RE = re.compile(r'\D+')


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


def get_packaged_config_dir() -> Path:
    """包内/源码树中的配置目录（只读，wheel 下在 site-packages）。"""
    return get_package_root() / 'assets' / 'config'


def get_external_config_dir() -> Path:
    """外部覆盖层（后台保存才写到这里）。"""
    override = os.environ.get('PAYLOAD_CONFIG_DIR', '').strip()
    if override:
        return Path(override).expanduser().resolve()
    return get_runtime_data_dir() / 'assets' / 'config'


def get_config_dir() -> Path:
    """外部可写配置目录。读取请用 ``resolve_config_file``。"""
    return get_external_config_dir()


def _config_dirs_are_same() -> bool:
    try:
        return get_external_config_dir().resolve() == get_packaged_config_dir().resolve()
    except OSError:
        return False


def _safe_cfg_name(name: str) -> str:
    return Path(name).name


def resolve_config_file(name: str) -> Path:
    """外部优先，其次包内。都不存在时返回包内路径（调用方可 ``is_file()``）。"""
    fname = _safe_cfg_name(name)
    external = get_external_config_dir() / fname
    if external.is_file():
        return external
    return get_packaged_config_dir() / fname


def get_writable_config_path(name: str) -> Path:
    """后台保存用的外部路径；目录不存在则创建。不从包内拷贝。"""
    fname = _safe_cfg_name(name)
    dest = get_external_config_dir() / fname
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def list_config_names(pattern: str = '*.json') -> list[str]:
    """两个目录下配置文件名并集（不含 ``*.bak``），按文件名排序。"""
    names: set[str] = set()
    for folder in (get_external_config_dir(), get_packaged_config_dir()):
        if not folder.is_dir():
            continue
        for path in folder.glob(pattern):
            if path.is_file() and not path.name.endswith('.bak'):
                names.add(path.name)
    return sorted(names, key=str.lower)


def iter_resolved_config_files(pattern: str = '*.json') -> list[Path]:
    return [resolve_config_file(n) for n in list_config_names(pattern)]


def display_config_path(path: Path) -> str:
    """本机路径字符串（Windows 反斜杠，POSIX 正斜杠）。"""
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _peek_cfg_datetime(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return str(data.get('datetime') or '').strip()
    except Exception:
        return ''
    return ''


def _datetime_stamp(path: Path) -> str:
    raw = _peek_cfg_datetime(path)
    digits = _DT_DIGITS_RE.sub('', raw)
    if len(digits) >= 12:
        return digits[:14]
    try:
        from datetime import datetime

        return datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y%m%d%H%M%S')
    except OSError:
        return '00000000000000'


def _packaged_cfg_newer(packaged: Path, external: Path) -> bool:
    src_dt = _peek_cfg_datetime(packaged)
    dest_dt = _peek_cfg_datetime(external)
    if not src_dt:
        return False
    if not dest_dt:
        return True
    return src_dt > dest_dt


def _files_identical(a: Path, b: Path) -> bool:
    try:
        return filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def drop_redundant_overlay(name: str) -> bool:
    """外部与包内字节相同则删除外部文件。源码同目录时不处理。"""
    if _config_dirs_are_same():
        return False
    fname = _safe_cfg_name(name)
    packaged = get_packaged_config_dir() / fname
    external = get_external_config_dir() / fname
    if not packaged.is_file() or not external.is_file():
        return False
    if not _files_identical(packaged, external):
        return False
    try:
        external.unlink()
        _LOG.info('外部配置与包内相同，已删除 %s', external)
        return True
    except OSError as e:
        _LOG.warning('删除相同外部配置失败 %s: %s', external, e)
        return False


def reconcile_external_configs() -> None:
    """
    启动时整理外部覆盖层，不向外部拷贝包内文件。

    - 外部与包内一模一样：删除外部
    - 包内 datetime 更新、外部更旧：外部改名为 ``name.YYYYMMDDHHMMSS.bak``
    """
    if _config_dirs_are_same():
        return
    packaged_dir = get_packaged_config_dir()
    external_dir = get_external_config_dir()
    if not packaged_dir.is_dir() or not external_dir.is_dir():
        return
    for packaged in packaged_dir.glob('*.json'):
        if not packaged.is_file() or packaged.name.endswith('.bak'):
            continue
        external = external_dir / packaged.name
        if not external.is_file():
            continue
        if _files_identical(packaged, external):
            drop_redundant_overlay(packaged.name)
            continue
        if not _packaged_cfg_newer(packaged, external):
            continue
        stamp = _datetime_stamp(external)
        bak = external.with_name(f'{external.name}.{stamp}.bak')
        try:
            if bak.exists():
                bak.unlink()
            external.rename(bak)
            _LOG.info('包内配置已更新，外部旧文件改名为 %s', bak.name)
        except OSError as e:
            _LOG.warning('备份外部配置失败 %s: %s', external, e)


def ensure_config_dir() -> Path:
    """启动时整理外部覆盖层；不创建空目录、不拷贝包内文件。"""
    reconcile_external_configs()
    return get_external_config_dir()
