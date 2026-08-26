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
_DT_DIGITS_RE = re.compile(r'\D+')  # 抽 datetime 中的数字作备份戳
_SAFE_CFG_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._\-]*\.json$')  # 仅允许安全 JSON 文件名


# ---------------------------------------------------------------------------
# 包根 / 可写数据根（wheel 下禁止写进 site-packages）
# ---------------------------------------------------------------------------


def get_package_root() -> Path:
    """安装包或源码树根目录（含 app.py / assets）。"""
    return Path(__file__).resolve().parent.parent


def dotenv_filename(run_env: str | None = None) -> str:
    """``.env.dev`` / ``.env.{env}`` 文件名。空环境按 dev。"""
    env = '' if run_env is None else str(run_env).strip()
    return '.env.dev' if not env else f'.env.{env}'


def dotenv_search_dirs() -> list[Path]:
    """查找 .env 的目录：cwd（可覆盖）→ 包根 → ``config/``（wheel 副本）。"""
    root = get_package_root().resolve()
    cwd = Path.cwd().resolve()
    ordered: list[Path] = []
    for candidate in (cwd, root, root / 'config'):
        resolved = candidate.resolve()
        if resolved not in ordered:
            ordered.append(resolved)
    return ordered


def resolve_dotenv_path(run_env: str | None = None) -> Path:
    """解析 dotenv 路径；找不到时返回包根下的默认文件名（文件可以尚不存在）。"""
    name = dotenv_filename(run_env)
    # cwd 可覆盖 → 包根 → config/（wheel 副本）
    for base in dotenv_search_dirs():
        candidate = base / name
        if candidate.is_file():
            return candidate
    return get_package_root() / name


def is_installed_package(root: Path | None = None) -> bool:
    """是否位于 pip 安装树（``site-packages`` / ``dist-packages``）。"""
    root = (root or get_package_root()).resolve()
    return any(part.lower() in {'site-packages', 'dist-packages'} for part in root.parts)


def is_source_checkout(root: Path | None = None) -> bool:
    """源码/Docker 工作副本：不在 site-packages 内则就地读写。

    不要用包根是否存在 ``.env.dev`` 判断：wheel 可能把环境文件打进
    ``site-packages/pgt/``，否则日志会写进安装目录，卸载时残留。
    """
    return not is_installed_package(root)


def _is_windows_system_profile(path: Path) -> bool:
    """SYSTEM / LocalService 等服务账户目录，不能当作用户数据根。"""
    text = str(path).replace('/', '\\').lower()
    if 'systemprofile' in text:
        return True
    if '\\windows\\system32\\config\\' in text:
        return True
    if '\\windows\\serviceprofiles\\' in text:
        return True
    return False


def _windows_console_user_local_appdata() -> Path | None:
    """当前控制台登录用户的 LocalAppData（服务进程没有可用的 LOCALAPPDATA 时用）。"""
    try:
        import ctypes
        from ctypes import wintypes
        import winreg
    except ImportError:
        return None
    try:
        session_id = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
        if session_id in (0, 0xFFFFFFFF):
            return None
        buffer = ctypes.c_wchar_p()
        nbytes = wintypes.DWORD()
        if not ctypes.windll.wtsapi32.WTSQuerySessionInformationW(
            None, session_id, 5, ctypes.byref(buffer), ctypes.byref(nbytes)
        ):
            return None
        username = (buffer.value or '').strip()
        ctypes.windll.wtsapi32.WTSFreeMemory(buffer)
        if not username or username.lower() in {'system', 'local service', 'network service'}:
            return None
        profile_root = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList'
        )
        try:
            index = 0
            while True:
                try:
                    sid = winreg.EnumKey(profile_root, index)
                except OSError:
                    break
                index += 1
                if sid in {'S-1-5-18', 'S-1-5-19', 'S-1-5-20'}:
                    continue
                with winreg.OpenKey(profile_root, sid) as sid_key:
                    try:
                        image, _ = winreg.QueryValueEx(sid_key, 'ProfileImagePath')
                    except OSError:
                        continue
                image_path = Path(os.path.expandvars(str(image)))
                folder_name = image_path.name.lower()
                if folder_name == username.lower() or folder_name.startswith(username.lower() + '.'):
                    local = image_path / 'AppData' / 'Local'
                    if not _is_windows_system_profile(local):
                        return local
        finally:
            winreg.CloseKey(profile_root)
        guess = Path(os.environ.get('SystemDrive', 'C:')) / 'Users' / username / 'AppData' / 'Local'
        if guess.is_dir() and not _is_windows_system_profile(guess):
            return guess
    except Exception:
        return None
    return None


def _windows_existing_pgt_local_bases() -> list[Path]:
    """已经写过数据的用户 LocalAppData（例如 C:\\Users\\ryb\\AppData\\Local）。"""
    users_root = Path(os.environ.get('SystemDrive', 'C:')) / 'Users'
    found: list[Path] = []
    if not users_root.is_dir():
        return found
    skip = {'public', 'default', 'default user', 'all users'}
    for child in users_root.iterdir():
        if not child.is_dir() or child.name.lower() in skip:
            continue
        local = child / 'AppData' / 'Local'
        if (local / 'pgt').is_dir() and not _is_windows_system_profile(local):
            found.append(local)
    return found


def _windows_local_appdata_base() -> Path:
    """wheel 可写根的父目录：必须是真实用户，不能是 systemprofile。"""
    env_local = os.environ.get('LOCALAPPDATA', '').strip()
    if env_local:
        env_path = Path(env_local).expanduser()
        try:
            resolved = env_path.resolve()
        except OSError:
            resolved = env_path
        if not _is_windows_system_profile(resolved):
            return resolved
    console_local = _windows_console_user_local_appdata()
    if console_local is not None and not _is_windows_system_profile(console_local):
        return console_local.resolve()
    existing = _windows_existing_pgt_local_bases()
    if existing:
        return existing[0].resolve()
    user_profile = os.environ.get('USERPROFILE', '').strip()
    if user_profile:
        fallback = Path(user_profile) / 'AppData' / 'Local'
        if not _is_windows_system_profile(fallback):
            return fallback.resolve()
    return Path(os.environ.get('PROGRAMDATA', '').strip() or r'C:\ProgramData')


def get_runtime_data_dir() -> Path:
    """
    可写数据根目录。

    优先 ``PGT_DATA_DIR``；源码目录用项目根；安装后的 wheel 用当前登录用户的
    ``%LOCALAPPDATA%/pgt``。服务账户的 ``systemprofile`` 不能用，会回退到
    控制台用户或已有的 ``C:\\Users\\<用户>\\AppData\\Local\\pgt``。
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
        base = _windows_local_appdata_base()
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
    """数据根下创建子目录并返回。"""
    path = get_runtime_data_dir().joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_vf_admin_dir() -> Path:
    """若依后台文件根（upload/download/gen）。"""
    return _ensure_data_subdir('vf_admin')


def get_upload_dir() -> Path:
    """上传目录（含 log_data 子目录）。"""
    return _ensure_data_subdir('vf_admin', 'upload_path')


def get_upload_log_data_dir() -> Path:
    """遥测回放上传目录 ``{UPLOAD_PATH}/log_data``。"""
    return _ensure_data_subdir('vf_admin', 'upload_path', 'log_data')


def get_download_dir() -> Path:
    """下载输出目录。"""
    return _ensure_data_subdir('vf_admin', 'download_path')


def get_gen_dir() -> Path:
    """代码生成输出目录。"""
    return _ensure_data_subdir('vf_admin', 'gen_path')


def get_cache_dir() -> Path:
    """运行时缓存目录。"""
    return _ensure_data_subdir('caches')


def get_logs_dir() -> Path:
    """应用日志目录。"""
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
    """源码就地读写时外部与包内是同一目录。"""
    try:
        return get_external_config_dir().resolve() == get_packaged_config_dir().resolve()
    except OSError:
        return False


def _safe_cfg_name(name: str) -> str:
    """只保留文件名，防止路径穿越。"""
    return Path(name).name


def require_config_name(name: str) -> str:
    """校验配置文件名；非法抛 ValueError。"""
    fname = _safe_cfg_name(name).strip()
    if not _SAFE_CFG_NAME_RE.match(fname):
        raise ValueError('非法文件名')
    return fname


def _glob_cfg_names(folder: Path, pattern: str) -> list[str]:
    """扫描目录下合法 JSON 名（排除 .bak）。"""
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
    """读 JSON 根上的 datetime 字段，失败返回空串。"""
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
    """按文件名读 UTF-8 文本（外部优先）。"""
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
    """备份文件名用的时间戳：优先 JSON datetime，否则 mtime。"""
    raw = _peek_cfg_datetime(path)
    digits = _DT_DIGITS_RE.sub('', raw)
    if len(digits) >= 12:
        return digits[:14]
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y%m%d%H%M%S')
    except OSError:
        return '00000000000000'


def _packaged_cfg_newer(packaged: Path, external: Path) -> bool:
    """包内 datetime 是否新于外部（启动时把更旧外部改名为 .bak）。"""
    src_dt = _peek_cfg_datetime(packaged)
    dest_dt = _peek_cfg_datetime(external)
    if not src_dt:
        return False
    if not dest_dt:
        return True
    return src_dt > dest_dt


def _files_identical(a: Path, b: Path) -> bool:
    """逐字节比较；读失败视为不同。"""
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
