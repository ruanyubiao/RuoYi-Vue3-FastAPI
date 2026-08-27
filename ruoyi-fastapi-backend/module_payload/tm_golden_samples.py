"""模拟页黄金样本：读 assets/data/tm_golden_cases.json，缓存时去掉庞大的 fields。"""

from __future__ import annotations

from typing import Any

from config.paths import resolve_data_file
from module_payload.constants import (
    ASSEMBLER_ENG_TM_SUBPKT,
    ASSEMBLER_PASSTHROUGH,
    PARSER_CAMERA_SC_LINK41EP,
    PARSER_TM_CAN_BIU,
    PARSER_TM_CAN_XL,
    PARSER_XL_BOARD_TM,
)

TM_GOLDEN_CASES_NAME = 'tm_golden_cases.json'

# 组装器+解析器 → 默认黄金用例 id（该组合有多样本时取第一条代表性）
_PIPELINE_DEFAULT_KEY: dict[tuple[str, str], str] = {
    (ASSEMBLER_PASSTHROUGH, PARSER_CAMERA_SC_LINK41EP): 'passthrough_cam_d8',
    (ASSEMBLER_PASSTHROUGH, PARSER_TM_CAN_BIU): 'passthrough_biu_ff_1',
    (ASSEMBLER_PASSTHROUGH, PARSER_TM_CAN_XL): 'passthrough_xlcan_ff',
    (ASSEMBLER_PASSTHROUGH, PARSER_XL_BOARD_TM): 'passthrough_board_rkdj',
    (ASSEMBLER_ENG_TM_SUBPKT, PARSER_XL_BOARD_TM): 'eng_board_rkdj',
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
