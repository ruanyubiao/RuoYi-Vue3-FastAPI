"""遥控/遥测配置文件：列表、读取、校验保存（仅限 assets/config 目录）。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config.paths import (
    list_config_file_info,
    read_config_json,
    read_config_text,
    require_config_name,
    resolve_config_file,
    save_config_text,
    stat_config_file,
)
from module_payload.cfg.payload_config_loader import PayloadConfigLoader


class PayloadConfigFileService:
    """配置文件读写与运行时重载（仅限 assets/config）。"""

    @classmethod
    def discover_files(cls) -> list[Path]:
        """外部优先、包内兜底后的实际文件路径。"""
        return [resolve_config_file(row['name']) for row in list_config_file_info()]

    @classmethod
    def resolve_safe(cls, file_name: str) -> Path:
        """校验文件名并解析为已存在的配置路径。"""
        name = require_config_name(file_name)
        path = resolve_config_file(name)
        if not path.is_file():
            raise FileNotFoundError(f'配置文件不存在: {name}')
        return path

    @classmethod
    def list_files(cls) -> list[dict[str, Any]]:
        """列出可编辑配置文件的元信息。"""
        return list_config_file_info()

    @classmethod
    def read_text(cls, file_name: str) -> dict[str, Any]:
        """读取配置原文，并附带 mtime 等元数据。"""
        info = stat_config_file(file_name)
        content = read_config_text(file_name)
        info['content'] = content
        return info

    @classmethod
    def save_text(cls, file_name: str, content: str) -> dict[str, Any]:
        """校验 JSON 后写回磁盘，并重载该文件到运行时缓存。"""
        name = require_config_name(file_name)
        cls.resolve_safe(name)
        text = content if content is not None else ''
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f'JSON 格式错误: {e.msg} (行 {e.lineno} 列 {e.colno})') from e
        if not isinstance(parsed, (dict, list)):
            raise ValueError('JSON 根节点须为对象或数组')
        # 连接默认配置写入时刷新 datetime，便于前端使缓存失效
        if name == 'cfg_device_connect.json' and isinstance(parsed, dict):
            parsed['datetime'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        dumped = json.dumps(parsed, ensure_ascii=False, indent=4)
        if not dumped.endswith('\n'):
            dumped += '\n'
        save_config_text(name, dumped)
        cls.reload_one(name)
        return cls.read_text(name)

    @classmethod
    def reload_runtime(cls) -> dict[str, Any]:
        """重新载入全部配置缓存（不重启进程）；并通知采集子进程重置解析器。"""
        PayloadConfigLoader.reload_all()
        try:
            from module_payload.collectors.process_manager import CollectorProcessManager

            CollectorProcessManager.instance().notify_reload_tm_cfg()
        except Exception:
            pass
        files = cls.list_files()
        return {'count': len(files), 'files': [f['name'] for f in files]}

    @classmethod
    def reload_one(cls, file_name: str) -> dict[str, Any]:
        """仅重载指定配置文件到运行时缓存。"""
        path = cls.resolve_safe(file_name)
        cache_key = PayloadConfigLoader.reload_file(path)
        if path.name.endswith('-TeleMetryCfg.json'):
            try:
                from module_payload.collectors.process_manager import CollectorProcessManager

                CollectorProcessManager.instance().notify_reload_tm_cfg()
            except Exception:
                pass
        meta = cls.read_text(path.name)
        return {
            'name': path.name,
            'cacheKey': cache_key,
            'mtime': meta.get('mtime'),
            'datetime': meta.get('datetime'),
        }

    @classmethod
    def _default_values_for_order(cls, order: dict[str, Any]) -> list[Any]:
        """按分量类型取 defaultVal / 首选项 / 0，供导出组帧。"""
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
        name = require_config_name(file_name)
        if not name.endswith('-TeleControlCfg.json'):
            raise ValueError('仅支持遥控配置文件导出指令列表')
        cfg = read_config_json(name)
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
