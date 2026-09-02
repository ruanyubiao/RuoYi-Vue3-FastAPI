"""模拟页黄金样本：读 assets/data/tm_golden_cases.json，缓存时去掉庞大的 fields。"""

from __future__ import annotations

from typing import Any

from config.paths import resolve_data_file
from module_payload.constants import (
    ASSEMBLER_ENG_TM_SUBPKT,
    ASSEMBLER_PASSTHROUGH,
    PARSER_TM_XL_CAMERA,
    PARSER_TM_XL_CAMERA_V17,
    PARSER_TM_CAN_BIU,
    PARSER_TM_CAN_XL,
    PARSER_TM_XL_BOARD,
)

TM_GOLDEN_CASES_NAME = 'tm_golden_cases.json'

# 组装器+解析器 → 默认黄金用例 id（该组合有多样本时取第一条代表性）
_PIPELINE_DEFAULT_KEY: dict[tuple[str, str], str] = {
    (ASSEMBLER_PASSTHROUGH, PARSER_TM_XL_CAMERA): 'passthrough_cam_d8',
    (ASSEMBLER_PASSTHROUGH, PARSER_TM_XL_CAMERA_V17): 'passthrough_cam_v17_d8',
    (ASSEMBLER_PASSTHROUGH, PARSER_TM_CAN_BIU): 'passthrough_biu_ff_1',
    (ASSEMBLER_PASSTHROUGH, PARSER_TM_CAN_XL): 'passthrough_xlcan_ff',
    (ASSEMBLER_PASSTHROUGH, PARSER_TM_XL_BOARD): 'passthrough_board_rkdj',
    (ASSEMBLER_ENG_TM_SUBPKT, PARSER_TM_XL_BOARD): 'eng_board_rkdj',
}

# 相机模拟页：黄金 key → 按钮短文案（D9 需区分单帧/多帧粘包）
_CAMERA_SAMPLE_LABELS: dict[str, str] = {
    'passthrough_cam_d8': 'D8',
    'passthrough_cam_d9': 'D9单帧',
    'passthrough_cam_d9_multi': 'D9多帧',
    'passthrough_cam_v17_d8': 'D8',
    'passthrough_cam_v17_d9': 'D9单帧',
    'passthrough_cam_v17_d9_multi': 'D9多帧',
}

# 组装器+解析器 → 黄金用例 key 前缀（列表接口筛选用）
_PIPELINE_KEY_PREFIX: dict[tuple[str, str], str] = {
    (ASSEMBLER_PASSTHROUGH, PARSER_TM_CAN_BIU): 'passthrough_biu_',
    (ASSEMBLER_PASSTHROUGH, PARSER_TM_CAN_XL): 'passthrough_xlcan_',
    (ASSEMBLER_PASSTHROUGH, PARSER_TM_XL_CAMERA): 'passthrough_cam_d',
    (ASSEMBLER_PASSTHROUGH, PARSER_TM_XL_CAMERA_V17): 'passthrough_cam_v17_',
    (ASSEMBLER_PASSTHROUGH, PARSER_TM_XL_BOARD): 'passthrough_board_',
    (ASSEMBLER_ENG_TM_SUBPKT, PARSER_TM_XL_BOARD): 'eng_board_',
}

_cache: dict[str, dict[str, Any]] | None = None


def _omit_fields(value: Any) -> Any:
    """递归丢掉 fields：模拟只要 hex，缓存不必扛整表解析结果。"""
    if isinstance(value, dict):
        return {k: _omit_fields(v) for k, v in value.items() if k != 'fields'}
    if isinstance(value, list):
        return [_omit_fields(x) for x in value]
    return value


def _load_cache() -> dict[str, dict[str, Any]]:
    global _cache
    if _cache is not None:
        return _cache
    path = resolve_data_file(TM_GOLDEN_CASES_NAME)
    if not path.is_file():
        _cache = {}
        return _cache
    import json

    raw = json.loads(path.read_text(encoding='utf-8'))
    out: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for cid, obj in raw.items():
            if isinstance(obj, dict):
                stripped = _omit_fields(obj)
                stripped['key'] = cid
                out[str(cid)] = stripped
    _cache = out
    return _cache


def reset_sample_cache() -> None:
    """测试用：清掉进程内缓存。"""
    global _cache
    _cache = None


def resolve_sample_key(key: str = '', assembler_id: str = '', parser_id: str = '') -> str:
    k = (key or '').strip()
    if k:
        return k
    pair = ((assembler_id or '').strip(), (parser_id or '').strip())
    return _PIPELINE_DEFAULT_KEY.get(pair, '')


def _pipeline_key_prefix(assembler_id: str = '', parser_id: str = '') -> str:
    pair = ((assembler_id or '').strip(), (parser_id or '').strip())
    return _PIPELINE_KEY_PREFIX.get(pair, '')


def _sample_button_label(key: str, obj: dict[str, Any]) -> str:
    """模拟页示例按钮短文案（FF / D8 / RKDJ 等）。"""
    result = obj.get('result') if isinstance(obj.get('result'), dict) else {}
    table_key = str(result.get('table_key') or '').strip()
    kind = str(obj.get('kind') or '').strip()

    if kind in ('camera', 'camera_v17'):
        if key in _CAMERA_SAMPLE_LABELS:
            return _CAMERA_SAMPLE_LABELS[key]
        return table_key or key.rsplit('_', 1)[-1].upper()

    if kind == 'biu':
        local = table_key.split(':', 1)[-1] if ':' in table_key else table_key
        return local or key.rsplit('_', 1)[-1].upper()

    if kind == 'xlcan':
        return table_key.split(':', 1)[-1] if ':' in table_key else 'FF'

    if kind in ('board', 'eng'):
        if table_key:
            return table_key
        for token, label in (('rkdj', 'RKDJ'), ('zk', 'ZK'), ('dj', 'DJ')):
            if token in key.lower():
                return label
        return key.rsplit('_', 1)[-1].upper()

    return key


def list_simulate_samples(*, assembler_id: str = '', parser_id: str = '') -> list[dict[str, str]]:
    """按组装器+解析器列出可选黄金样本（key/label/tooltip）；无匹配返回空列表。"""
    prefix = _pipeline_key_prefix(assembler_id, parser_id)
    if not prefix:
        return []
    out: list[dict[str, str]] = []
    seen_labels: set[str] = set()
    for key in sorted(_load_cache()):
        if not key.startswith(prefix):
            continue
        obj = _load_cache()[key]
        label = _sample_button_label(key, obj)
        if label in seen_labels:
            continue
        seen_labels.add(label)
        result = obj.get('result') if isinstance(obj.get('result'), dict) else {}
        tooltip = str(result.get('name') or key)
        out.append(
            {
                'key': key,
                'label': label,
                'tooltip': tooltip,
            }
        )
    return out


def get_simulate_sample(
    *,
    key: str = '',
    assembler_id: str = '',
    parser_id: str = '',
) -> dict[str, Any]:
    """返回黄金对象（含 key/kind/hex，无 fields）；匹配不到返回空 dict。"""
    cid = resolve_sample_key(key, assembler_id, parser_id)
    if not cid:
        return {}
    return dict(_load_cache().get(cid) or {})
