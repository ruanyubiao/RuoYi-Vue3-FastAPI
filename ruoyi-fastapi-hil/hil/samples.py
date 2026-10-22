"""样本加载：遥测黄金样本、遥控黄金样例、CAN 收包 txt。"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from hil.config import CONFIG

_LINE_RE = re.compile(r'^\s*(\d+)\s+([0-9A-Fa-f]+)\s*\[([0-9A-Fa-f\s]*)\]')


def hex_to_bytes(s: str) -> bytes:
    return bytes.fromhex(re.sub(r'0x|[\s,]', '', s, flags=re.I))


def bytes_to_hex(b: bytes) -> str:
    return ' '.join(f'{x:02X}' for x in b)


@lru_cache
def tm_goldens() -> dict:
    return json.loads(Path(CONFIG.tm_golden_path).read_text(encoding='utf-8'))


@lru_cache
def tc_goldens() -> dict:
    return json.loads(Path(CONFIG.tc_golden_path).read_text(encoding='utf-8'))


def get_hex(key: str) -> str:
    """先查遥测黄金样本，再查遥控黄金样例。"""
    for src in (tm_goldens(), tc_goldens()):
        if key in src:
            return src[key]['hex']
    raise KeyError(f'样本 key 不存在: {key}')


def get_bytes(key: str) -> bytes:
    return hex_to_bytes(get_hex(key))


def tm_table_key(key: str) -> str:
    """遥测样本对应的遥测表存储键，如 BIU:FF / D8 / RKDJ。"""
    return tm_goldens()[key]['result']['table_key']


def tm_fields(key: str) -> list[dict]:
    """遥测样本期望字段：[{id,name,show,hex,...}]"""
    return list(tm_goldens()[key]['result'].get('fields') or [])


def iter_can_frames(path: str | Path | None = None) -> Iterator[tuple[str, int, bytes]]:
    """解析 `时间戳 帧ID [字节...]`，产出 (timestamp, can_id, data)。"""
    p = Path(path or CONFIG.can_recv_txt)
    with p.open(encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = _LINE_RE.match(line)
            if m:
                yield m.group(1), int(m.group(2), 16), hex_to_bytes(m.group(3))


def split_to_can_frames(data: bytes, can_id: int, size: int = 8) -> list[tuple[int, bytes]]:
    """把长报文按 8 字节切成 CAN 帧（不带协议帧标志，仅 dry-run 用）。"""
    return [(can_id, data[i:i + size]) for i in range(0, len(data), size)]
