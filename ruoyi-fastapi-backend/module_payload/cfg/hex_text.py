"""HEX 文本解析：与前端 ``payloadRawData.js`` 对齐。

空白（空格 / Tab / 换行）是 token 分隔符，不是可忽略字符。
每个 token 独立成对；奇数位时在末半字节前补 ``0``。

例：``A B`` → ``0A 0B``（不是 ``AB``）；``aabbc`` → ``AA BB 0C``。
"""

from __future__ import annotations

import re

_HEX_TOKEN_RE = re.compile(r'^[0-9a-fA-F]+$')


def hex_tokens(text: str) -> list[str]:
    if not text:
        return []
    return str(text).split()


def pad_odd_hex(cleaned: str) -> str:
    if not cleaned:
        return ''
    if len(cleaned) % 2 == 0:
        return cleaned
    return cleaned[:-1] + '0' + cleaned[-1]


def normalize_hex_pairs(text: str) -> list[str] | None:
    """返回大写双字符列表；非法 token 返回 ``None``；空输入返回 ``[]``。"""
    tokens = hex_tokens(text)
    if not tokens:
        return []
    pairs: list[str] = []
    for token in tokens:
        if not _HEX_TOKEN_RE.match(token):
            return None
        padded = pad_odd_hex(token)
        for i in range(0, len(padded), 2):
            pairs.append(padded[i : i + 2].upper())
    return pairs


def normalize_hex_display(text: str) -> str:
    pairs = normalize_hex_pairs(text)
    if not pairs:
        return ''
    return ' '.join(pairs)


def hex_to_bytes(text: str) -> bytes:
    pairs = normalize_hex_pairs(text)
    if pairs is None:
        raise ValueError('HEX 含非法字符')
    if not pairs:
        return b''
    return bytes(int(p, 16) for p in pairs)
