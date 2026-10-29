"""CAN 硬件帧文本：模拟页「CAN-* 组装器」输入格式。

每行一帧：``CAN_ID DATA_HEX...``（空行 / ``#`` 注释忽略）。
ID 支持 ``4FF`` / ``0x4FF``；数据段规则与 ``hex_text.hex_to_bytes`` 相同。
"""

from __future__ import annotations

import re
from typing import Any

from module_payload.cfg.hex_text import hex_to_bytes

_ID_RE = re.compile(r'^(?:0x)?([0-9a-fA-F]+)$')


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
        parts = s.split()
        if len(parts) < 2:
            raise ValueError(f'第{i}行格式错误，需要: CAN_ID DATA_HEX...')
        m = _ID_RE.match(parts[0])
        if not m:
            raise ValueError(f'第{i}行 CAN_ID 非法: {parts[0]!r}')
        un_id = int(m.group(1), 16) & 0x1FFFFFFF
        try:
            data = hex_to_bytes(' '.join(parts[1:]))
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
        raise ValueError('未解析到 CAN 帧（每行: CAN_ID + 数据 HEX）')
    return frames
