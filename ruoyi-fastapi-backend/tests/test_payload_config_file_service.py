"""配置文件服务：默认控件值、指令顺序、JSON 保存校验。"""

from __future__ import annotations

import pytest

from module_payload.service.payload_config_file_service import PayloadConfigFileService


def test_default_values_for_order_types() -> None:
    order = {
        'component': [
            {'componentType': 'fixed', 'defaultVal': '0xEB90'},
            {'componentType': 'select', 'defaultVal': '', 'options': {'0xAA': '方位', '0xBB': '俯仰'}},
            {'componentType': 'select', 'defaultVal': '0xBB', 'options': {'0xAA': 'a'}},
            {'componentType': 'number', 'defaultVal': '1.5'},
            {'componentType': 'number', 'defaultVal': '3'},
            {'componentType': 'number', 'defaultVal': 'x'},
            {'componentType': 'number', 'defaultVal': ''},
            {'componentType': 'hex', 'defaultVal': '0F'},
        ]
    }
    vals = PayloadConfigFileService._default_values_for_order(order)
    assert vals[0] == '0xEB90'
    assert vals[1] == '0xAA'
    assert vals[2] == '0xBB'
    assert vals[3] == 1.5
    assert vals[4] == 3
    assert vals[5] == 0
    assert vals[6] == 0
    assert vals[7] == '0F'


def test_order_ids_page_then_dict() -> None:
    cfg = {
        'page': [{'orderList': ['B', 'A', 'B']}],
        'order': {'A': {}, 'C': {}, 'B': {}},
    }
    assert PayloadConfigFileService._order_ids(cfg) == ['B', 'A', 'C']


def test_export_rejects_non_telecontrol() -> None:
    with pytest.raises(ValueError, match='仅支持遥控'):
        PayloadConfigFileService.export_orders_defaults('BIU-TeleMetryCfg.json')


def test_export_orders_defaults_camera_has_hex() -> None:
    rows = PayloadConfigFileService.export_orders_defaults('XL-Camera-TeleControlCfg.json')
    assert rows
    ok = [r for r in rows if r.get('hex')]
    assert ok
    assert all('id' in r and 'len' in r for r in rows)


def test_save_text_rejects_invalid_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        PayloadConfigFileService,
        'resolve_safe',
        classmethod(lambda cls, name: tmp_path / name),
    )
    with pytest.raises(ValueError, match='JSON 格式错误'):
        PayloadConfigFileService.save_text('foo.json', '{')
    with pytest.raises(ValueError, match='根节点'):
        PayloadConfigFileService.save_text('foo.json', '"x"')
