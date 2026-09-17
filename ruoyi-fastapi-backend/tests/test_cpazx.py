"""CPA 指向：小端组帧、55AA 遥测、配置加载。"""

from __future__ import annotations

import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from module_payload.cfg.payload_config_loader import PayloadConfigLoader, XL_BOARD_TM_TABLE
from module_payload.cfg.telecontrol_assembler import encode_number
from module_payload.cfg.telecontrol_cfg import (
    PROTOCOL_XL_CPAZX,
    TeleControlCfgManager,
    cfg_id_for_board,
    cfg_id_from_filename,
    protocol_for_cfg_id,
)
from module_payload.cfg.xl_board_telecontrol_assembler import assemble_xl_board_order
from module_payload.constants import PARSER_TM_XL_CPAZX
from module_payload.parsers import list_parsers, resolve_parser
from module_payload.parsers.xl_cpazx_tm import (
    FRAME_LEN,
    XlCpazxTmIngest,
    reset_xl_cpazx_tm_mgr,
)
from module_payload.tm_golden_samples import get_simulate_sample, list_simulate_samples, reset_sample_cache

SAMPLE_TM_HEX = (
    '55 AA 01 00 1B B7 00 40 5D C6 00 40 1F 00 00 28 23 00 00 00 1B B7 00 40 5D C6 00 00 14'
)


def test_encode_number_little_endian_int32() -> None:
    assert encode_number(10000001, 'INT32', endian='little') == struct.pack('<i', 10000001)
    assert encode_number(10000001, 'INT32') == struct.pack('>i', 10000001)
    assert encode_number(10000, 'INT32', endian='le') == struct.pack('<i', 10000)


def test_cfg_id_and_protocol() -> None:
    assert cfg_id_from_filename('XL-CPAZX-TeleControlCfg.json') == 'xl-cpazx-tc'
    assert cfg_id_for_board('cpazx') == 'xl-cpazx-tc'
    assert protocol_for_cfg_id('xl-cpazx-tc') == PROTOCOL_XL_CPAZX
    assert PayloadConfigLoader.normalize_xl_board('cpazx') == 'cpazx'
    assert PayloadConfigLoader.xl_board_tm_table_key('cpazx') == XL_BOARD_TM_TABLE['cpazx'] == 'CPAZX'
    entry = PayloadConfigLoader.get_device_connect_entry('cpazx', reload=True)
    assert entry.get('baudrate') == 921600
    assert entry.get('parserId') == PARSER_TM_XL_CPAZX
    assert entry.get('assemblerId') == 'passthrough'
    assert entry.get('fullDuplex') is True
    from pathlib import Path

    assert PayloadConfigLoader._cache_key_for_path(Path('XL-CPAZX-TeleMetryCfg.json')) == 'xl_tm:cpazx'


def test_parser_registered() -> None:
    ids = {p['id'] for p in list_parsers()}
    assert PARSER_TM_XL_CPAZX in ids
    assert resolve_parser(PARSER_TM_XL_CPAZX) is XlCpazxTmIngest


def test_assemble_noparam_12b_checksum_includes_header() -> None:
    TeleControlCfgManager.reload('xl-cpazx-tc')
    result = TeleControlCfgManager.assemble('xl-cpazx-tc', 'CP01', [])
    raw = bytes.fromhex(result['hex'].replace(' ', ''))
    assert len(raw) == 12
    assert raw[0:3] == bytes([0xEB, 0x90, 0xFF])
    assert raw[3:11] == bytes(8)
    assert (sum(raw[:-1]) & 0xFF) == raw[-1]
    xl_style = sum(raw[2:-1]) & 0xFF
    assert xl_style != raw[-1]


def test_assemble_position_10_000001_little_endian() -> None:
    TeleControlCfgManager.reload('xl-cpazx-tc')
    result = TeleControlCfgManager.assemble('xl-cpazx-tc', 'CP05', [None, None, 10.000001, 0])
    raw = bytes.fromhex(result['hex'].replace(' ', ''))
    assert raw[0:3] == bytes([0xEB, 0x90, 0x04])
    assert raw[3:7] == struct.pack('<i', 10000001)
    assert raw[7:11] == struct.pack('<i', 0)
    assert (sum(raw[:-1]) & 0xFF) == raw[-1]
    assert len(raw) == 12


def test_assemble_speed_10_little_endian() -> None:
    TeleControlCfgManager.reload('xl-cpazx-tc')
    result = TeleControlCfgManager.assemble('xl-cpazx-tc', 'CP06', [None, None, 10, 10])
    raw = bytes.fromhex(result['hex'].replace(' ', ''))
    assert raw[0:3] == bytes([0xEB, 0x90, 0x05])
    assert raw[3:7] == struct.pack('<i', 10000)
    assert raw[7:11] == struct.pack('<i', 10000)
    assert (sum(raw[:-1]) & 0xFF) == raw[-1]


def test_xl_board_assemble_still_big_endian_checksum_excludes_header() -> None:
    order = {
        'check': 'yes',
        'component': [
            {'componentType': 'fixed', 'defaultVal': '0xEB90'},
            {'componentType': 'fixed', 'defaultVal': '0x0F'},
            {'componentType': 'fixed', 'defaultVal': '0x0008'},
            {'componentType': 'fixed', 'defaultVal': '0x92AA03'},
            {'componentType': 'select', 'defaultVal': '0xAA', 'options': {'0xAA': '方位'}},
            {
                'componentType': 'number',
                'dataType': 'INT32',
                'formula': 'D*100000',
            },
        ],
    }
    result = assemble_xl_board_order(order, [None, None, None, None, '0xAA', 1.5])
    raw = bytes.fromhex(result['hex'].replace(' ', ''))
    assert raw[9:13] == struct.pack('>i', 150000)
    assert (sum(raw[2:-1]) & 0xFF) == raw[-1]
    assert (sum(raw[:-1]) & 0xFF) != raw[-1]


def _field(parsed, fid: str) -> dict:
    for f in parsed.fields:
        if f.get('id') == fid:
            return f
    raise AssertionError(fid)


def test_tm_sample_hex_fields() -> None:
    reset_xl_cpazx_tm_mgr()
    raw = bytes.fromhex(SAMPLE_TM_HEX.replace(' ', ''))
    assert len(raw) == FRAME_LEN
    assert (sum(raw[:-1]) & 0xFF) == raw[-1] == 0x14
    parsed = XlCpazxTmIngest.parse_bytes(raw)
    assert parsed.table_key == 'CPAZX'
    assert parsed.size == 29
    assert parsed.data_len == 26
    assert _field(parsed, 'CPA001')['value'] == 1
    assert '使能' in str(_field(parsed, 'CPA001').get('show') or '')
    assert _field(parsed, 'CPA002')['calc_val'] == pytest.approx(12.0, abs=0.01)
    assert _field(parsed, 'CPA003')['calc_val'] == pytest.approx(13.0, abs=0.01)
    assert _field(parsed, 'CPA004')['calc_val'] == pytest.approx(8.0)
    assert _field(parsed, 'CPA005')['calc_val'] == pytest.approx(9.0)
    assert _field(parsed, 'CPA006')['calc_val'] == pytest.approx(12.0, abs=0.01)
    assert _field(parsed, 'CPA007')['calc_val'] == pytest.approx(13.0, abs=0.01)
    assert _field(parsed, 'CPA008')['value'] == 0
    assert '无故障' in str(_field(parsed, 'CPA008').get('show') or '')
    assert _field(parsed, 'CPA009')['value'] == 0
    assert _field(parsed, 'CPA010')['value'] == 0
    assert _field(parsed, 'CPA011')['value'] == 0
    for fid in ('CPA012', 'CPA013', 'CPA014', 'CPA015'):
        assert _field(parsed, fid)['value'] == 0


def test_tm_fault_bits_msb_is_bit1() -> None:
    """Bit1=MSB(bitpos0)。0b10010101 → 方位传感器/俯仰驱动/Bit6/Bit8 故障。"""
    reset_xl_cpazx_tm_mgr()
    raw = bytearray(bytes.fromhex(SAMPLE_TM_HEX.replace(' ', '')))
    raw[-2] = 0b10010101
    raw[-1] = sum(raw[:-1]) & 0xFF
    parsed = XlCpazxTmIngest.parse_bytes(bytes(raw))
    assert _field(parsed, 'CPA008')['value'] == 1
    assert '故障' in str(_field(parsed, 'CPA008').get('show') or '')
    assert _field(parsed, 'CPA009')['value'] == 0
    assert _field(parsed, 'CPA010')['value'] == 0
    assert _field(parsed, 'CPA011')['value'] == 1
    assert _field(parsed, 'CPA012')['value'] == 0
    assert _field(parsed, 'CPA013')['value'] == 1
    assert _field(parsed, 'CPA014')['value'] == 0
    assert _field(parsed, 'CPA015')['value'] == 1


def test_tm_bad_checksum_dropped_from_extract() -> None:
    raw = bytearray(bytes.fromhex(SAMPLE_TM_HEX.replace(' ', '')))
    raw[-1] ^= 0x01
    blob = bytes(raw)
    assert XlCpazxTmIngest.extract_frames(blob) == []
    with pytest.raises(ValueError, match='校验和错误'):
        XlCpazxTmIngest.parse_bytes(blob)


def test_tm_sticky_extract() -> None:
    raw = bytes.fromhex(SAMPLE_TM_HEX.replace(' ', ''))
    blob = b'\x00\x01' + raw + raw + b'\xff'
    frames = XlCpazxTmIngest.extract_frames(blob)
    assert len(frames) == 2
    assert frames[0] == raw


def test_simulate_golden_sample() -> None:
    reset_sample_cache()
    items = list_simulate_samples(assembler_id='passthrough', parser_id=PARSER_TM_XL_CPAZX)
    assert items
    assert items[0]['label'] == 'CPAZX'
    obj = get_simulate_sample(assembler_id='passthrough', parser_id=PARSER_TM_XL_CPAZX)
    assert obj.get('key') == 'passthrough_cpazx'
    assert SAMPLE_TM_HEX.split()[0] in obj.get('hex', '').upper()
