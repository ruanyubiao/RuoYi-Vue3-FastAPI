"""模拟页黄金样本：路径、缓存去 fields、key / 组装器+解析器查找。"""

from __future__ import annotations

from config.paths import get_packaged_data_dir, resolve_data_file
from module_payload.constants import (
    ASSEMBLER_PASSTHROUGH,
    PARSER_TM_CAN_BIU,
)
from module_payload.tm_golden_samples import (
    TM_GOLDEN_CASES_NAME,
    get_simulate_sample,
    reset_sample_cache,
)
from module_payload.service.payload_telemetry_service import PayloadTelemetryService


def test_pyproject_packages_assets_data() -> None:
    text = (get_packaged_data_dir().parents[1] / 'pyproject.toml').read_text(encoding='utf-8')
    assert 'data/*.json' in text
    assert '"pgt.assets.data"' in text


def test_golden_cases_live_under_assets_data() -> None:
    path = get_packaged_data_dir() / TM_GOLDEN_CASES_NAME
    assert path.is_file()
    assert resolve_data_file(TM_GOLDEN_CASES_NAME) == path
    assert 'assets' in path.parts and 'data' in path.parts


def test_sample_by_key_has_hex_without_fields() -> None:
    reset_sample_cache()
    obj = get_simulate_sample(key='passthrough_cam_d8')
    assert obj.get('key') == 'passthrough_cam_d8'
    assert obj.get('kind') == 'camera'
    assert isinstance(obj.get('hex'), str) and obj['hex'].strip()
    assert 'fields' not in obj
    result = obj.get('result') or {}
    assert 'fields' not in result


def test_sample_unknown_key_empty() -> None:
    reset_sample_cache()
    assert get_simulate_sample(key='not_a_real_case') == {}
    assert get_simulate_sample(assembler_id='camera_image_d6', parser_id=PARSER_TM_CAN_BIU) == {}


def test_sample_pipeline_maps_passthrough_biu() -> None:
    reset_sample_cache()
    obj = get_simulate_sample(
        assembler_id=ASSEMBLER_PASSTHROUGH, parser_id=PARSER_TM_CAN_BIU
    )
    assert obj.get('key') == 'passthrough_biu_ff_1'
    assert 'EB' in obj.get('hex', '').upper() or obj.get('hex', '').strip()


def test_service_delegates_empty_and_hit() -> None:
    reset_sample_cache()
    assert PayloadTelemetryService.get_simulate_sample(key='nope') == {}
    hit = PayloadTelemetryService.get_simulate_sample(key='passthrough_xlcan_ff')
    assert hit.get('key') == 'passthrough_xlcan_ff'
    assert hit.get('kind') == 'xlcan'


def test_cache_skips_fields_on_nested_eng() -> None:
    reset_sample_cache()
    obj = get_simulate_sample(key='eng_board_dj')
    assert obj.get('kind') == 'eng'
    inner = (obj.get('result') or {}).get('inner_board') or {}
    assembled = (obj.get('result') or {}).get('assembled_dj') or {}
    assert 'fields' not in inner
    assert 'fields' not in assembled
    assert inner.get('table_key') == 'DJ'
