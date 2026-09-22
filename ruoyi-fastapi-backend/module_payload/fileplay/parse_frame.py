"""文件回放：按表类型解析一帧为表格 JSON（不写 ``payload:tm:*``）。

hex 文本行先抽 HEX 再校验复合帧；bin 按 offset/length 切片。
D9 需拼最近最多 8 包再交给相机 ingest（与实时流一致）。

与硬件采集同一套解析：本模块只做「读文件 → 调 ingest.parse_bytes」；
单板走 XlBoardTmIngest，相机/CAN 同理。硬件走 ingest_bytes_sync，
数据模拟走 ingest_bytes_async；拆帧与 TeleMetryCfg 字段不在此重复实现。
"""

from __future__ import annotations

from typing import Any

from module_payload.fileplay.detect import FrameRef, FileIndex, fields_to_rows, frame_data_ts_ms
from module_payload.fileplay.registry import resolve_fileplay, unsupported_error


def _load_raw(idx: FileIndex, ref: FrameRef) -> bytes:
    """取帧原始字节：优先缓存，否则从文件切片。"""
    if ref.raw:
        return ref.raw
    data = Path_read(idx.path, ref.offset, ref.length)
    if idx.kind == 'hex':
        from module_payload.cfg.hex_text import hex_to_bytes
        from module_payload.fileplay.detect import _BRACKET_HEX_RE, _CAN_LINE_RE, _match_raw_frame

        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            text = data.decode('latin-1', errors='ignore')
        m = _CAN_LINE_RE.match(text.rstrip('\r\n'))
        hex_part = m.group(3) if m else ''
        if not hex_part:
            bm = _BRACKET_HEX_RE.search(text)
            hex_part = bm.group(1) if bm else text.strip()
        raw = hex_to_bytes(hex_part)
        matched = _match_raw_frame(raw, idx.table_type)
        return matched or raw
    return data


def Path_read(path: str, offset: int, length: int) -> bytes:
    """按 FrameRef 的 offset/length 从文件读一块（精确扫描后 raw 常为空）。"""
    with open(path, 'rb') as fp:
        fp.seek(offset)
        return fp.read(length)


def parse_frame(idx: FileIndex, frame_index: int) -> dict[str, Any]:
    """解析第 ``frame_index`` 帧（1-based）为遥测表快照。

    委托各 ingest 的 parse_bytes（与硬件 ingest_bytes_sync 同源 cfg），
    仅组装 fileplay 前端 JSON，不写实时遥测键。
    """
    if frame_index < 1 or frame_index > len(idx.frames):
        raise IndexError(f'帧序号超出范围: {frame_index}/{len(idx.frames)}')
    spec = resolve_fileplay(idx.table_type)
    if spec is None:
        raise ValueError(unsupported_error(idx.table_type))
    ref = idx.frames[frame_index - 1]
    if spec.parse_span > 1:
        start = max(1, frame_index - (spec.parse_span - 1))
        blob = b''.join(_load_raw(idx, idx.frames[i - 1]) for i in range(start, frame_index + 1))
        parsed = spec.parse.parse_bytes(blob)
    else:
        parsed = spec.parse.parse_bytes(_load_raw(idx, ref))
    fields = parsed.fields
    name = parsed.name
    raw_len = len(parsed.raw_frame)
    rows = fields_to_rows(fields)
    ts_ms = frame_data_ts_ms(idx, frame_index, ref)
    return {
        'type': idx.table_type,
        'name': name,
        'rows': rows,
        'tsMs': ts_ms,
        'ts': _fmt_ts(ts_ms),
        'dataSource': idx.path,
        'frameIndex': frame_index,
        'rawLen': raw_len,
    }


def _fmt_ts(ts_ms: int) -> str:
    """毫秒时间戳 → ``YYYY-MM-DD HH:MM:SS.mmm``；0 表示无数据时间。"""
    from datetime import datetime

    if not ts_ms:
        return ''
    dt = datetime.fromtimestamp(ts_ms / 1000.0)
    ms = int(ts_ms) % 1000
    return dt.strftime('%Y-%m-%d %H:%M:%S') + f'.{ms:03d}'
