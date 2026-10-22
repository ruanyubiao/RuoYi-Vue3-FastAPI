# -*- coding: utf-8 -*-
"""闭环黄金样例：加载 scenarios/goldens/*.json，对比 hex/字段，生成缺黄金 skip 原因。

发遥控必须走 UI（Playwright 点「发送指令」等）；本模块只提供数据与断言辅助，不下发。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hil.config import BACKEND_ROOT, HIL_ROOT
from hil.samples import hex_to_bytes, bytes_to_hex

GOLDENS_DIR = HIL_ROOT / 'scenarios' / 'goldens'
CFG_DIR = BACKEND_ROOT / 'assets' / 'config'


def norm_hex(s: str | None) -> str:
    if not s:
        return ''
    return ' '.join(f'{b:02X}' for b in hex_to_bytes(s))


def hex_diff(expect: str | bytes, actual: str | bytes) -> str:
    eh = norm_hex(expect if isinstance(expect, str) else bytes_to_hex(expect))
    ah = norm_hex(actual if isinstance(actual, str) else bytes_to_hex(actual))
    if eh == ah:
        return 'OK'
    return f'expect={eh or "(empty)"} actual={ah or "(empty)"}'


def fields_diff(expect: list[dict], actual: dict[str, str], exclude: set[str] | None = None) -> dict[str, tuple[str, str]]:
    """expect: tm_golden fields [{id,show,...}]；actual: {id: show}。返回不匹配 {id:(want,got)}。"""
    bad: dict[str, tuple[str, str]] = {}
    ex = exclude or set()
    for f in expect:
        fid = str(f.get('id') or '')
        if not fid or fid in ex:
            continue
        want = str(f.get('show', ''))
        got = str(actual.get(fid, ''))
        if want != got:
            bad[fid] = (want, got)
    return bad


@dataclass
class GoldenCase:
    """单条闭环用例。"""
    protocol: str
    case_id: str
    order_id: str
    page: str
    ui_action: str = 'send_order'  # send_order | tm_request | timed_tm | udp_observe
    tx_expect_hex: str | None = None
    reply_expect_hex: str | None = None
    tm_golden_key: str | None = None
    tm_table_key: str | None = None
    tm_exclude: list[str] = field(default_factory=list)
    status: str = 'ready'  # ready | missing_tx_golden | pending_reply | skip
    skip_reason: str | None = None
    note: str = ''
    cable: str | None = None  # can a/b
    source: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'protocol': self.protocol,
            'case_id': self.case_id,
            'order_id': self.order_id,
            'page': self.page,
            'ui_action': self.ui_action,
            'tx_expect_hex': self.tx_expect_hex,
            'reply_expect_hex': self.reply_expect_hex,
            'tm_golden_key': self.tm_golden_key,
            'tm_table_key': self.tm_table_key,
            'tm_exclude': self.tm_exclude,
            'status': self.status,
            'skip_reason': self.skip_reason,
            'note': self.note,
            'cable': self.cable,
            'source': self.source,
        }


def load_protocol_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def iter_golden_files() -> list[Path]:
    if not GOLDENS_DIR.is_dir():
        return []
    return sorted(GOLDENS_DIR.glob('*.json'))


def load_all_cases(*, protocol: str | None = None, ready_only: bool = False) -> list[GoldenCase]:
    out: list[GoldenCase] = []
    for p in iter_golden_files():
        data = load_protocol_file(p)
        proto = str(data.get('protocol') or p.stem)
        if protocol and proto != protocol and not proto.startswith(protocol):
            # allow protocol filter like can_biu or can
            if protocol == 'can' and not proto.startswith('can_'):
                continue
            if protocol == 'serial' and not proto.startswith('serial_'):
                continue
            if protocol == 'udp' and not proto.startswith('udp_'):
                continue
            if protocol not in (proto, p.stem):
                continue
        for c in data.get('cases') or []:
            gc = GoldenCase(
                protocol=proto,
                case_id=str(c.get('case_id') or c.get('id') or c.get('order_id')),
                order_id=str(c.get('order_id') or ''),
                page=str(c.get('page') or data.get('page') or ''),
                ui_action=str(c.get('ui_action') or 'send_order'),
                tx_expect_hex=c.get('tx_expect_hex'),
                reply_expect_hex=c.get('reply_expect_hex'),
                tm_golden_key=c.get('tm_golden_key'),
                tm_table_key=c.get('tm_table_key'),
                tm_exclude=list(c.get('tm_exclude') or []),
                status=str(c.get('status') or 'ready'),
                skip_reason=c.get('skip_reason'),
                note=str(c.get('note') or ''),
                cable=c.get('cable'),
                source=dict(c.get('source') or {}),
            )
            if ready_only and gc.status != 'ready':
                continue
            out.append(gc)
    return out


def assert_tx_bytes(got: bytes | None, expect_hex: str, *, label: str) -> None:
    if got is None:
        raise AssertionError(f'{label}: 未收到线帧；{hex_diff(expect_hex, b"")}')
    if norm_hex(bytes_to_hex(got)) != norm_hex(expect_hex):
        raise AssertionError(f'{label}: 线帧不匹配；{hex_diff(expect_hex, got)}')


# ---- 从仓库资产生成 manifest（写 scenarios/goldens）----

_WIRE_TO_PROTO = {
    # wire_key -> (protocol, page, order_id, tm_key, table)
    'biu_k1501_defaults': ('can_biu', '/biu/telecontrol/command', 'K1501', 'passthrough_biu_ff_1', 'BIU:FF'),
    'camera_cam_a0_seq0': ('serial_xl-camera', '/xl/board/camera', 'CAM_A0', 'passthrough_cam_d8', 'D8'),
    'xl_rkdj_d1503_defaults': ('serial_xl-rkdj', '/xl/board/rkdj', 'D1503', 'passthrough_board_rkdj', 'RKDJ'),
}

_CFG_MAP = {
    'can_biu': ('BIU-TeleControlCfg.json', '/biu/telecontrol/command'),
    'can_xl': ('XL-TeleControlCfg.json', '/xl/telecontrol/command'),
    'can_yj216': ('YJ216-TeleControlCfg.json', '/yj216/telecontrol/command'),
    'serial_xl-camera': ('XL-Camera-TeleControlCfg.json', '/xl/board/camera'),
    'serial_xl-camera-v17': ('XL-Camera-V17-TeleControlCfg.json', '/xl/board/camera_v17'),
    'serial_xl-rkdj': ('XL-RKDJ-TeleControlCfg.json', '/xl/board/rkdj'),
    'serial_xl-zk': ('XL-ZK-TeleControlCfg.json', '/xl/board/zk'),
    'serial_xl-cpazx': ('XL-CPAZX-TeleControlCfg.json', '/xl/board/cpazx'),
    'serial_yj216-rs422': ('YJ216-RS422-TeleControlCfg.json', '/yj216/rs422'),
    'udp_xl_udp_dj': ('XL-DJ-TeleControlCfg.json', '/xl/board/dj'),
}

# 已知可复用的 wire 黄金（orderId -> wire key）；跨协议同 order 时按 protocol 过滤
_ORDER_WIRE = {
    ('can_biu', 'K1501'): 'biu_k1501_defaults',
    ('can_xl', 'K1501'): 'biu_k1501_defaults',  # 同默认值；标注复用
    ('serial_xl-camera', 'CAM_A0'): 'camera_cam_a0_seq0',
    ('serial_xl-camera-v17', 'CAM_A0'): 'camera_cam_a0_seq0',
    ('serial_xl-rkdj', 'D1503'): 'xl_rkdj_d1503_defaults',
    ('serial_xl-zk', 'D1503'): 'xl_rkdj_d1503_defaults',  # TODO 2.5 确认是否完全一致
}


def _load_wire() -> dict:
    from hil.samples import tc_goldens
    return tc_goldens()


def _load_cfg_orders(cfg_name: str) -> dict[str, dict]:
    path = CFG_DIR / cfg_name
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    orders = data.get('order') or {}
    return {str(k): v for k, v in orders.items() if isinstance(v, dict)}


def build_and_write_goldens() -> dict[str, int]:
    """扫描 TeleControlCfg + telecontrol_wire_goldens，写入 scenarios/goldens/<protocol>.json。"""
    wire = _load_wire()
    stats: dict[str, int] = {}
    GOLDENS_DIR.mkdir(parents=True, exist_ok=True)

    # 额外：相机 v17 复用；cpazx/rs422/udp/yj216 can 无 wire → missing
    extra_tm = {
        'serial_xl-camera': ('passthrough_cam_d8', 'D8', ['CAM001', 'CAM002']),
        'serial_xl-camera-v17': ('passthrough_cam_v17_d8', 'D8V17', ['CAM001', 'CAM002']),
        'serial_xl-rkdj': ('passthrough_board_rkdj', 'RKDJ', []),
        'serial_xl-zk': ('passthrough_board_zk', 'ZK', []),
        'serial_xl-cpazx': ('passthrough_cpazx', 'CPAZX', []),
        'serial_yj216-rs422': (None, 'LCWP20', []),  # 仅刷新 historically
        'can_biu': ('passthrough_biu_ff_1', 'BIU:FF', []),
        'can_xl': ('passthrough_xlcan_ff', 'XL:FF', []),
        'can_yj216': ('passthrough_yj216_ff', 'YJ216:FF', ['YJ001', 'YJ002']),
        'udp_xl_udp_dj': ('passthrough_board_dj', 'DJ', []),
    }

    # cpazx CP01 线帧可从协议算（与旧测试一致）
    from hil.protocol import frames as F
    computed = {
        ('serial_xl-cpazx', 'CP01'): (
            (b'\xEB\x90\xFF' + bytes(8) + bytes([F.sum8(b'\xEB\x90\xFF' + bytes(8))])).hex(' ').upper()
        ),
        ('serial_yj216-rs422', 'RS422_TM_REQ'): F.rs422_request(0x01).hex(' ').upper(),
    }

    for proto, (cfg_name, page) in _CFG_MAP.items():
        orders = _load_cfg_orders(cfg_name)
        cases: list[dict] = []
        ready = missing = 0
        tm_key, table, excl = extra_tm.get(proto, (None, None, []))
        for oid, ord_body in orders.items():
            case_id = f'{proto}__{oid}'
            wire_key = _ORDER_WIRE.get((proto, oid))
            tx = None
            src = {'cfg': cfg_name, 'order_name': ord_body.get('name')}
            if wire_key and wire_key in wire:
                tx = norm_hex(wire[wire_key]['hex'])
                src['wire_key'] = wire_key
            elif (proto, oid) in computed:
                tx = computed[(proto, oid)]
                src['computed'] = True
            status = 'ready' if tx else 'missing_tx_golden'
            skip = None if tx else f'缺黄金：TeleControlCfg 有指令 {oid}，但 telecontrol_wire_goldens 无对应线帧'
            if status == 'ready':
                ready += 1
            else:
                missing += 1
            case = {
                'case_id': case_id,
                'order_id': oid,
                'page': page,
                'ui_action': 'send_order',
                'tx_expect_hex': tx,
                'reply_expect_hex': None,
                'tm_golden_key': tm_key if (tx and tm_key and oid == list(orders)[0]) else None,
                # 仅首条 ready 附带一次遥测字段断言，避免每条都刷 TM
                'tm_table_key': table if (tx and tm_key and status == 'ready') else None,
                'tm_exclude': excl if (tx and tm_key) else [],
                'status': status,
                'skip_reason': skip,
                'note': ord_body.get('name') or '',
                'cable': 'a' if proto.startswith('can_') else None,
                'source': src,
            }
            # 修正：只给「本协议第一条 ready」挂 tm，上面逻辑挂了每个 ready —— 稍后压缩
            cases.append(case)

        # 只给第一条 ready 挂 tm_*
        seen_ready = False
        for c in cases:
            if c['status'] == 'ready' and not seen_ready:
                seen_ready = True
                c['tm_golden_key'] = tm_key
                c['tm_table_key'] = table
                c['tm_exclude'] = excl
            else:
                c['tm_golden_key'] = None
                c['tm_table_key'] = None
                c['tm_exclude'] = []

        # UDP：另加一条 observe 字段用例（无遥控也可测推遥测）
        if proto == 'udp_xl_udp_dj':
            cases.append({
                'case_id': 'udp_xl_udp_dj__tm_push',
                'order_id': '',
                'page': page,
                'ui_action': 'tm_observe',
                'tx_expect_hex': None,
                'reply_expect_hex': None,
                'tm_golden_key': 'passthrough_board_dj',
                'tm_table_key': 'DJ',
                'tm_exclude': [],
                'status': 'ready',
                'skip_reason': None,
                'note': '模拟器推工程遥测；UI 字段与 tm_golden 对比（附加刷新检查）',
                'cable': None,
                'source': {'tm': 'eng/passthrough_board_dj'},
            })
            ready += 1

        # CAN：附加 UI 遥测请求用例（点控制页按钮，非 API）
        if proto.startswith('can_') and tm_key:
            fam = proto.split('_', 1)[1]
            cases.append({
                'case_id': f'{proto}__tm_request',
                'order_id': '',
                'page': f'/{fam}/telecontrol/control',
                'ui_action': 'tm_request',
                'tx_expect_hex': None,
                'reply_expect_hex': None,
                'tm_golden_key': tm_key,
                'tm_table_key': table,
                'tm_exclude': excl,
                'status': 'ready',
                'skip_reason': None,
                'note': 'UI 点「发送遥测请求」→ 模拟器回包 → 实时遥测字段黄金对比',
                'cable': 'a',
                'source': {'ui': 'control_tm_request'},
            })
            ready += 1

        doc = {
            '_说明': [
                '闭环黄金：发遥控必须 Playwright 点界面「发送指令」/对应按钮，禁止测试里调发送 API。',
                'status=ready 才执行收发对比；missing_tx_golden / pending_reply 在用例里 skip 并写明原因。',
                'tx_expect_hex = 本机模拟器应收到的线帧；reply_expect_hex = 设备应答（缺则 null，不瞎编）。',
            ],
            'protocol': proto,
            'page': page,
            'cfg': cfg_name,
            'cases': cases,
        }
        out = GOLDENS_DIR / f'{proto}.json'
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        stats[proto] = ready
        stats[f'{proto}__missing'] = missing
    return stats


if __name__ == '__main__':
    s = build_and_write_goldens()
    print(json.dumps(s, ensure_ascii=False, indent=2))
