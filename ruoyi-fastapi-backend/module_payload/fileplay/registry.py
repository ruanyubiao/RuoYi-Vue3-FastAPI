"""文件回放：本地表键 → 拆帧函数 + 字段解析类。

规格由各协议的 ``BINDINGS`` 提供：非总线表查 ``fileplay_tables``；总线两位十六进制表查该族的
``fileplay``，没给时按该族的 ``verify_tm`` 滑动扫描（帧形状：2 字节长度 + 帧类型 + 表号）。
未登记的表键不扫描文件，错误为「不支持的遥测类型」。
实时采集不走这里，仍用会话里的 parserId。
"""

from __future__ import annotations

import re
from typing import Any

from module_payload.constants import split_tm_table_key
from module_payload.protocol.hooks import ExtractFn, FilePlaySpec, MatchFn
from module_payload.protocol.registry import bus_bindings, fileplay_tables
from module_payload.protocol.protocol_catalog import is_bus_family

__all__ = ['UNSUPPORTED', 'FilePlaySpec', 'resolve_fileplay', 'unsupported_error']

_CAN_LOCAL = re.compile(r'^[0-9A-F]{2}$')
_TABLE_ID_AT = 3  # 默认帧形状里表号的下标
UNSUPPORTED = '不支持的遥测类型'


def unsupported_error(table_type: str) -> str:
    return f'{UNSUPPORTED}: {table_type}'


def _bus_can_match(verify: Any) -> MatchFn:
    """用该协议自己的校验从一段字节里认出一帧。"""

    def match(raw: bytes, table_type: str) -> bytes | None:
        ok, _, frame = verify(raw)
        if not ok:
            return None
        local = split_tm_table_key(table_type)[1]
        if local and f'{frame[_TABLE_ID_AT]:02X}' != local:
            return None
        return frame

    return match


def _bus_can_extract(verify: Any) -> ExtractFn:
    """滑动扫描，按该协议的校验切出遥测帧。"""

    def extract(buf: bytes, table_type: str) -> list[bytes]:
        out: list[bytes] = []
        i = 0
        n = len(buf)
        local = split_tm_table_key(table_type)[1]
        while i + 5 <= n:
            ok, _, frame = verify(buf[i:])
            if ok:
                if not local or f'{frame[_TABLE_ID_AT]:02X}' == local:
                    out.append(frame)
                    i += len(frame)
                    continue
            i += 1
        return out

    return extract


def _can_spec(parse: Any, verify: Any) -> FilePlaySpec:
    return FilePlaySpec(
        kind='can',
        extract=_bus_can_extract(verify),
        parse=parse,
        match=_bus_can_match(verify),
    )


def resolve_fileplay(table_type: str) -> FilePlaySpec | None:
    """表键 → 拆帧规格。非总线表优先；其余按总线族的钩子。"""
    fam, local = split_tm_table_key(table_type)
    spec = fileplay_tables().get(local)
    if spec is not None:
        return spec
    if not is_bus_family(fam) or not _CAN_LOCAL.fullmatch(local or ''):
        return None
    bindings = bus_bindings(fam)
    if bindings.fileplay is not None:
        return bindings.fileplay
    if bindings.verify_tm is None or bindings.ingest is None:
        return None
    return _can_spec(bindings.ingest, bindings.verify_tm)
