"""按 cfg_device_connect.json 的 source key 合并打开连接请求。

有对应条目且 kind 匹配时：配置中的单值字段覆盖请求；baudChoices 等
多选：请求值在列表内则保留，否则取列表第一项（或配置里的单值默认）。
配置未覆盖的字段（端口号、CAN vendor/索引/线缆等）仍用请求体。
source 为 home / 未知 key 时不改请求。
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from module_payload.cfg.payload_config_loader import PayloadConfigLoader
from module_payload.constants import PARSER_NONE
from module_payload.entity.vo.payload_device_vo import CanOpenModel, NetOpenModel, SerialOpenModel

T = TypeVar('T', bound=BaseModel)


def _entry_for(source: str | None, kind: str) -> dict[str, Any]:
    key = (source or '').strip()
    if not key or key.lower() == 'home':
        return {}
    entry = PayloadConfigLoader.get_device_connect_entry(key)
    if not isinstance(entry, dict) or not entry:
        return {}
    if str(entry.get('kind') or '').strip().lower() != kind:
        return {}
    return entry


def _nonempty_str(entry: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key not in entry:
            continue
        text = str(entry.get(key) or '').strip()
        if text:
            return text
    return None


def _int_choices(entry: dict[str, Any], choices_key: str, *single_keys: str) -> list[int]:
    raw = entry.get(choices_key)
    out: list[int] = []
    if isinstance(raw, list):
        for item in raw:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
    if out:
        return out
    for key in single_keys:
        if key not in entry:
            continue
        try:
            return [int(entry[key])]
        except (TypeError, ValueError):
            continue
    return []


def _pick_choice(requested: Any, choices: list[int]) -> int | None:
    if not choices:
        return None
    try:
        req = int(requested)
    except (TypeError, ValueError):
        return choices[0]
    return req if req in choices else choices[0]


def _apply_pipeline(data: dict[str, Any], entry: dict[str, Any]) -> None:
    assembler = _nonempty_str(entry, 'assemblerId')
    if assembler is not None:
        data['assembler_id'] = assembler
    if 'parserId' in entry:
        raw = str(entry.get('parserId') or '').strip()
        if not raw or raw.lower() == PARSER_NONE:
            data['parser_id'] = ''
        else:
            data['parser_id'] = raw
    if 'fullDuplex' in entry:
        data['full_duplex'] = bool(entry.get('fullDuplex'))


def _rebuild(model_cls: type[T], body: T, data: dict[str, Any]) -> T:
    return model_cls.model_validate(data)


def merge_can_open(body: CanOpenModel) -> CanOpenModel:
    """合并 CAN 打开请求；无配置则原样返回。"""
    entry = _entry_for(body.source, 'can')
    if not entry:
        return body
    data = body.model_dump()
    choices = _int_choices(entry, 'baudChoices', 'baudRate', 'baudrate')
    picked = _pick_choice(data.get('baud_rate'), choices)
    if picked is not None:
        data['baud_rate'] = picked
    _apply_pipeline(data, entry)
    return _rebuild(CanOpenModel, body, data)


def merge_serial_open(body: SerialOpenModel) -> SerialOpenModel:
    """合并串口打开请求；无配置则原样返回。"""
    entry = _entry_for(body.source, 'serial')
    if not entry:
        return body
    data = body.model_dump()
    choices = _int_choices(entry, 'baudChoices', 'baudrate', 'baudRate')
    picked = _pick_choice(data.get('baudrate'), choices)
    if picked is not None:
        data['baudrate'] = picked
    if 'dataBits' in entry:
        try:
            data['data_bits'] = int(entry['dataBits'])
        except (TypeError, ValueError):
            pass
    if 'stopBits' in entry:
        try:
            data['stop_bits'] = float(entry['stopBits'])
        except (TypeError, ValueError):
            pass
    parity = _nonempty_str(entry, 'parity')
    if parity is not None:
        data['parity'] = parity
    flow = _nonempty_str(entry, 'flowControl')
    if flow is not None:
        data['flow_control'] = flow
    _apply_pipeline(data, entry)
    return _rebuild(SerialOpenModel, body, data)


def merge_net_open(body: NetOpenModel) -> NetOpenModel:
    """合并 UDP 打开请求；无配置则原样返回。"""
    entry = _entry_for(body.source, 'udp')
    if not entry:
        return body
    data = body.model_dump()
    host = _nonempty_str(entry, 'localHost')
    if host is not None:
        data['local_host'] = host
    if 'localPort' in entry:
        try:
            port = int(entry['localPort'])
            if port > 0:
                data['local_port'] = port
        except (TypeError, ValueError):
            pass
    if 'remoteHost' in entry:
        data['remote_host'] = str(entry.get('remoteHost') or '').strip()
    if 'remotePort' in entry:
        try:
            data['remote_port'] = int(entry['remotePort'])
        except (TypeError, ValueError):
            pass
    _apply_pipeline(data, entry)
    return _rebuild(NetOpenModel, body, data)
