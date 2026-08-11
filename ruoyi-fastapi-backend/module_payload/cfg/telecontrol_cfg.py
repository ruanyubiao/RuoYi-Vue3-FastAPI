"""遥控配置统一封装：TeleControlCfg + TeleControlCfgManager。

cfgId 标识哪份 JSON；protocol 决定组件编解码后的封帧/校验策略。
遥控配置只允许经 TeleControlCfgManager 读写（勿直接写 Loader 遥控缓存）。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from exceptions.exception import ServiceException
from module_payload.cfg.payload_config_loader import CONFIG_DIR
from utils.log_util import logger

PROTOCOL_CAN_BUS = 'can_bus'
PROTOCOL_XL_BOARD = 'xl_board'
PROTOCOL_CAMERA = 'camera'

_TC_SUFFIX = '-TeleControlCfg.json'


def _tc_path(name: str) -> Path:
    return CONFIG_DIR / name


def cfg_id_from_filename(name: str) -> str:
    """``XL-RKDJ-TeleControlCfg.json`` → ``xl-rkdj-tc``。"""
    base = Path(name).name
    if base.endswith(_TC_SUFFIX):
        stem = base[: -len(_TC_SUFFIX)]
    elif base.lower().endswith('.json'):
        stem = base[: -len('.json')]
    else:
        stem = base
    parts = [p.lower() for p in stem.replace('_', '-').split('-') if p]
    return '-'.join(parts) + '-tc'


# cfgId → (path, protocol) —— protocol 以注册表为准，不做文件名启发式推断
TC_REGISTRY: dict[str, tuple[Path, str]] = {
    'biu-tc': (_tc_path('BIU-TeleControlCfg.json'), PROTOCOL_CAN_BUS),
    'xl-tc': (_tc_path('XL-TeleControlCfg.json'), PROTOCOL_CAN_BUS),
    'xl-rkdj-tc': (_tc_path('XL-RKDJ-TeleControlCfg.json'), PROTOCOL_XL_BOARD),
    'xl-zk-tc': (_tc_path('XL-ZK-TeleControlCfg.json'), PROTOCOL_XL_BOARD),
    'xl-camera-tc': (_tc_path('XL-Camera-TeleControlCfg.json'), PROTOCOL_CAMERA),
}


def protocol_for_cfg_id(cfg_id: str) -> str:
    cid = (cfg_id or '').strip().lower()
    if cid in TC_REGISTRY:
        return TC_REGISTRY[cid][1]
    raise ServiceException(message=f'未知遥控配置: {cfg_id}')


def cfg_id_for_family(family: str | None) -> str:
    return 'xl-tc' if (family or 'biu').strip().lower() == 'xl' else 'biu-tc'


def cfg_id_for_board(board: str) -> str:
    key = (board or '').strip().lower()
    if key == 'rkdj':
        return 'xl-rkdj-tc'
    if key == 'zk':
        return 'xl-zk-tc'
    raise ValueError(f'未知单板: {board}')


def cfg_id_for_camera() -> str:
    return 'xl-camera-tc'


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        logger.error(f'遥控配置文件不存在: {path}')
        raise ServiceException(message=f'遥控配置文件不存在: {path.name}')
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except ServiceException:
        raise
    except Exception as e:
        logger.error(f'加载遥控配置失败 {path}: {e}')
        raise ServiceException(message=f'加载遥控配置失败: {path.name}') from e
    if not isinstance(data, dict):
        raise ServiceException(message=f'遥控配置格式错误: {path.name}')
    return data


class TeleControlCfg:
    """单份 ``*TeleControlCfg.json`` 门面。"""

    def __init__(
        self,
        data: dict[str, Any],
        *,
        cfg_id: str,
        protocol: str,
        path: Path | None = None,
    ) -> None:
        self._data = data if isinstance(data, dict) else {}
        self.cfg_id = cfg_id
        self.protocol = protocol
        self.path = path

    @classmethod
    def from_path(cls, path: Path | str, *, cfg_id: str | None = None, protocol: str | None = None) -> TeleControlCfg:
        p = Path(path)
        cid = cfg_id or cfg_id_from_filename(p.name)
        if cid in TC_REGISTRY:
            reg_path, reg_proto = TC_REGISTRY[cid]
            p = reg_path
            proto = protocol or reg_proto
        elif protocol is not None:
            proto = protocol
        else:
            raise ServiceException(message=f'未知遥控配置: {cid}')
        return cls(_load_json(p), cfg_id=cid, protocol=proto, path=p)

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        cfg_id: str,
        protocol: str | None = None,
        path: Path | None = None,
    ) -> TeleControlCfg:
        proto = protocol if protocol is not None else protocol_for_cfg_id(cfg_id)
        return cls(
            data,
            cfg_id=cfg_id,
            protocol=proto,
            path=path,
        )

    @property
    def raw(self) -> dict[str, Any]:
        return self._data

    @property
    def page(self) -> list[Any]:
        return list(self._data.get('page') or [])

    @property
    def datetime(self) -> str:
        return str(self._data.get('datetime') or '')

    def list_orders(self) -> list[dict[str, Any]]:
        orders = self._data.get('order') or {}
        if not isinstance(orders, dict):
            return []
        out: list[dict[str, Any]] = []
        for oid, order in orders.items():
            if not isinstance(order, dict):
                continue
            item = copy.deepcopy(order)
            item.setdefault('id', oid)
            out.append(item)
        return out

    def get_order(self, order_id: str) -> dict[str, Any]:
        orders = self._data.get('order') or {}
        order = orders.get(order_id) if isinstance(orders, dict) else None
        if not order:
            raise ServiceException(message=f'指令 {order_id} 不存在')
        item = copy.deepcopy(order)
        item.setdefault('id', order_id)
        return item

    def assemble(self, order_id: str, values: list[Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        return self.assemble_order_dict(self.get_order(order_id), values, **kwargs)

    def assemble_order_dict(
        self,
        order: dict[str, Any],
        values: list[Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        values = values or []
        if self.protocol == PROTOCOL_CAMERA:
            from module_payload.cfg.camera_telecontrol_assembler import assemble_camera_order

            return assemble_camera_order(order, values, seq=int(kwargs.get('seq') or 0))
        if self.protocol == PROTOCOL_XL_BOARD:
            from module_payload.cfg.xl_board_telecontrol_assembler import assemble_xl_board_order

            return assemble_xl_board_order(order, values)
        from module_payload.cfg.telecontrol_assembler import assemble_order

        return assemble_order(order.get('component') or [], values)


class TeleControlCfgManager:
    """管理全部遥控配置实例（按 cfgId 缓存）。"""

    _instances: dict[str, TeleControlCfg] = {}

    @classmethod
    def known_ids(cls) -> list[str]:
        return list(TC_REGISTRY.keys())

    @classmethod
    def resolve_id(cls, cfg_id: str) -> str:
        cid = (cfg_id or '').strip().lower()
        if cid in TC_REGISTRY:
            return cid
        # 允许传文件名
        if cid.endswith('.json') or '-telecontrolcfg' in cid.replace('_', '-'):
            derived = cfg_id_from_filename(cfg_id)
            if derived in TC_REGISTRY:
                return derived
        raise ServiceException(message=f'未知遥控配置: {cfg_id}')

    @classmethod
    def get(cls, cfg_id: str, *, reload: bool = False) -> TeleControlCfg:
        cid = cls.resolve_id(cfg_id)
        if reload or cid not in cls._instances:
            path, protocol = TC_REGISTRY[cid]
            cls._instances[cid] = TeleControlCfg.from_path(path, cfg_id=cid, protocol=protocol)
            cls._sync_loader_cache(cid, cls._instances[cid].raw)
        return cls._instances[cid]

    @classmethod
    def _sync_loader_cache(cls, cfg_id: str, data: dict[str, Any]) -> None:
        """与 PayloadConfigLoader._cache 对齐，兼容旧 getter。遥控写入请只走 Manager。"""
        try:
            from module_payload.cfg.payload_config_loader import PayloadConfigLoader

            cache = PayloadConfigLoader._cache
            cache[cfg_id] = data
            if cfg_id == 'biu-tc':
                cache['telecontrol:biu'] = data
                cache['telecontrol'] = data
            elif cfg_id == 'xl-tc':
                cache['telecontrol:xl'] = data
            elif cfg_id == 'xl-camera-tc':
                cache['camera_telecontrol'] = data
            elif cfg_id == 'xl-rkdj-tc':
                cache['xl_tc:rkdj'] = data
            elif cfg_id == 'xl-zk-tc':
                cache['xl_tc:zk'] = data
        except Exception as e:
            logger.warning(f'同步遥控配置到 Loader 缓存失败 cfgId={cfg_id}: {e}')

    @classmethod
    def reload(cls, cfg_id_or_path: str | Path) -> str:
        """重载单个配置；返回 cfgId。"""
        raw = str(cfg_id_or_path)
        path = Path(raw)
        if path.suffix.lower() == '.json' or raw.endswith(_TC_SUFFIX):
            name = path.name if path.suffix else Path(raw).name
            cid = cfg_id_from_filename(name)
        else:
            cid = cls.resolve_id(raw)
        if cid not in TC_REGISTRY:
            raise ServiceException(message=f'未知遥控配置: {cfg_id_or_path}')
        cls._instances.pop(cid, None)
        cls.get(cid, reload=True)
        return cid

    @classmethod
    def reload_all(cls) -> None:
        cls._instances.clear()
        for cid in TC_REGISTRY:
            cls.get(cid, reload=True)

    @classmethod
    def assemble(
        cls,
        cfg_id: str,
        order_id: str,
        values: list[Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return cls.get(cfg_id).assemble(order_id, values, **kwargs)

    @classmethod
    def assemble_order_dict(
        cls,
        cfg_id: str,
        order: dict[str, Any],
        values: list[Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return cls.get(cfg_id).assemble_order_dict(order, values, **kwargs)

    @classmethod
    def cfg_id_for_path(cls, path: Path | str) -> str | None:
        p = Path(path)
        try:
            resolved = p.resolve()
        except OSError:
            resolved = p
        for cid, (reg_path, _) in TC_REGISTRY.items():
            try:
                if reg_path.resolve() == resolved:
                    return cid
            except OSError:
                if reg_path == p or reg_path.name == p.name:
                    return cid
        if p.name.endswith(_TC_SUFFIX):
            cid = cfg_id_from_filename(p.name)
            return cid if cid in TC_REGISTRY else None
        return None

    @classmethod
    def discover_in_dir(cls, root: Path | None = None) -> list[str]:
        """扫描目录下 ``*-TeleControlCfg.json``，返回已注册 cfgId 列表。"""
        base = Path(root) if root else Path(CONFIG_DIR)
        found: list[str] = []
        for path in sorted(base.glob('*-TeleControlCfg.json'), key=lambda x: x.name.lower()):
            cid = cfg_id_from_filename(path.name)
            if cid in TC_REGISTRY:
                found.append(cid)
        return found
