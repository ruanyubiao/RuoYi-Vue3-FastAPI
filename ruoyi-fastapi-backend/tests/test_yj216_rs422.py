"""YJ216 RS422 遥测请求组帧与应答拆表。"""

from __future__ import annotations

import json
from pathlib import Path

from module_payload.constants import checksum_u16
from module_payload.protocol.yj216.rs422.tc import assemble
from module_payload.protocol.yj216.rs422.tm import (
    Yj216Rs422TmIngest,
    table_for_payload,
    _table_spans,
)

_CFG = Path(__file__).resolve().parents[1] / 'assets' / 'config' / 'YJ216-RS422-TeleControlCfg.json'


def _order() -> dict:
    return json.loads(_CFG.read_text(encoding='utf-8'))['order']['RS422_TM_REQ']


def _frame(payload: bytes, seq: int = 1) -> bytes:
    length = len(payload).to_bytes(2, 'big')
    head = bytes((0x3A,)) + length + bytes((seq,))
    total = checksum_u16(payload)
    return b'\xEB\x90' + head + payload + total.to_bytes(2, 'big')


def test_assemble_telemetry_request_uses_command_select() -> None:
    out = assemble(_order(), ['0x06'])
    raw = bytes.fromhex(out['hex'])
    assert out['tableKey'] == 'LCOS'
    assert raw == bytes.fromhex('EB9006000006')
    assert int.from_bytes(raw[-2:], 'big') == checksum_u16(raw[2:-2])


def test_assemble_appends_components_after_command() -> None:
    order = _order()
    order['component'] = [
        *order['component'],
        {
            'title': '参数',
            'componentType': 'hex',
            'defaultVal': 'AABB',
        },
    ]
    raw = bytes.fromhex(assemble(order, ['0x01', 'CCDD'])['hex'])
    assert raw[:5] == bytes.fromhex('EB900102CC')
    assert raw[5:6] == bytes.fromhex('DD')
    assert int.from_bytes(raw[-2:], 'big') == checksum_u16(raw[2:-2])


def test_same_length_lcwp_follows_last_command() -> None:
    spans = _table_spans()
    assert spans['LCWP20'] == spans['LCWP60']
    assert table_for_payload(spans['LCWP20'], 'LCWP60') == 'LCWP60'
    assert table_for_payload(spans['UPHI']) == 'UPHI'
    assert table_for_payload(spans['LCOS']) == 'LCOS'


def test_parse_frame_reads_yj001() -> None:
    payload = bytearray(_table_spans()['LCWP20'])
    payload[0] = 0x2A
    parsed = Yj216Rs422TmIngest.parse_frame(_frame(bytes(payload)), table_key='LCWP20')
    assert parsed.table_key == 'LCWP20'
    first = next(row for row in parsed.fields if row.get('id') == 'YJ001')
    assert int(first.get('value')) == 0x2A
