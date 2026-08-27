"""JSON 编解码（无 Redis）。采集/解释器/错误存储共用，避免 parsers 依赖 collectors。"""

from __future__ import annotations

import json
from typing import Any


def dumps_json(data: Any) -> str:
    """JSON 序列化（保留中文）。"""
    return json.dumps(data, ensure_ascii=False)


def loads_json(text: str | None) -> Any:
    """JSON 反序列化；空串返回 None。"""
    if not text:
        return None
    return json.loads(text)
