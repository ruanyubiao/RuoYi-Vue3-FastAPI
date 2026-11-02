"""CAN 硬件帧文本：模拟页「CAN-* 组装器」输入格式。

每行一帧（空行 / ``#`` 注释忽略），三种等价写法：

1. ``779  00 25 3A FF 03 02 01 11``
2. ``00000779  [00 25 3A FF 03 02 01 11]``
3. ``20261029101019 00000779  [00 25 3A FF 03 02 01 11]``（可选时间前缀，解析时去掉）

ID 支持短写 / 8 位补零 / ``0x``；与数据之间空白不限（可无空白）。
数据可带或不带 ``[]``；括号内外空白不限。
数据 token 规则与 ``hex_text.hex_to_bytes`` 相同。
"""

from __future__ import annotations

import re
from typing import Any

from module_payload.cfg.hex_text import hex_to_bytes

# 采集日志时间：YYYYMMDDHHmmss，仅作前缀，不参与组帧
_TS_RE = re.compile(r'^(\d{14})\s+(.*)$')
_LINE_RE = re.compile(r'^(?:0x)?([0-9a-fA-F]+)(.*)$', re.IGNORECASE)


def _strip_optional_timestamp(line: str) -> str:
    m = _TS_RE.match(line)
    return m.group(2).strip() if m else line


def _data_hex_text(raw: str) -> str:
    """数据段；整段可选 ``[...]`` 包围，括号内外空白不限。"""
    s = str(raw or '').strip()
    if len(s) >= 2 and s[0] == '[' and s[-1] == ']':
        s = s[1:-1].strip()
    return s


def parse_can_frame_text(text: str) -> list[Any]:
    """解析为 gpcan ``CanRecvObj`` 列表；非法格式抛 ``ValueError``。"""
    from gpcan.sdk.can_sdk_def import CanRecvObj

    raw = str(text or '')
    if not raw.strip():
        raise ValueError('CAN 帧文本为空')

    frames: list[Any] = []
    for i, line in enumerate(raw.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        s = _strip_optional_timestamp(s)
        m = _LINE_RE.match(s)
        if not m:
            raise ValueError(f'第{i}行格式错误，需要: [时间] CAN_ID DATA_HEX...')
        un_id = int(m.group(1), 16) & 0x1FFFFFFF
        data_raw = _data_hex_text(m.group(2))
        if not data_raw:
            raise ValueError(f'第{i}行格式错误，需要: [时间] CAN_ID DATA_HEX...')
        try:
            data = hex_to_bytes(data_raw)
        except ValueError as e:
            raise ValueError(f'第{i}行数据 HEX 非法: {e}') from e
        if not data:
            raise ValueError(f'第{i}行数据为空')
        if len(data) > 8:
            raise ValueError(f'第{i}行数据超过 8 字节（经典 CAN）: {len(data)}')
        frames.append(
            CanRecvObj(
                un_id=un_id,
                str_data=data,
                un_data_len=len(data),
            )
        )

    if not frames:
        raise ValueError('未解析到 CAN 帧（每行: [时间] CAN_ID + 数据 HEX）')
    return frames
