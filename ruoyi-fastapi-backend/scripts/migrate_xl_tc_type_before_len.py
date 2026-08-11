"""One-shot: migrate XL board TeleControlCfg complex frames to type-before-len."""

from __future__ import annotations

import json
import re
from pathlib import Path


def clean_hex(text: str) -> str:
    s = (text or '').strip()
    if s.lower().startswith('0x'):
        s = s[2:]
    return re.sub(r'[^0-9A-Fa-f]', '', s)


def to_hex_pref(b: bytes, prefer_0x: bool) -> str:
    h = b.hex().upper()
    return ('0x' + h) if prefer_0x else h


def migrate_fixed_complex(default_val: str) -> str | None:
    hx = clean_hex(default_val)
    if len(hx) < 14 or len(hx) % 2:
        return None
    b = bytearray.fromhex(hx)
    if b[0:2] != bytes([0xEB, 0x90]) or len(b) <= 8:
        return None
    # old: EB90 | len | 0F | rest | chk?
    if b[4] != 0x0F:
        return None
    old_len = (b[2] << 8) | b[3]
    has_chk = len(b) == 2 + 2 + old_len + 1
    payload = bytes(b[5:-1] if has_chk else b[5:])
    new_len = len(payload)
    body = bytearray([0xEB, 0x90, 0x0F, (new_len >> 8) & 0xFF, new_len & 0xFF]) + payload
    if has_chk:
        body.append(sum(body[2:]) & 0xFF)
    prefer_0x = default_val.strip().lower().startswith('0x')
    return to_hex_pref(bytes(body), prefer_0x)


def migrate_multi(comps: list[dict]) -> bool:
    if len(comps) < 3:
        return False
    v0 = clean_hex(comps[0].get('defaultVal', ''))
    v1 = clean_hex(comps[1].get('defaultVal', ''))
    v2 = clean_hex(comps[2].get('defaultVal', ''))
    if v0.upper() != 'EB90' or len(v1) != 4 or not v2:
        return False
    if len(v1) == 2 and int(v1, 16) == 0x0F:
        return False
    if not v2.upper().startswith('0F'):
        return False
    old_len = int(v1, 16)
    new_len = max(0, old_len - 1)
    rest = v2[2:]
    prefer = comps[2].get('defaultVal', '').strip().lower().startswith('0x')
    new_comps = [
        comps[0],
        {
            'title': '固定值',
            'componentType': 'fixed',
            'dataType': '',
            'unit': '',
            'minVal': '',
            'maxVal': '',
            'defaultVal': '0x0F',
            'options': {},
        },
        {
            'title': '固定值',
            'componentType': 'fixed',
            'dataType': '',
            'unit': '',
            'minVal': '',
            'maxVal': '',
            'defaultVal': f'0x{new_len:04X}',
            'options': {},
        },
        {**comps[2], 'defaultVal': ('0x' + rest) if prefer else rest},
    ] + comps[3:]
    comps.clear()
    comps.extend(new_comps)
    return True


def main() -> None:
    root = Path(__file__).resolve().parents[1] / 'assets' / 'config'
    for name in ('XL-RKDJ-TeleControlCfg.json', 'XL-ZK-TeleControlCfg.json'):
        path = root / name
        cfg = json.loads(path.read_text(encoding='utf-8'))
        changed = 0
        for oid, order in (cfg.get('order') or {}).items():
            comps = order.get('component') or []
            if len(comps) == 1:
                nv = migrate_fixed_complex(comps[0].get('defaultVal', ''))
                if nv is not None and nv != comps[0].get('defaultVal'):
                    print(f'{name} {oid} FIXED {comps[0]["defaultVal"]} -> {nv}')
                    comps[0]['defaultVal'] = nv
                    changed += 1
            else:
                before = [c.get('defaultVal') for c in comps[:3]]
                if migrate_multi(comps):
                    after = [c.get('defaultVal') for c in comps[:4]]
                    print(f'{name} {oid} MULTI {before} -> {after}')
                    order['component'] = comps
                    changed += 1
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=4) + '\n', encoding='utf-8')
        print(f'wrote {name} changed={changed}')


if __name__ == '__main__':
    main()
