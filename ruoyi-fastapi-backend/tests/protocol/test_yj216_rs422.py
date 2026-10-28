"""YJ216 RS422 遥控组帧与遥测应答。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from module_payload.cfg.payload_config_loader import PayloadConfigLoader
from module_payload.constants import checksum_u16
from module_payload.protocol.yj216.rs422.tc import assemble
from module_payload.protocol.yj216.rs422.tm import (
    Yj216Rs422TmIngest,
    table_for_seq,
    _table_spans,
    _fileplay_extract,
)

_CFG = Path(__file__).resolve().parents[2] / 'assets' / 'config' / 'YJ216-RS422-TeleControlCfg.json'


def _order() -> dict:
    return json.loads(_CFG.read_text(encoding='utf-8'))['order']['RS422_TM_REQ']


def _frame(payload: bytes, seq: int = 1) -> bytes:
    """遥测应答：EB90|3A|lenBE|seq|data|sum16BE(data only)。"""
    length = len(payload).to_bytes(2, 'big')
    head = bytes((0x3A,)) + length + bytes((seq,))
    total = checksum_u16(payload)
    return b'\xEB\x90' + head + payload + total.to_bytes(2, 'big')


def test_assemble_telemetry_request_is_fixed_ff() -> None:
    """配置整帧 fixed：EB 90 FF 00 00 00 FF，直出不重装。"""
    out = assemble(_order(), None)
    raw = bytes.fromhex(out['hex'].replace(' ', ''))
    assert out.get('tableKey') is None
    assert raw == bytes.fromhex('EB90FF000000FF')
    assert out['hex'] == 'EB 90 FF 00 00 00 FF'


def test_assemble_ff_empty_matches_protocol_example() -> None:
    """协议示例帧与配置 fixed 一致。"""
    out = assemble(_order(), [])
    assert bytes.fromhex(out['hex'].replace(' ', '')) == bytes.fromhex('EB90FF000000FF')


def test_assemble_structured_still_works() -> None:
    """结构化路径仍可用：类型码 + 有效数据 → 自动长度与校验。"""
    order = {
        'id': 'RS422_STRUCT',
        'name': '结构化样例',
        'component': [
            {
                'title': '指令类型码',
                'componentType': 'fixed',
                'dataType': 'BYTE',
                'defaultVal': '0x01',
            },
            {
                'title': '附加',
                'componentType': 'hex',
                'defaultVal': 'AABB',
            },
        ],
    }
    raw = bytes.fromhex(assemble(order, [None, 'CCDD'])['hex'].replace(' ', ''))
    assert raw[:6] == bytes.fromhex('EB90010002CC')
    assert raw[6:7] == bytes.fromhex('DD')
    assert int.from_bytes(raw[-2:], 'big') == checksum_u16(raw[2:-2])


def test_table_for_seq_uses_config_key() -> None:
    """帧序号对应 TeleMetryCfg 表项 key（00→LCWP20 … 06→UPHI）。"""
    assert PayloadConfigLoader.normalize_table_match_key('00') == 0
    assert PayloadConfigLoader.normalize_table_match_key('06') == 6
    assert table_for_seq(0) == 'LCWP20'
    assert table_for_seq(1) == 'LCWP30'
    assert table_for_seq(4) == 'LCWP60'
    assert table_for_seq(5) == 'LCOS'
    assert table_for_seq(6) == 'UPHI'
    with pytest.raises(ValueError, match='无法对应表'):
        table_for_seq(99)


def test_parse_unknown_length_uses_seq_key_not_span() -> None:
    """数据区长 0x0E39=3641 与表跨度不等；seq=0 → key=00 → LCWP20，不按长度选表。"""
    payload = bytes([0x05, 0x05, 0x00, 0x00, 0xFF] + [0] * (3641 - 5))
    frame = _frame(payload, seq=0)
    assert frame[0:3] == bytes.fromhex('EB903A')
    assert int.from_bytes(frame[3:5], 'big') == 3641
    assert frame[5] == 0
    assert table_for_seq(frame[5]) == 'LCWP20'
    prepared = Yj216Rs422TmIngest.prepare_frame(frame)
    assert prepared.table_key == 'LCWP20'
    parsed = Yj216Rs422TmIngest.parse_frame(frame)
    assert parsed.table_key == 'LCWP20'
    assert parsed.data_len == 3641


def test_length_fields_are_big_endian_on_tc_and_tm() -> None:
    """遥控/遥测有效数据长度均为 UINT16 大端（非小端）。"""
    order = {
        'component': [
            {
                'title': '指令类型码',
                'componentType': 'fixed',
                'dataType': 'BYTE',
                'defaultVal': '0x01',
            },
            {'title': '附加', 'componentType': 'hex', 'defaultVal': '00'},
        ]
    }
    raw = bytes.fromhex(assemble(order, [None, 'AA' * 258])['hex'].replace(' ', ''))
    assert raw[3:5] == bytes.fromhex('0102')
    assert raw[3:5] != bytes.fromhex('0201')

    tm_payload = bytes([0x11]) * 0x0E39  # 3641，填充与长度字段同值
    frame = _frame(tm_payload, seq=0)
    assert frame[3:5] == bytes.fromhex('0E39')
    assert frame[3:5] != bytes.fromhex('390E')
    assert int.from_bytes(frame[3:5], 'big') == 0x0E39
    assert Yj216Rs422TmIngest.extract_frames(frame) == [frame]


def test_parse_frame_reads_yj001() -> None:
    payload = bytearray(_table_spans()['LCWP20'])
    payload[0] = 0x2A
    parsed = Yj216Rs422TmIngest.parse_frame(_frame(bytes(payload), seq=0), table_key='LCWP20')
    assert parsed.table_key == 'LCWP20'
    first = next(row for row in parsed.fields if row.get('id') == 'YJ001')
    assert int(first.get('value')) == 0x2A


def test_tm_checksum_is_over_data_area_only() -> None:
    payload = bytes([0x05, 0x05, 0x00, 0x00, 0xFF] + [0] * 10)
    frame = _frame(payload, seq=0)
    assert frame[0:3] == bytes.fromhex('EB903A')
    assert int.from_bytes(frame[3:5], 'big') == len(payload)
    assert frame[5] == 0
    assert int.from_bytes(frame[-2:], 'big') == checksum_u16(payload)
    got = Yj216Rs422TmIngest.extract_frames(frame)
    assert got == [frame]


def test_find_table_id_by_key_generic() -> None:
    """通用 key 匹配：只认带 key 的表；无对应返回 None。"""
    tables = {
        'A': {'key': '00', 'name': 'a'},
        'B': {'key': '05', 'name': 'b'},
        'C': {'name': 'no-key'},
    }
    assert PayloadConfigLoader.find_table_id_by_key(tables, 0) == 'A'
    assert PayloadConfigLoader.find_table_id_by_key(tables, '05') == 'B'
    assert PayloadConfigLoader.find_table_id_by_key(tables, 99) is None
    assert PayloadConfigLoader.find_table_id_by_key({'C': {'name': 'x'}}, 0) is None


def test_extract_frames_independent_of_table_spans() -> None:
    """拆帧只看 EB90→长度→校验；数据区长度不必等于任一张表的字段跨度。"""
    spans = _table_spans()
    # 故意选一个不等于任何表跨度的长度
    n = 123
    assert n not in spans.values()
    payload = bytes([0xAB]) * n
    frame = _frame(payload, seq=0)
    assert Yj216Rs422TmIngest.extract_frames(frame) == [frame]
    # 文件回放按帧序号筛表，也不按跨度卡长度
    got = _fileplay_extract(frame, "LCWP20")
    assert got == [frame]
    assert _fileplay_extract(frame, "LCOS") == []


