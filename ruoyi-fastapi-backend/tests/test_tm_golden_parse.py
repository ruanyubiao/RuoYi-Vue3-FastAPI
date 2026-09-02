"""遥测解析回归：读 tm_golden_cases.json，解析 hex，与 result 对比。

每种类型一个对象：``hex`` 为遥测字符串，``result`` 为事先保存的解析结果。
测试不引用 ``_gen_tm_golden.py``。用法见 README.md。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from module_payload.assemblers.eng_tm_subpkt import EngTmSubpktAssembler
from module_payload.cfg.hex_text import hex_to_bytes
from module_payload.parsers.xl_camera_tm import XlCameraTmIngest, reset_xl_camera_tm_mgr
from module_payload.parsers.biu_can_tm import BiuCanTmIngest
from module_payload.parsers.xl_board_tm import XlBoardTmIngest
from module_payload.parsers.xl_can_tm import XlCanTmIngest

_TESTS_DIR = Path(__file__).resolve().parent
_BACKEND = _TESTS_DIR.parent
TM_TXT = _TESTS_DIR / '遥测数据.txt'
CASES_JSON = _BACKEND / 'assets' / 'data' / 'tm_golden_cases.json'

REQUIRED_TYPES = {
    'passthrough_cam_d8',
    'passthrough_cam_d9',
    'passthrough_cam_d9_multi',
    'passthrough_biu_ff_1',
    'passthrough_biu_ff_2',
    'passthrough_biu_fd_1',
    'passthrough_biu_fd_2',
    'passthrough_biu_fb',
    'passthrough_biu_f9',
    'passthrough_biu_f7',
    'passthrough_biu_fe',
    'passthrough_biu_fc',
    'passthrough_xlcan_ff',
    'passthrough_board_rkdj',
    'passthrough_board_zk',
    'passthrough_board_dj',
    'eng_board_rkdj',
    'eng_board_zk',
    'eng_board_dj',
}


def _load_cases() -> dict[str, dict]:
    return json.loads(CASES_JSON.read_text(encoding='utf-8'))


def _norm_hex(text: str) -> str:
    return ' '.join(f'{b:02X}' for b in hex_to_bytes(text))


def _bytes_hex(raw: bytes) -> str:
    return ' '.join(f'{b:02X}' for b in raw)


def _txt_hex_lines() -> list[str]:
    out: list[str] = []
    for ln in TM_TXT.read_text(encoding='utf-8').splitlines():
        s = ln.strip()
        if not s:
            continue
        if all(c in '0123456789abcdefABCDEF ' for c in s):
            out.append(_norm_hex(s))
    return out


def _jsonable(v):
    """转成标准 JSON 可写的值。inf/nan 不能落成 Infinity。"""
    if v is None or isinstance(v, (str, bool)):
        return v
    if isinstance(v, int) and not isinstance(v, bool):
        return int(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        return round(float(v), 10)
    if hasattr(v, 'item'):
        return _jsonable(v.item())
    return str(v)


def _fields(fields: list[dict]) -> list[dict]:
    out = []
    for f in fields or []:
        out.append(
            {
                'id': f.get('id'),
                'name': f.get('name'),
                'value': _jsonable(f.get('value')),
                'calc_val': _jsonable(f.get('calc_val')),
                'show': f.get('show'),
                'hex': f.get('hex'),
                'unit': f.get('unit'),
            }
        )
    return out


def _snapshot_parsed(parsed) -> dict:
    snap = {
        'table_key': parsed.table_key,
        'name': parsed.name,
        'data_len': parsed.data_len,
        'size': parsed.size,
        'fields': _fields(parsed.fields),
    }
    if hasattr(parsed, 'src'):
        snap['src'] = int(parsed.src)
        snap['dst'] = int(parsed.dst)
    if hasattr(parsed, 'frame_type'):
        snap['frame_type'] = parsed.frame_type
    return snap


def _snapshot_assembled(payload: bytes) -> dict:
    prepared = XlBoardTmIngest.prepare_assembled_payload(payload, table_key='DJ')
    fields = prepared.mgr.parse(prepared.table_key, prepared.payload) or []
    return {
        'table_key': prepared.table_key,
        'name': prepared.name,
        'data_len': len(prepared.payload),
        'size': len(prepared.raw_frame),
        'fields': _fields(fields),
    }


def parse_hex(kind: str, hex_text: str) -> dict:
    """现场解析遥测 hex（独立于生成脚本）。"""
    raw = hex_to_bytes(hex_text)
    if kind == 'camera':
        reset_xl_camera_tm_mgr()
        return _snapshot_parsed(XlCameraTmIngest.parse_bytes(raw))
    if kind == 'biu':
        return _snapshot_parsed(BiuCanTmIngest.parse_bytes(raw))
    if kind == 'xlcan':
        return _snapshot_parsed(XlCanTmIngest.parse_bytes(raw))
    if kind == 'board':
        return _snapshot_parsed(XlBoardTmIngest.parse_bytes(raw))
    if kind == 'eng':
        parsed = EngTmSubpktAssembler.parse_frame(raw)
        inner = parsed['data']
        return {
            'eng': {
                'dataLen': parsed['dataLen'],
                'srcAddr': parsed['srcAddr'],
                'destAddr': parsed['destAddr'],
                'subCount': parsed['subCount'],
                'subIndex': parsed['subIndex'],
            },
            'inner_board': _snapshot_parsed(XlBoardTmIngest.parse_bytes(inner)),
            'assembled_dj': _snapshot_assembled(inner),
        }
    raise ValueError(f'未知 kind: {kind}')


def _json_roundtrip(obj: object) -> object:
    return json.loads(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    )


def test_golden_file_is_standard_json() -> None:
    """对照文件须是 RFC JSON：禁止 Infinity / NaN / -Infinity。"""
    text = CASES_JSON.read_text(encoding='utf-8')

    def _reject(name: str):
        raise ValueError(f'非标准 JSON 常量: {name}')

    json.loads(text, parse_constant=_reject)


CASES = _load_cases()


@pytest.mark.parametrize('type_id', list(CASES.keys()))
def test_parse_hex_matches_saved_result(type_id: str) -> None:
    """解析对象里的 hex 字符串，与同对象的 result 对比。"""
    obj = CASES[type_id]
    hex_text = obj['hex']
    expected = obj['result']
    parsed = parse_hex(obj['kind'], hex_text)
    assert _json_roundtrip(parsed) == expected


def test_each_object_has_hex_and_result() -> None:
    """每种类型一个对象：hex 与 result 都在。"""
    for type_id, obj in CASES.items():
        assert isinstance(obj.get('hex'), str) and obj['hex'].strip(), type_id
        assert isinstance(obj.get('result'), dict) and obj['result'], type_id
        assert obj.get('kind') in ('camera', 'biu', 'xlcan', 'board', 'eng'), type_id


def test_example_cam_d8() -> None:
    """写法示例：取一种类型的 hex / result。"""
    obj = CASES['passthrough_cam_d8']
    parsed = parse_hex(obj['kind'], obj['hex'])
    assert _json_roundtrip(parsed) == obj['result']


def _used_hex_from_cases(cases: dict[str, dict]) -> set[str]:
    """黄金 hex + D9 多帧粘包拆成单帧行（供 txt 逐行对照）。"""
    used: set[str] = set()
    for obj in cases.values():
        hx = _norm_hex(obj['hex'])
        used.add(hx)
        raw = hex_to_bytes(hx)
        if obj.get('kind') == 'camera' and len(raw) > 20 and raw[0:2] == bytes([0xEB, 0xD9]):
            for off in range(0, len(raw), 20):
                chunk = raw[off : off + 20]
                if len(chunk) == 20:
                    used.add(_bytes_hex(chunk))
    return used


def test_txt_every_hex_is_used() -> None:
    """遥测数据.txt 每一条 hex 都必须出现在某个类型对象里。"""
    used = _used_hex_from_cases(CASES)
    lines = _txt_hex_lines()
    assert lines, f'未从 {TM_TXT} 读到 hex 行'
    missing = [h for h in lines if h not in used]
    assert not missing, f'未使用的 hex 行数={len(missing)} 首条={missing[0][:48]}'


def test_every_case_hex_is_in_txt() -> None:
    """每个类型对象的 hex 都能在遥测数据.txt 里找到。"""
    txt = set(_txt_hex_lines())
    absent: list[str] = []
    for tid, obj in CASES.items():
        hx = _norm_hex(obj['hex'])
        if hx in txt:
            continue
        if tid == 'passthrough_cam_d9_multi':
            raw = hex_to_bytes(hx)
            frames = [
                _bytes_hex(raw[i : i + 20])
                for i in range(0, len(raw), 20)
                if len(raw[i : i + 20]) == 20
            ]
            if frames and all(fr in txt for fr in frames):
                continue
        absent.append(tid)
    assert not absent, f'hex 不在 txt 中: {absent}'


def test_case_kinds_cover_tm_types() -> None:
    assert REQUIRED_TYPES <= set(CASES)


def test_xl_board_src_table_not_old_swap() -> None:
    """锁 V1.0.6 源地址分表，防止再把 0x33 当 ZK、0x44 当热控。"""
    rkdj = CASES['passthrough_board_rkdj']['result']
    zk = CASES['passthrough_board_zk']['result']
    dj = CASES['passthrough_board_dj']['result']
    assert rkdj['src'] == 0x33 and rkdj['table_key'] == 'RKDJ'
    assert zk['src'] == 0x44 and zk['table_key'] == 'ZK'
    assert dj['src'] == 0x77 and dj['table_key'] == 'DJ'
    eng_rkdj = CASES['eng_board_rkdj']['result']['inner_board']
    eng_zk = CASES['eng_board_zk']['result']['inner_board']
    eng_dj = CASES['eng_board_dj']['result']['inner_board']
    assert eng_rkdj['table_key'] == 'RKDJ' and eng_rkdj['src'] == 0x33
    assert eng_zk['table_key'] == 'ZK' and eng_zk['src'] == 0x44
    assert eng_dj['table_key'] == 'DJ' and eng_dj['src'] == 0x77
    assert CASES['eng_board_rkdj']['result']['assembled_dj']['table_key'] == 'DJ'
    assert CASES['eng_board_zk']['result']['assembled_dj']['table_key'] == 'DJ'
    assert CASES['eng_board_dj']['result']['assembled_dj']['table_key'] == 'DJ'


def test_camera_d8_d9_not_old_swap() -> None:
    """锁相机帧类型：D8 慢遥、D9 快遥。"""
    assert CASES['passthrough_cam_d8']['result']['table_key'] == 'D8'
    assert CASES['passthrough_cam_d9']['result']['table_key'] == 'D9'
    assert CASES['passthrough_cam_d9_multi']['result']['table_key'] == 'D9'
    d8 = hex_to_bytes(CASES['passthrough_cam_d8']['hex'])
    d9 = hex_to_bytes(CASES['passthrough_cam_d9']['hex'])
    d9m = hex_to_bytes(CASES['passthrough_cam_d9_multi']['hex'])
    assert d8[0:3] == bytes([0xEB, 0x90, 0xD8])
    assert d9[0:3] == bytes([0xEB, 0xD9, 0xAC])
    assert len(d9m) == 7 * 20
    assert d9m[0:3] == bytes([0xEB, 0xD9, 0xB1])
    assert d9m[-20] == 0xEB and d9m[-19] == 0xD9 and d9m[-18] == 0xB7
