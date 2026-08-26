"""文件回放允许的目录：上传 ``{UPLOAD_PATH}/log_data`` 与采集落盘 ``logs_data``。

浏览只列出文件夹 + 文件名含 ``_recv`` 的项（与采集落盘命名一致）。
``resolve_play_path`` 拒绝白名单外路径，防止任意读盘。
"""

from __future__ import annotations

from pathlib import Path

from config.paths import get_logs_data_dir, get_upload_log_data_dir

RECV_NAME_MARK = '_recv'


def upload_root() -> Path:
    """上传回放文件根：``{UPLOAD_PATH}/log_data``。"""
    return get_upload_log_data_dir()


def logs_root() -> Path:
    """采集落盘根：``logs_data``。"""
    return get_logs_data_dir()


def root_for(name: str) -> Path:
    """``upload`` → 上传目录；``logs`` → 本地日志。"""
    key = (name or '').strip().lower()
    if key in ('upload', 'log_data', 'uploaddir'):
        return upload_root()
    if key in ('logs', 'logs_data', 'local'):
        return logs_root()
    raise ValueError('root 仅支持 upload | logs')


def _is_relative_to(path: Path, root: Path) -> bool:
    """``path`` 是否在 ``root`` 之下（含自身）；解析失败当越界。"""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def resolve_play_path(path: str | Path) -> Path:
    """解析并校验路径必须落在上传 log_data 或 logs_data 下。

    相对路径先试 upload 再试 logs（与浏览「上传文件 / 本地日志」两根对应）。
    """
    p = Path(str(path)).expanduser()
    if not p.is_absolute():
        # 相对路径依次尝试两个根
        for root in (upload_root(), logs_root()):
            cand = (root / p).resolve()
            if cand.is_file() or cand.is_dir():
                p = cand
                break
        else:
            p = p.resolve()
    else:
        p = p.resolve()
    if not (_is_relative_to(p, upload_root()) or _is_relative_to(p, logs_root())):
        raise ValueError('路径不在允许的日志目录内')
    return p


def locate_play_file(path: str) -> dict:
    """若路径在 upload/logs 白名单内且存在，返回浏览用的 root + 相对目录 + 文件名。

    越界或不存在返回 ``found=False``，不抛错（打开选择框时静默回首页）。
    """
    raw = str(path or '').strip()
    if not raw:
        return {'found': False}
    try:
        resolved = resolve_play_path(raw)
    except ValueError:
        return {'found': False}
    if not resolved.exists():
        return {'found': False}
    upload = upload_root().resolve()
    logs = logs_root().resolve()
    candidates: list[tuple[str, Path]] = []
    if _is_relative_to(resolved, upload):
        candidates.append(('upload', upload))
    if _is_relative_to(resolved, logs):
        candidates.append(('logs', logs))
    if not candidates:
        return {'found': False}
    root_name, base = max(candidates, key=lambda x: len(str(x[1])))
    target = resolved.parent if resolved.is_file() else resolved
    rel = str(target.relative_to(base)).replace('\\', '/')
    if rel == '.':
        rel = ''
    return {
        'found': True,
        'root': root_name,
        'path': rel,
        'name': resolved.name if resolved.is_file() else '',
        'isFile': resolved.is_file(),
        'absPath': str(target),
    }


def is_recv_file(name: str) -> bool:
    """文件名含 ``_recv`` 才可选。"""
    return RECV_NAME_MARK in (name or '')


def list_dir(root_name: str, rel: str = '') -> dict:
    """列出某根下相对路径的目录项（文件夹全部列出，文件仅 ``_recv``）。"""
    root = root_for(root_name).resolve()
    rel = (rel or '').replace('\\', '/').lstrip('/')
    current = (root / rel).resolve() if rel else root
    if not _is_relative_to(current, root):
        raise ValueError('路径越界')
    if not current.exists():
        current.mkdir(parents=True, exist_ok=True)
    if not current.is_dir():
        raise ValueError('不是目录')
    entries: list[dict] = []
    for child in sorted(current.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if child.is_dir():
            entries.append({'name': child.name, 'isDir': True, 'selectable': False, 'size': None})
        elif child.is_file() and is_recv_file(child.name):
            entries.append(
                {
                    'name': child.name,
                    'isDir': False,
                    'selectable': True,
                    'size': int(child.stat().st_size),
                }
            )
    parent_rel = ''
    if current != root:
        parent_rel = str(current.parent.relative_to(root)).replace('\\', '/')
        if parent_rel == '.':
            parent_rel = ''
    return {
        'root': root_name,
        'path': rel,
        'absPath': str(current),
        'parent': parent_rel,
        'entries': entries,
    }
