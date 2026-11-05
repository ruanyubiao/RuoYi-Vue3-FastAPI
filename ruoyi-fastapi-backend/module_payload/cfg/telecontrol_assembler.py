"""遥控组件编码与已组 HEX 的广播判断。各协议的组帧规则在 ``protocol/<族>/`` 下的 telecontrol 模块里。"""

from __future__ import annotations

import re
import struct
from typing import Any

from module_payload.cfg.hex_text import hex_to_bytes
from module_payload.constants import checksum_u8


def _strip_0x_prefix(text: str) -> str:
    """去掉可选的 0x 前缀。"""
    s = (text or '').strip()
    if s.lower().startswith('0x'):
        return s[2:]
    return s


def _clean_hex(text: str) -> str:
    """压成连续十六进制字符（配置 defaultVal / 宽度计算）。"""
    s = _strip_0x_prefix(text)
    return re.sub(r'[^0-9A-Fa-f]', '', s)


def _cfg_hex_to_bytes(text: str) -> bytes:
    """读 TeleControlCfg 的 defaultVal / 选项键。

    JSON 仍是 C++ 风格 ``0x92AA01``；HEX 输入框不允许 ``0x``。
    只在读配置时剥前缀，再走与前端相同的 token 规则。
    """
    return hex_to_bytes(_strip_0x_prefix(text))


def _is_little_endian(endian: str | None) -> bool:
    """组件 endian：little/le/lsb 为小端，其余默认大端。"""
    return str(endian or 'big').strip().lower() in ('little', 'le', 'lsb')


def encode_number(value: Any, data_type: str, endian: str = 'big') -> bytes:
    """按 dataType 打包数值；endian 默认 big，CPA 指向组件写 little。"""
    dt = (data_type or 'INT16').upper()
    if value is None or value == '':
        value = 0
    le = _is_little_endian(endian)
    prefix = '<' if le else '>'
    order = 'little' if le else 'big'
    if dt in ('INT8',):
        return struct.pack(f'{prefix}b', int(value))
    if dt in ('BYTE', 'UINT8'):
        return struct.pack(f'{prefix}B', int(value) & 0xFF)
    if dt in ('INT16',):
        return struct.pack(f'{prefix}h', int(value))
    if dt in ('UINT16',):
        return struct.pack(f'{prefix}H', int(value) & 0xFFFF)
    if dt in ('INT24',):
        v = int(value)
        return v.to_bytes(3, byteorder=order, signed=True)
    if dt in ('UINT24',):
        v = int(value) & 0xFFFFFF
        return v.to_bytes(3, byteorder=order, signed=False)
    if dt in ('INT32',):
        return struct.pack(f'{prefix}i', int(value))
    if dt in ('UINT32',):
        return struct.pack(f'{prefix}I', int(value) & 0xFFFFFFFF)
    if dt == 'FLOAT':
        return struct.pack(f'{prefix}f', float(value))
    if dt == 'DOUBLE':
        return struct.pack(f'{prefix}d', float(value))
    return struct.pack(f'{prefix}h', int(value))


def apply_component_formula(value: Any, formula: str) -> Any:
    """若 formula 非空，用 TeleMetryParser.exec_formula(D=value) 计算；结果为 float。"""
    expr = str(formula or '').strip()
    if not expr:
        return value
    try:
        from TeleMetryParser.tinyexpr import exec_formula
    except ImportError as e:
        raise ValueError('TeleMetryParser.tinyexpr 不可用，无法计算公式') from e
    try:
        d = 0.0 if _is_empty_value(value) else float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f'公式输入不是数值: {value!r}') from e
    result, err = exec_formula(expr, d)
    if err:
        raise ValueError(f'公式计算失败: {expr} (D={d})')
    return result


def _is_empty_value(value: Any) -> bool:
    """None / 空白串视为未填。"""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _byte_width_from_data_type(data_type: str) -> int:
    """数值类型对应字节宽度。"""
    dt = (data_type or 'INT16').upper()
    if dt in ('INT8', 'BYTE', 'UINT8'):
        return 1
    if dt in ('INT16', 'UINT16'):
        return 2
    if dt in ('INT24', 'UINT24'):
        return 3
    if dt in ('INT32', 'UINT32', 'FLOAT'):
        return 4
    if dt == 'DOUBLE':
        return 8
    return 2


def _hex_char_byte_width(hex_text: str) -> int:
    """HEX 文本（去空白后）折合字节数，奇数位向上取整。"""
    n = len(_clean_hex(hex_text))
    if not n:
        return 0
    return (n + 1) // 2


def _zero_bytes(width: int) -> bytes:
    """width 个 0x00。"""
    return b'\x00' * max(0, width)


def _select_byte_width(component: dict[str, Any]) -> int:
    """select 组件宽度：defaultVal 优先，否则看 options 键。"""
    width = _hex_char_byte_width(str(component.get('defaultVal', '')))
    if width:
        return width
    for key in (component.get('options') or {}):
        width = _hex_char_byte_width(str(key))
        if width:
            return width
    return 1


def _zero_bytes_for_component(component: dict[str, Any]) -> bytes:
    """空值时按组件类型输出等宽 0。"""
    ctype = (component.get('componentType') or 'fixed').lower()
    if ctype == 'number':
        return _zero_bytes(_byte_width_from_data_type(component.get('dataType', '')))
    if ctype == 'scientific':
        dt = (component.get('dataType') or 'DOUBLE').upper()
        return _zero_bytes(4 if dt == 'FLOAT' else 8)
    if ctype == 'hex':
        return _zero_bytes(_hex_char_byte_width(str(component.get('defaultVal', ''))))
    if ctype == 'select':
        return _zero_bytes(_select_byte_width(component))
    return b''


def _mask_byte_width(data_type: str) -> int:
    """勾选位图宽度。INT* 与 UINT* 都按无符号字节数。"""
    dt = (data_type or '').upper()
    if dt in ('INT8', 'UINT8', 'BYTE'):
        return 1
    if dt in ('INT16', 'UINT16'):
        return 2
    if dt in ('INT24', 'UINT24'):
        return 3
    if dt in ('INT32', 'UINT32'):
        return 4
    if dt in ('INT40', 'UINT40'):
        return 5
    if dt in ('INT48', 'UINT48'):
        return 6
    if dt in ('INT56', 'UINT56'):
        return 7
    if dt in ('INT64', 'UINT64'):
        return 8
    raise ValueError(f'checkboxgroup 的 dataType 不是整数宽度: {data_type!r}')


def _as_int(raw: Any, name: str) -> int:
    """配置或 mask 必须是整数；布尔值不算。"""
    if isinstance(raw, bool):
        raise ValueError(f'{name} 不是整数')
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and re.fullmatch(r'-?\d+', raw.strip() or ''):
        return int(raw.strip())
    raise ValueError(f'{name} 不是整数')


def configured_component_width(component: dict[str, Any]) -> int:
    """槽位宽度只看配置，不看当前输入。定不出宽度则报错。"""
    ctype = (component.get('componentType') or 'fixed').lower()
    if ctype == 'checkboxgroup':
        raise ValueError('不支持嵌套 checkboxgroup')
    if ctype == 'number':
        return _byte_width_from_data_type(component.get('dataType', ''))
    if ctype == 'scientific':
        dt = (component.get('dataType') or 'DOUBLE').upper()
        return 4 if dt == 'FLOAT' else 8
    if ctype == 'hex':
        return _hex_char_byte_width(str(component.get('defaultVal', '')))
    if ctype == 'select':
        return _select_byte_width(component)
    if ctype == 'fixed':
        return len(_cfg_hex_to_bytes(str(component.get('defaultVal', '') or '')))
    raise ValueError(f'无法确定组件宽度: {ctype}')


def _fill_byte(component: dict[str, Any]) -> int:
    """groupDataDefaultByte；缺省 0x00；必须恰好一个字节。"""
    raw = component.get('groupDataDefaultByte')
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return 0
    data = _cfg_hex_to_bytes(str(raw))
    if len(data) != 1:
        raise ValueError('groupDataDefaultByte 必须是一个字节')
    return data[0]


def _group_data_length(component: dict[str, Any]) -> int:
    """小于 0 表示按槽位求和。缺省 -1。"""
    if 'groupDataLength' not in component or component.get('groupDataLength') is None:
        return -1
    return _as_int(component.get('groupDataLength'), 'groupDataLength')


def _mask_from_value(value: Any, nbytes: int, group_len: int) -> int:
    """mask 为等宽 0/1 字符串，左边是高位，最右边是 group[0]。空值视为全 0。"""
    bits = nbytes * 8
    if value is None or value == '':
        mask = 0
    elif isinstance(value, dict):
        raw = value.get('mask', 0)
        if raw is None or raw == '':
            mask = 0
        elif isinstance(raw, str) and re.fullmatch(r'[01]+', raw.strip()):
            text = raw.strip()
            if len(text) != bits:
                raise ValueError('mask 位数与 dataType 不一致')
            mask = int(text, 2)
        else:
            mask = _as_int(raw, 'mask')
    else:
        raise ValueError('checkboxgroup 的值必须包含 mask')
    limit = 1 << (nbytes * 8)
    if mask < 0 or mask >= limit:
        raise ValueError('mask 超出 dataType 范围')
    if mask >> group_len:
        raise ValueError('mask 含无对应项的位')
    return mask


def _child_row(value: Any, index: int) -> list[Any]:
    if not isinstance(value, dict):
        return []
    rows = value.get('values')
    if not isinstance(rows, list) or index >= len(rows) or not isinstance(rows[index], list):
        return []
    return rows[index]


def _encode_group_slot(child: dict[str, Any], row: list[Any], fill: int, selected: bool) -> bytes:
    comps = child.get('component') if isinstance(child, dict) else None
    if not isinstance(comps, list):
        raise ValueError('group 项缺少 component 数组')
    parts: list[bytes] = []
    for j, comp in enumerate(comps):
        if not isinstance(comp, dict):
            raise ValueError('group 项的 component 无效')
        width = configured_component_width(comp)
        if selected:
            encoded = encode_component(comp, row[j] if j < len(row) else None)
            if len(encoded) != width:
                raise ValueError('编码长度与槽位不一致')
            parts.append(encoded)
        else:
            parts.append(bytes([fill]) * width)
    return b''.join(parts)


def encode_checkboxgroup(component: dict[str, Any], value: Any = None) -> bytes:
    """位图（大端无符号）接组合区。未选中槽位整段为填充字节。"""
    group = component.get('group')
    if not isinstance(group, list):
        raise ValueError('checkboxgroup 的 group 必须是数组')
    nbytes = _mask_byte_width(str(component.get('dataType', '')))
    bits = nbytes * 8
    if len(group) > bits:
        raise ValueError(f'group 项数 {len(group)} 超过位图位数 {bits}')
    mask = _mask_from_value(value, nbytes, len(group))
    fill = _fill_byte(component)
    slots = [
        _encode_group_slot(child, _child_row(value, i), fill, bool(mask & (1 << i)))
        for i, child in enumerate(group)
    ]
    body = b''.join(slots)
    declared = _group_data_length(component)
    if declared < 0:
        payload = body
    elif declared == 0:
        if body:
            raise ValueError('槽位总宽超过 groupDataLength')
        payload = b''
    else:
        if len(body) > declared:
            raise ValueError('槽位总宽超过 groupDataLength')
        payload = bytes([fill]) * declared
        if body:
            payload = body + payload[len(body) :]
    return mask.to_bytes(nbytes, 'big', signed=False) + payload


def encode_component(component: dict[str, Any], value: Any = None) -> bytes:
    """单组件编码；number 类型先走 formula 再按 dataType 组帧。"""
    ctype = (component.get('componentType') or 'fixed').lower()
    if ctype == 'checkboxgroup':
        return encode_checkboxgroup(component, value)
    if ctype == 'fixed':
        return _cfg_hex_to_bytes(component.get('defaultVal', ''))
    if ctype == 'number':
        # UI 输入值；formula 非空时先 exec_formula，再按 dataType 组帧（endian 默认大端）
        raw = 0 if _is_empty_value(value) else value
        encoded_val = apply_component_formula(raw, component.get('formula', ''))
        return encode_number(
            encoded_val,
            component.get('dataType', ''),
            endian=str(component.get('endian') or 'big'),
        )
    if _is_empty_value(value):
        return _zero_bytes_for_component(component)
    if ctype == 'select':
        raw = value if value is not None else component.get('defaultVal', '')
        if isinstance(raw, str) and not _clean_hex(raw):
            opts = component.get('options') or {}
            for k, label in opts.items():
                if label == raw or k == raw:
                    raw = k
                    break
        return _cfg_hex_to_bytes(str(raw))
    if ctype == 'scientific':
        dt = (component.get('dataType') or 'DOUBLE').upper()
        val = float(value if value is not None else component.get('defaultVal', 0) or 0)
        return struct.pack('>f', val) if dt == 'FLOAT' else struct.pack('>d', val)
    if ctype == 'hex':
        width = len(_clean_hex(component.get('defaultVal', '')))
        raw = _clean_hex(str(value if value is not None else component.get('defaultVal', '')))
        if width and len(raw) < width:
            raw = raw.zfill(width)
        return hex_to_bytes(raw)
    return _cfg_hex_to_bytes(str(value or ''))


calc_checksum = checksum_u8

_BROADCAST_FRAME_TYPES = {0x30, 0x1A}


def is_broadcast_hex(hex_text: str) -> bool:
    """已组 HEX 是否为广播帧类型：8 字节看首字节，更长看第 3 字节。"""
    try:
        buf = hex_to_bytes(hex_text)
        if len(buf) < 8:
            return False
        ft = buf[0] if len(buf) == 8 else buf[2]
        return ft in _BROADCAST_FRAME_TYPES
    except Exception:
        return False
