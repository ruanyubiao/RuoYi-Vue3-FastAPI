"""文件回放：本地表键 → 拆帧函数 + 字段解析类。

新增遥测表在此登记一行。未登记、又不是 BIU/XL 两位十六进制 CAN 表，
不扫描文件，错误为「不支持的遥测类型」。
实时采集不走这里，仍用会话里的 parserId。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from module_payload.cfg.can_yc_frame import verify_can_yc_frame
from module_payload.constants import split_tm_table_key
from module_payload.parsers.biu_can_tm import BiuCanTmIngest
from module_payload.parsers.xl_board_tm import SRC_TO_TABLE, XlBoardTmIngest
from module_payload.parsers.xl_camera_tm import XlCameraTmIngest
from module_payload.parsers.xl_camera_tm_v17 import XlCameraTmV17Ingest
from module_payload.parsers.xl_can_tm import XlCanTmIngest
from module_payload.parsers.xl_cpazx_tm import XlCpazxTmIngest

ExtractFn = Callable[[bytes, str], list[bytes]]
MatchFn = Callable[[bytes, str], bytes | None]

_CAN_LOCAL = re.compile(r'^[0-9A-F]{2}$')
UNSUPPORTED = '不支持的遥测类型'


@dataclass(frozen=True, slots=True)
class FilePlaySpec:
    """一种表键的文件回放拆帧与解字段。"""

    kind: str
    extract: ExtractFn
    parse: Any
    parse_span: int = 1
    match: MatchFn | None = None


def unsupported_error(table_type: str) -> str:
    return f'{UNSUPPORTED}: {table_type}'


def _as_extract(cls: Any, name: str) -> ExtractFn:
    """调用时再取类方法，测试 patch 才能作用到拆帧。"""

    def extract(buf: bytes, table_type: str) -> list[bytes]:
        return list(getattr(cls, name)(buf))

    return extract


def _board_extract(buf: bytes, table_type: str) -> list[bytes]:
    local = split_tm_table_key(table_type)[1]
    return [
        fr
        for fr in XlBoardTmIngest.extract_frames(buf)
        if XlBoardTmIngest.table_key_for_src(fr[4]) == local
    ]


def _can_match(raw: bytes, table_type: str) -> bytes | None:
    ok, _, frame = verify_can_yc_frame(raw)
    if not ok:
        return None
    local = split_tm_table_key(table_type)[1]
    if local and f'{frame[3]:02X}' != local:
        return None
    return frame


def _can_extract(buf: bytes, table_type: str) -> list[bytes]:
    out: list[bytes] = []
    i = 0
    n = len(buf)
    local = split_tm_table_key(table_type)[1]
    while i + 5 <= n:
        ok, _, frame = verify_can_yc_frame(buf[i:])
        if ok:
            if not local or f'{frame[3]:02X}' == local:
                out.append(frame)
                i += len(frame)
                continue
        i += 1
    return out


def _can_spec(parse: Any) -> FilePlaySpec:
    return FilePlaySpec(kind='can', extract=_can_extract, parse=parse, match=_can_match)


_BY_LOCAL: dict[str, FilePlaySpec] = {
    'D8': FilePlaySpec('camera_d8', _as_extract(XlCameraTmIngest, 'extract_d8_frames'), XlCameraTmIngest),
    'D8V17': FilePlaySpec('camera_d8', _as_extract(XlCameraTmIngest, 'extract_d8_frames'), XlCameraTmV17Ingest),
    'D9': FilePlaySpec(
        'camera_d9', _as_extract(XlCameraTmIngest, 'extract_d9_frames'), XlCameraTmIngest, parse_span=8
    ),
    'D9V17': FilePlaySpec(
        'camera_d9', _as_extract(XlCameraTmIngest, 'extract_d9_frames'), XlCameraTmV17Ingest, parse_span=8
    ),
    'CPAZX': FilePlaySpec('cpazx', _as_extract(XlCpazxTmIngest, 'extract_frames'), XlCpazxTmIngest),
}
for _board_key in SRC_TO_TABLE.values():
    _BY_LOCAL[_board_key] = FilePlaySpec('board', _board_extract, XlBoardTmIngest)


def resolve_fileplay(table_type: str) -> FilePlaySpec | None:
    """表键 → 拆帧规格。字典优先；其余 BIU/XL 两位十六进制走 CAN。"""
    fam, local = split_tm_table_key(table_type)
    spec = _BY_LOCAL.get(local)
    if spec is not None:
        return spec
    if fam in ('biu', 'xl') and _CAN_LOCAL.fullmatch(local or ''):
        return _can_spec(XlCanTmIngest if fam == 'xl' else BiuCanTmIngest)
    return None
