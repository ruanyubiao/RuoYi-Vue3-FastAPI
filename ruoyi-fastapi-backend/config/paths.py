"""运行时路径与 JSON 配置存取：源码就地读写；wheel 安装后只写外部数据目录。

配置读写、列表、属性、保存一律走本模块；不要在业务文件里再拼 ``assets/config``。
"""

from __future__ import annotations

import filecmp
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)
_DT_DIGITS_RE = re.compile(r'\D+')
_SAFE_CFG_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._\-]*\.json$')


# ---------------------------------------------------------------------------
# 包根 / 可写数据根（wheel 下禁止写进 site-packages）
# ---------------------------------------------------------------------------


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


def resolve_data_subdir(relative_or_abs: str, *, default: str) -> Path:
    """相对路径落到数据根下；绝对路径原样使用。"""
    raw = (relative_or_abs or default).strip() or default
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = get_runtime_data_dir() / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _ensure_data_subdir(*parts: str) -> Path:
    path = get_runtime_data_dir().joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_vf_admin_dir() -> Path:
    return _ensure_data_subdir('vf_admin')


def get_upload_dir() -> Path:
    return _ensure_data_subdir('vf_admin', 'upload_path')


def get_download_dir() -> Path:
    return _ensure_data_subdir('vf_admin', 'download_path')


def get_gen_dir() -> Path:
    return _ensure_data_subdir('vf_admin', 'gen_path')


def get_cache_dir() -> Path:
    return _ensure_data_subdir('caches')


def get_logs_dir() -> Path:
    return _ensure_data_subdir('logs')


def get_logs_data_dir() -> Path:
    """连接收发落盘目录（代码里历史名为 logs_data）。"""
    return _ensure_data_subdir('logs_data')


def get_sqlite_path(db_name: str) -> Path:
    """SQLite 文件：相对名放数据根；绝对路径不改。"""
    raw = (db_name or 'ruoyi-fastapi').strip() or 'ruoyi-fastapi'
    name = raw if raw.lower().endswith('.db') else f'{raw}.db'
    path = Path(name).expanduser()
    if path.is_absolute():
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return get_runtime_data_dir() / path.name


# ---------------------------------------------------------------------------
# JSON 配置：外部优先、包内兜底；只在后台保存时写外部
# ---------------------------------------------------------------------------


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


def require_config_name(name: str) -> str:
    fname = _safe_cfg_name(name).strip()
    if not _SAFE_CFG_NAME_RE.match(fname):
        raise ValueError('非法文件名')
    return fname


def _glob_cfg_names(folder: Path, pattern: str) -> list[str]:
    if not folder.is_dir():
        return []
    names: list[str] = []
    for path in folder.glob(pattern):
        if path.is_file() and not path.name.endswith('.bak') and _SAFE_CFG_NAME_RE.match(path.name):
            names.append(path.name)
    return names


def resolve_config_file(name: str) -> Path:
    """先外部、再包内。都不存在时返回包内路径（调用方可 ``is_file()``）。"""
    fname = _safe_cfg_name(name)
    external = get_external_config_dir() / fname
    if external.is_file():
        return external
    return get_packaged_config_dir() / fname


def get_writable_config_path(name: str) -> Path:
    """后台保存用的外部路径；目录不存在则创建。不从包内拷贝。"""
    fname = require_config_name(name)
    dest = get_external_config_dir() / fname
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def list_config_names(pattern: str = '*.json') -> list[str]:
    """
    列出配置文件名：先扫外部、再扫包内，同名只保留一份（外部为准），再按文件名排序。
    """
    names: dict[str, None] = {}
    for fname in _glob_cfg_names(get_external_config_dir(), pattern):
        names[fname] = None
    for fname in _glob_cfg_names(get_packaged_config_dir(), pattern):
        names.setdefault(fname, None)
    return sorted(names, key=str.lower)


def iter_resolved_config_files(pattern: str = '*.json') -> list[Path]:
    """每个文件名再 ``resolve_config_file``：同名一定落到外部（若外部存在）。"""
    return [resolve_config_file(n) for n in list_config_names(pattern)]


def display_config_path(path: Path) -> str:
    """本机路径字符串（Windows 反斜杠，POSIX 正斜杠）。"""
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def config_file_layer(path: Path) -> str:
    """``external`` / ``packaged``；源码同目录时为 ``source``。"""
    if _config_dirs_are_same():
        return 'source'
    try:
        resolved = path.resolve()
        if resolved.is_relative_to(get_external_config_dir().resolve()):
            return 'external'
    except OSError:
        pass
    return 'packaged'


def _peek_cfg_datetime(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return str(data.get('datetime') or '').strip()
    except Exception:
        return ''
    return ''


def stat_config_file(name: str) -> dict[str, Any]:
    """配置文件属性：name / path / layer / datetime / mtime / size。"""
    fname = require_config_name(name)
    path = resolve_config_file(fname)
    if not path.is_file():
        raise FileNotFoundError(f'配置文件不存在: {fname}')
    st = path.stat()
    return {
        'name': path.name,
        'path': display_config_path(path),
        'layer': config_file_layer(path),
        'datetime': _peek_cfg_datetime(path),
        'mtime': datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
        'size': st.st_size,
    }


def list_config_file_info(pattern: str = '*.json') -> list[dict[str, Any]]:
    """合并列表：同名以外部文件为准。"""
    rows: list[dict[str, Any]] = []
    for i, fname in enumerate(list_config_names(pattern), start=1):
        info = stat_config_file(fname)
        info['index'] = i
        rows.append(info)
    return rows


def read_config_text(name: str) -> str:
    fname = require_config_name(name)
    path = resolve_config_file(fname)
    if not path.is_file():
        raise FileNotFoundError(f'配置文件不存在: {fname}')
    return path.read_text(encoding='utf-8')


def read_config_json(name: str) -> Any:
    """按文件名读 JSON（外部优先）。文件不存在抛 ``FileNotFoundError``。"""
    return json.loads(read_config_text(name))


def save_config_text(name: str, content: str) -> Path:
    """只写外部覆盖层；若与包内字节相同则删除外部。返回当前应读取的路径。"""
    fname = require_config_name(name)
    dest = get_writable_config_path(fname)
    dest.write_text(content if content is not None else '', encoding='utf-8')
    drop_redundant_overlay(fname)
    return resolve_config_file(fname)


def _datetime_stamp(path: Path) -> str:
    raw = _peek_cfg_datetime(path)
    digits = _DT_DIGITS_RE.sub('', raw)
    if len(digits) >= 12:
        return digits[:14]
    try:
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
