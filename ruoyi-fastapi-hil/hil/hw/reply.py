"""自定义应答规则（scenarios/reply_map.json 的 custom_rules）：收到以 match_hex_prefix 开头的数据即回 reply_hex。
协议能确定的应答已由 hil/protocol/* 内置；这里只放协议代码里没有定义、需用户补充的规则。"""
from __future__ import annotations

import json
from pathlib import Path

from hil.samples import hex_to_bytes


class ReplyMap:
    def __init__(self, rules: list[dict]) -> None:
        self.rules = []
        for r in rules:
            if not r.get('enabled', True) or not r.get('reply_hex'):
                continue
            self.rules.append({**r, '_prefix': hex_to_bytes(r['match_hex_prefix']), '_reply': hex_to_bytes(r['reply_hex'])})

    @classmethod
    def load(cls, path: str | Path) -> 'ReplyMap':
        p = Path(path)
        if not p.exists():
            return cls([])
        data = json.loads(p.read_text(encoding='utf-8'))
        rules = data.get('custom_rules', data.get('rules', [])) if isinstance(data, dict) else data
        return cls(rules)

    def for_target(self, target: str) -> list[dict]:
        """target: CAN 族名（biu/xl/yj216）或串口/UDP 设备键（xl-rkdj 等）。"""
        return [r for r in self.rules if r.get('target') in (None, target)]

    def match(self, data: bytes, target: str | None = None) -> dict | None:
        for r in self.rules:
            if target and r.get('target') not in (None, target):
                continue
            if data.startswith(r['_prefix']):
                return r
        return None
