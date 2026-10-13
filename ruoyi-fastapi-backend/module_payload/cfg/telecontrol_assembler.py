"""遥控组件编码。各总线族的组帧规则在各自的 *_telecontrol_assembler 里。"""

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


def encode_component(component: dict[str, Any], value: Any = None) -> bytes:
    """单组件编码；number 类型先走 formula 再按 dataType 组帧。"""
    ctype = (component.get('componentType') or 'fixed').lower()
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
