"""文件回放：hex/bin 侦测、拆帧索引（不写实时 ``payload:tm:*``）。

hex：CAN recv 文本行（时间戳 + id 列 + [HEX]）。
bin：串口/UDP 落盘流，滑动校验或相机/单板 extract。
``index_file(..., force_estimate=True)`` 只收首帧并按文件大小估总帧数，供引擎先 ready。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from module_payload.cfg.can_yc_frame import verify_can_yc_frame
from module_payload.cfg.hex_text import hex_to_bytes
from module_payload.constants import split_tm_table_key
from module_payload.parsers.xl_camera_tm import XlCameraTmIngest
from module_payload.parsers.xl_board_tm import SRC_TO_TABLE, XlBoardTmIngest

# 小于该大小开局即精确计帧；超过则先按「文件大小/首帧长度」预估
EXACT_COUNT_MAX_BYTES = 100 * 1024 * 1024

# CAN recv 文本行：YYYYMMDDHHMMSS + 8 字符 id 列 + [HEX]
_CAN_LINE_RE = re.compile(
    r'^(\d{14})\s(.{8})\s\[([0-9A-Fa-f ]+)\]',
)
_BRACKET_HEX_RE = re.compile(r'\[([0-9A-Fa-f ]+)\]')
# 落盘文件名：YYYYMMDD_HHMMSS_mmm（与采集命名一致）
_RECV_STAMP_RE = re.compile(r'(\d{8})_(\d{6})_(\d{1,3})')
FRAME_INTERVAL_MS = 1000


@dataclass(slots=True)
class FrameRef:
    """一帧在文件中的定位（1-based 由列表下标+1 表示）。"""

    offset: int  # 文件字节偏移（该行/块起点）
    length: int  # 从 offset 起读取长度
    ts_ms: int = 0  # 行内时间戳；bin 流多为 0
    raw: bytes | None = None  # 小文件扫描时可缓存完整帧


@dataclass
class FileIndex:
    """一份回放文件的拆帧结果。

    frames           1-based 序号 = 下标+1；预估模式下可能只有首帧
    frame_count      展示用总数；预估时可能大于 len(frames)
    frame_count_exact  False 时前端滑块标「预估」，后台 finalize 后改 True
    """

    path: str
    table_type: str
    kind: str  # hex | bin
    size: int
    frames: list[FrameRef] = field(default_factory=list)
    frame_count: int = 0
    frame_count_exact: bool = False
    first_frame_len: int = 0
    has_timestamp: bool = False
    error: str = ''
    start_ts_ms: int = 0  # 文件名解析的起始时刻；0 表示没有


def parse_recv_file_start_ms(path: str | Path) -> int:
    """从文件名解析 ``YYYYMMDD_HHMMSS_mmm`` 为本地毫秒时间戳；解析不到返回 0。"""
    name = Path(path).name
    m = _RECV_STAMP_RE.search(name)
    if not m:
        return 0
    ymd, hms, frac = m.group(1), m.group(2), m.group(3)
    try:
        ms = int(str(frac).ljust(3, '0')[:3])
        dt = datetime(
            int(ymd[0:4]),
            int(ymd[4:6]),
            int(ymd[6:8]),
            int(hms[0:2]),
            int(hms[2:4]),
            int(hms[4:6]),
            ms * 1000,
        )
        return int(dt.timestamp() * 1000)
    except ValueError:
        return 0


def frame_data_ts_ms(idx: FileIndex, frame_index: int, ref: FrameRef | None = None) -> int:
    """第 n 帧数据时间：有文件名起始则 start+(n-1)*1s，否则用行内时间。"""
    n = max(1, int(frame_index or 1))
    if idx.start_ts_ms:
        return idx.start_ts_ms + (n - 1) * FRAME_INTERVAL_MS
    if ref is not None and ref.ts_ms:
        return int(ref.ts_ms)
    return 0


def detect_file_kind(path: str | Path, sample: bytes | None = None) -> str:
    """自判 hex 文本（CAN recv .txt）或 bin 流（串口/UDP .bin）。"""
    p = Path(path)
    suffix = p.suffix.lower()
    if sample is None:
        try:
            with p.open('rb') as fp:
                sample = fp.read(4096)
        except OSError:
            sample = b''
    if not sample:
        return 'hex' if suffix == '.txt' else 'bin'
    if b'\x00' in sample[:512]:
        return 'bin'
    text_ratio = sum(1 for b in sample if 32 <= b <= 126 or b in (9, 10, 13)) / max(len(sample), 1)
    if suffix == '.bin':
        return 'bin' if text_ratio < 0.85 else 'hex'
    if suffix == '.txt' or text_ratio >= 0.85:
        return 'hex'
    return 'bin'


def _parse_line_ts_ms(stamp: str) -> int:
    """YYYYMMDDHHMMSS → 毫秒（秒级，毫秒为 0）。"""
    try:
        dt = datetime.strptime(stamp, '%Y%m%d%H%M%S')
        return int(dt.timestamp() * 1000)
    except ValueError:
        return 0


def _local_key(table_type: str) -> str:
    return split_tm_table_key(table_type)[1]


def ingest_kind(table_type: str) -> str:
    """表类型对应拆帧策略：can / camera_d8 / camera_d9 / board。"""
    local = _local_key(table_type)
    if local == 'D8':
        return 'camera_d8'
    if local == 'D9':
        return 'camera_d9'
    if local in SRC_TO_TABLE.values():
        return 'board'
    return 'can'


def _can_frame_ok(raw: bytes, table_type: str) -> bytes | None:
    """校验 CAN 复合帧且 dataType 匹配表本地 key。"""
    ok, _, frame = verify_can_yc_frame(raw)
    if not ok:
        return None
    local = _local_key(table_type)
    if local and f'{frame[3]:02X}' != local:
        return None
    return frame


def iter_hex_frames(path: str | Path, table_type: str):
    """逐行提取 hex 文本中的完整遥测帧（组包完成行才能通过复合帧校验）。"""
    p = Path(path)
    offset = 0
    kind = ingest_kind(table_type)
    with p.open('rb') as fp:
        for line in fp:
            start = offset
            offset += len(line)
            try:
                text = line.decode('utf-8')
            except UnicodeDecodeError:
                text = line.decode('latin-1', errors='ignore')
            m = _CAN_LINE_RE.match(text.rstrip('\r\n'))
            hex_part = ''
            ts_ms = 0
            if m:
                ts_ms = _parse_line_ts_ms(m.group(1))
                hex_part = m.group(3)
            else:
                bm = _BRACKET_HEX_RE.search(text)
                if bm:
                    hex_part = bm.group(1)
                elif re.fullmatch(r'[0-9A-Fa-f][0-9A-Fa-f\s]*', text.strip() or ''):
                    hex_part = text.strip()
            if not hex_part:
                continue
            try:
                raw = hex_to_bytes(hex_part)
            except ValueError:
                continue
            frame = _match_raw_frame(raw, table_type, kind)
            if frame is None:
                continue
            yield FrameRef(offset=start, length=len(line), ts_ms=ts_ms, raw=frame)


def _match_raw_frame(raw: bytes, table_type: str, kind: str) -> bytes | None:
    """单段原始字节是否为一帧目标表数据。"""
    if kind == 'can':
        return _can_frame_ok(raw, table_type)
    if kind == 'camera_d8':
        frames = XlCameraTmIngest.extract_d8_frames(raw)
        return frames[0] if frames else (raw if len(raw) >= 8 and raw[:2] == b'\xeb\x90' else None)
    if kind == 'camera_d9':
        frames = XlCameraTmIngest.extract_d9_frames(raw)
        return frames[0] if frames else None
    if kind == 'board':
        frames = XlBoardTmIngest.extract_frames(raw)
        local = _local_key(table_type)
        for fr in frames:
            if XlBoardTmIngest.table_key_for_src(fr[4]) == local:
                return fr
        return None
    return None


def iter_bin_frames(path: str | Path, table_type: str, *, keep_raw: bool = True):
    """从 bin 流拆出完整帧（粘包友好，整文件读入后提取）。"""
    p = Path(path)
    data = p.read_bytes()
    kind = ingest_kind(table_type)
    frames: list[bytes] = []
    if kind == 'camera_d8':
        frames = XlCameraTmIngest.extract_d8_frames(data)
    elif kind == 'camera_d9':
        frames = XlCameraTmIngest.extract_d9_frames(data)
    elif kind == 'board':
        local = _local_key(table_type)
        frames = [
            fr
            for fr in XlBoardTmIngest.extract_frames(data)
            if XlBoardTmIngest.table_key_for_src(fr[4]) == local
        ]
    else:
        frames = list(_scan_can_frames(data, table_type))
    pos = 0
    for fr in frames:
        idx = data.find(fr, pos)
        if idx < 0:
            idx = pos
        yield FrameRef(
            offset=idx,
            length=len(fr),
            ts_ms=0,
            raw=fr if keep_raw else None,
        )
        pos = idx + len(fr)


def _scan_can_frames(data: bytes, table_type: str):
    """在二进制缓冲中滑动校验 CAN 复合帧。"""
    i = 0
    n = len(data)
    while i + 5 <= n:
        ok, _, frame = verify_can_yc_frame(data[i:])
        if ok:
            local = _local_key(table_type)
            if not local or f'{frame[3]:02X}' == local:
                yield frame
                i += len(frame)
                continue
        i += 1


def _first_bin_frame(path: Path, table_type: str) -> FrameRef | None:
    """超长 bin：分块搜首帧，避免整文件读入。"""
    kind = ingest_kind(table_type)
    overlap = 65536
    buf = b''
    file_off = 0
    chunk = 256 * 1024
    with path.open('rb') as fp:
        while True:
            data = fp.read(chunk)
            if not data:
                break
            buf += data
            frames: list[bytes] = []
            if kind == 'camera_d8':
                frames = XlCameraTmIngest.extract_d8_frames(buf)
            elif kind == 'camera_d9':
                frames = XlCameraTmIngest.extract_d9_frames(buf)
            elif kind == 'board':
                local = _local_key(table_type)
                frames = [
                    fr
                    for fr in XlBoardTmIngest.extract_frames(buf)
                    if XlBoardTmIngest.table_key_for_src(fr[4]) == local
                ]
            else:
                frames = list(_scan_can_frames(buf, table_type))
            if frames:
                fr = frames[0]
                rel = buf.find(fr)
                if rel < 0:
                    rel = 0
                return FrameRef(offset=file_off + rel, length=len(fr), ts_ms=0, raw=fr)
            if len(buf) > chunk + overlap:
                drop = len(buf) - overlap
                file_off += drop
                buf = buf[-overlap:]
    return None


def estimate_frame_count(file_size: int, first_frame_len: int) -> int:
    """超长文件预估帧数：文件大小 / 首帧长度，至少 1。"""
    if first_frame_len <= 0:
        return 1
    return max(1, file_size // first_frame_len)


def _iter_frames(path: Path, table_type: str, kind: str, *, keep_raw: bool):
    """按 hex/bin 产出 FrameRef；keep_raw=False 时精确扫描为省内存不缓存 raw。"""
    if kind == 'hex':
        yield from iter_hex_frames(path, table_type)
    else:
        yield from iter_bin_frames(path, table_type, keep_raw=keep_raw)


def index_file(
    path: str | Path,
    table_type: str,
    *,
    exact_max_bytes: int = EXACT_COUNT_MAX_BYTES,
    force_estimate: bool = False,
) -> FileIndex:
    """拆帧并给出 frameCount。

    默认：文件 ≤ 100MB 且未 force_estimate → 一次扫完，frame_count_exact=True。
    force_estimate 或超长文件：只定位首帧，frame_count = size // 首帧长（至少 1）。
    引擎默认走预估，避免大日志卡死 parse 接口。
    """
    p = Path(path)
    table_type = (table_type or '').upper()
    idx = FileIndex(path=str(p), table_type=table_type, kind='bin', size=0)
    if not p.is_file():
        idx.error = '文件不存在'
        return idx
    idx.size = p.stat().st_size
    idx.kind = detect_file_kind(p)
    idx.start_ts_ms = parse_recv_file_start_ms(p)
    use_exact = (idx.size <= exact_max_bytes) and not force_estimate
    if use_exact:
        frames = list(_iter_frames(p, table_type, idx.kind, keep_raw=True))
        if not frames:
            idx.error = '未找到匹配遥测类型的完整帧'
            idx.frame_count = 0
            idx.frame_count_exact = True
            return idx
        idx.frames = frames
        idx.first_frame_len = len(frames[0].raw or b'') or frames[0].length
        idx.frame_count = len(frames)
        idx.frame_count_exact = True
        idx.has_timestamp = bool(idx.start_ts_ms) or any(f.ts_ms > 0 for f in frames)
        return idx

    first: FrameRef | None = None
    if idx.kind == 'bin':
        first = _first_bin_frame(p, table_type)
    else:
        for ref in iter_hex_frames(p, table_type):
            first = ref
            break
    if first is None:
        idx.error = '未找到匹配遥测类型的完整帧'
        idx.frame_count = 0
        idx.frame_count_exact = True
        return idx
    idx.frames = [first]
    idx.first_frame_len = len(first.raw or b'') or first.length
    idx.frame_count = estimate_frame_count(idx.size, idx.first_frame_len)
    idx.frame_count_exact = False
    idx.has_timestamp = bool(idx.start_ts_ms) or first.ts_ms > 0
    return idx


def finalize_exact_index(idx: FileIndex) -> FileIndex:
    """把预估会话改为精确帧列表（超长文件扫完后调用）。"""
    pending = list(_iter_frames(Path(idx.path), idx.table_type, idx.kind, keep_raw=False))
    idx.frames = pending
    idx.frame_count = len(pending)
    idx.frame_count_exact = True
    idx.has_timestamp = bool(idx.start_ts_ms) or any(f.ts_ms > 0 for f in idx.frames)
    return idx


def fields_to_rows(fields: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """TeleMetryParser 字段列表 → 遥测表行。"""
    rows: list[dict[str, Any]] = []
    for f in fields or []:
        rows.append(
            {
                'id': f.get('id', ''),
                'name': f.get('name', ''),
                'value': f.get('value', f.get('show', '')),
                'show': f.get('show', f.get('value', '')),
                'unit': f.get('unit', ''),
                'hex': f.get('hex', ''),
            }
        )
    return rows
