"""生成遥测回归对照 ``tm_golden_cases.json``。

在解析代码正确时运行：读 ``遥测数据.txt`` 的 hex，走当前 ingest，把每种类型写成一个对象
（``hex`` + ``result``）。pytest 不收集本文件。

用法见 tests/README.md。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from module_payload.assemblers.eng_tm_subpkt import EngTmSubpktAssembler
from module_payload.cfg.hex_text import hex_to_bytes
from module_payload.parsers.xl_camera_tm import XlCameraTmIngest, reset_xl_camera_tm_mgr
from module_payload.parsers.biu_can_tm import BiuCanTmIngest
from module_payload.parsers.xl_board_tm import XlBoardTmIngest
from module_payload.parsers.xl_can_tm import XlCanTmIngest

_TESTS_DIR = Path(__file__).resolve().parent
_BACKEND = _TESTS_DIR.parent
TXT_PATH = _TESTS_DIR / '遥测数据.txt'
CASES_PATH = _BACKEND / 'assets' / 'data' / 'tm_golden_cases.json'

# 与 遥测数据.txt 中样本顺序一致：D8 → D9 单帧 → D9 多帧连续块 → 其余各一行
_SPECS: list[tuple[str, str]] = [
    ('passthrough_cam_d8', 'camera'),
    ('passthrough_cam_d9', 'camera'),
    ('passthrough_cam_d9_multi', 'camera'),
    ('passthrough_biu_ff_1', 'biu'),
    ('passthrough_biu_ff_2', 'biu'),
    ('passthrough_biu_fd_1', 'biu'),
    ('passthrough_biu_fd_2', 'biu'),
    ('passthrough_biu_fb', 'biu'),
    ('passthrough_biu_f9', 'biu'),
    ('passthrough_biu_f7', 'biu'),
    ('passthrough_biu_fe', 'biu'),
    ('passthrough_biu_fc', 'biu'),
    ('passthrough_xlcan_ff', 'xlcan'),
    ('passthrough_board_rkdj', 'board'),
    ('passthrough_board_zk', 'board'),
    ('passthrough_board_dj', 'board'),
    ('eng_board_rkdj', 'eng'),
    ('eng_board_zk', 'eng'),
    ('eng_board_dj', 'eng'),
]


def _fmt_hex(raw: bytes) -> str:
    return ' '.join(f'{b:02X}' for b in raw)


def _is_hex_line(text: str) -> bool:
    s = text.strip()
    return bool(s) and all(c in '0123456789abcdefABCDEF ' for c in s)


def _hex_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if _is_hex_line(ln)]


def _hex_samples_for_specs(text: str) -> list[str]:
    """D8 一行；D9 单帧一行；其后连续 EB D9 行拼成多帧粘包；其余各一行。"""
    lines = _hex_lines(text)
    if len(lines) < 3:
        raise ValueError('样本不足')

    idx = 0
    d8 = lines[idx]
    idx += 1

    d9_single = lines[idx]
    if not d9_single.upper().startswith('EB D9'):
        raise ValueError('D9 单帧须为 EB D9 行')
    idx += 1

    d9_multi_lines: list[str] = []
    while idx < len(lines) and lines[idx].upper().startswith('EB D9'):
        d9_multi_lines.append(lines[idx])
        idx += 1
    if not d9_multi_lines:
        raise ValueError('D9 多帧块须至少 1 行 EB D9')

    d9_multi = _fmt_hex(b''.join(hex_to_bytes(ln) for ln in d9_multi_lines))
    samples = [d8, d9_single, d9_multi, *lines[idx:]]
    if len(samples) != len(_SPECS):
        raise ValueError(f'样本数 {len(samples)} 与类型数 {len(_SPECS)} 不一致')
    return samples


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


def _parse(kind: str, hex_text: str) -> dict:
    """生成侧解析：与测试用例各自实现，避免测试依赖本脚本。"""
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
    raise ValueError(kind)


def main() -> None:
    hex_samples = _hex_samples_for_specs(TXT_PATH.read_text(encoding='utf-8'))

    cases: dict[str, dict] = {}
    for (cid, kind), hx in zip(_SPECS, hex_samples, strict=True):
        hex_text = _fmt_hex(hex_to_bytes(hx))
        cases[cid] = {
            'kind': kind,
            'hex': hex_text,
            'result': _parse(kind, hex_text),
        }
        print(cid, kind, 'ok')

    CASES_PATH.write_text(
        json.dumps(cases, ensure_ascii=False, indent=2, sort_keys=False, allow_nan=False) + '\n',
        encoding='utf-8',
    )
    print('wrote', CASES_PATH, 'bytes', CASES_PATH.stat().st_size)


if __name__ == '__main__':
    main()
