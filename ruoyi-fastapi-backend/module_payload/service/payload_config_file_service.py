"""遥控/遥测配置文件：列表、读取、校验保存（仅限 assets/config 目录）。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from module_payload.cfg.payload_config_loader import CONFIG_DIR, PayloadConfigLoader

_SAFE_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._\-]*\.json$')


class PayloadConfigFileService:
    @classmethod
    def config_dir(cls) -> Path:
        return Path(CONFIG_DIR)

    @classmethod
    def discover_files(cls) -> list[Path]:
        """扫描 ``assets/config`` 下全部合法 ``*.json``，按文件名排序。"""
        root = cls.config_dir()
        out: list[Path] = []
        if not root.is_dir():
            return out
        for path in sorted(root.glob('*.json'), key=lambda p: p.name.lower()):
            if not path.is_file():
                continue
            if not _SAFE_NAME_RE.match(path.name):
                continue
            out.append(path)
        return out

    @classmethod
    def resolve_safe(cls, file_name: str) -> Path:
        name = (file_name or '').strip()
        if not _SAFE_NAME_RE.match(name):
            raise ValueError('非法文件名')
        root = cls.config_dir().resolve()
        path = (root / name).resolve()
        if path.parent != root or not path.is_file():
            raise FileNotFoundError(f'配置文件不存在: {name}')
        allowed = {p.resolve() for p in cls.discover_files()}
        if path not in allowed:
            raise FileNotFoundError(f'不是可管理的配置文件: {name}')
        return path

    @classmethod
    def _peek_datetime(cls, path: Path) -> str:
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return str(data.get('datetime') or '')
        except Exception:
            pass
        return ''

    @classmethod
    def list_files(cls) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for i, path in enumerate(cls.discover_files(), start=1):
            st = path.stat()
            mtime = datetime.fromtimestamp(st.st_mtime)
            rows.append(
                {
                    'index': i,
                    'name': path.name,
                    'datetime': cls._peek_datetime(path),
                    'mtime': mtime.strftime('%Y-%m-%d %H:%M:%S'),
                    'size': st.st_size,
                }
            )
        return rows

    @classmethod
    def read_text(cls, file_name: str) -> dict[str, Any]:
        path = cls.resolve_safe(file_name)
        content = path.read_text(encoding='utf-8')
        st = path.stat()
        mtime = datetime.fromtimestamp(st.st_mtime)
        datetime_val = ''
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                datetime_val = str(parsed.get('datetime') or '')
        except Exception:
            pass
        return {
            'name': path.name,
            'content': content,
            'datetime': datetime_val,
            'mtime': mtime.strftime('%Y-%m-%d %H:%M:%S'),
            'size': st.st_size,
        }

    @classmethod
    def save_text(cls, file_name: str, content: str) -> dict[str, Any]:
        path = cls.resolve_safe(file_name)
        text = content if content is not None else ''
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f'JSON 格式错误: {e.msg} (行 {e.lineno} 列 {e.colno})') from e
        if not isinstance(parsed, (dict, list)):
            raise ValueError('JSON 根节点须为对象或数组')
        # cfg_device_connect：写入时刷新根级 datetime
        if path.name == 'cfg_device_connect.json' and isinstance(parsed, dict):
            parsed['datetime'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        dumped = json.dumps(parsed, ensure_ascii=False, indent=4)
        if not dumped.endswith('\n'):
            dumped += '\n'
        path.write_text(dumped, encoding='utf-8')
        cls.reload_one(path.name)
        return cls.read_text(path.name)

    @classmethod
    def reload_runtime(cls) -> dict[str, Any]:
        """重新载入全部配置缓存（不重启进程）；采集子进程内解析器需重连/重启后生效。"""
        PayloadConfigLoader.reload_all()
        files = cls.list_files()
        return {'count': len(files), 'files': [f['name'] for f in files]}

    @classmethod
    def reload_one(cls, file_name: str) -> dict[str, Any]:
        """仅重载指定配置文件到运行时缓存。"""
        path = cls.resolve_safe(file_name)
        cache_key = PayloadConfigLoader.reload_file(path)
        meta = cls.read_text(path.name)
        return {
            'name': path.name,
            'cacheKey': cache_key,
            'mtime': meta.get('mtime'),
            'datetime': meta.get('datetime'),
        }

    @classmethod
    def _default_values_for_order(cls, order: dict[str, Any]) -> list[Any]:
        vals: list[Any] = []
        for comp in order.get('component') or []:
            ctype = (comp.get('componentType') or 'fixed').lower()
            default = comp.get('defaultVal')
            if ctype == 'fixed':
                vals.append(default)
            elif ctype == 'select':
                if default not in (None, ''):
                    vals.append(default)
                else:
                    opts = comp.get('options') or {}
                    vals.append(next(iter(opts), ''))
            elif ctype == 'number':
                if default not in (None, ''):
                    try:
                        vals.append(float(default) if '.' in str(default) else int(default))
                    except (TypeError, ValueError):
                        vals.append(0)
                else:
                    vals.append(0)
            else:
                vals.append(default if default not in (None, '') else '')
        return vals

    @classmethod
    def _order_ids(cls, cfg: dict[str, Any]) -> list[str]:
        """按 page.orderList 顺序导出；无则按 order 字典键。"""
        seen: set[str] = set()
        out: list[str] = []
        for page in cfg.get('page') or []:
            for oid in page.get('orderList') or []:
                sid = str(oid)
                if sid and sid not in seen:
                    seen.add(sid)
                    out.append(sid)
        for oid in (cfg.get('order') or {}):
            sid = str(oid)
            if sid and sid not in seen:
                seen.add(sid)
                out.append(sid)
        return out

    @classmethod
    def export_orders_defaults(cls, file_name: str) -> list[dict[str, Any]]:
        """导出遥控配置全部指令（默认参数组帧）为 [{id,name,hex,len}, ...]。"""
        path = cls.resolve_safe(file_name)
        name = path.name
        if not name.endswith('-TeleControlCfg.json'):
            raise ValueError('仅支持遥控配置文件导出指令列表')

        text = path.read_text(encoding='utf-8')
        cfg = json.loads(text)
        if not isinstance(cfg, dict):
            raise ValueError('配置根节点须为对象')
        orders = cfg.get('order') or {}
        if not isinstance(orders, dict) or not orders:
            return []

        from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, cfg_id_from_filename

        cfg_id = cfg_id_from_filename(name)
        rows: list[dict[str, Any]] = []
        for oid in cls._order_ids(cfg):
            order = orders.get(oid)
            if not isinstance(order, dict):
                continue
            values = cls._default_values_for_order(order)
            try:
                assembled = TeleControlCfgManager.assemble_order_dict(cfg_id, order, values)
            except Exception as e:
                rows.append(
                    {
                        'id': order.get('id') or oid,
                        'name': order.get('name') or '',
                        'hex': '',
                        'len': 0,
                        'error': str(e),
                    }
                )
                continue
            hex_text = assembled.get('hex') or ''
            length = int(assembled.get('length') or 0)
            if not length and hex_text:
                length = len([p for p in hex_text.split() if p])
            rows.append(
                {
                    'id': order.get('id') or oid,
                    'name': order.get('name') or '',
                    'hex': hex_text,
                    'len': length,
                }
            )
        return rows
