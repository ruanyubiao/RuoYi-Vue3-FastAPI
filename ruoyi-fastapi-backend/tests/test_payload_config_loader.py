"""配置加载器：族归一化、遥测表键、连接默认项 fullDuplex。"""

from __future__ import annotations

import pytest

from module_payload.cfg.payload_config_loader import (
    DEVICE_CONNECT_CFG_NAME,
    PayloadConfigLoader,
    XL_BOARD_TM_TABLE,
)


def test_normalize_family_and_board() -> None:
    assert PayloadConfigLoader.normalize_family(None) == 'biu'
    assert PayloadConfigLoader.normalize_family('XL') == 'xl'
    assert PayloadConfigLoader.normalize_family('biu') == 'biu'
    assert PayloadConfigLoader.normalize_xl_board('RKDJ') == 'rkdj'
    assert PayloadConfigLoader.normalize_xl_board('zk') == 'zk'
    assert PayloadConfigLoader.normalize_xl_board('dj') == 'dj'
    with pytest.raises(ValueError, match='未知单板'):
        PayloadConfigLoader.normalize_xl_board('foo')
    assert PayloadConfigLoader.xl_board_tm_table_key('rkdj') == XL_BOARD_TM_TABLE['rkdj']


def test_family_from_tm_path() -> None:
    from pathlib import Path

    assert PayloadConfigLoader.family_from_tm_path(Path('BIU-TeleMetryCfg.json')) == 'biu'
    assert PayloadConfigLoader.family_from_tm_path(Path('XL-TeleMetryCfg.json')) == 'xl'
    assert PayloadConfigLoader.family_from_tm_path(Path('other.json')) == 'biu'


def test_tables_to_page_list_storage_key() -> None:
    cfg = {'table': {'ff': {'id': 'ff', 'name': '快遥'}, 'bad': 'x', '': {}}}
    pages = PayloadConfigLoader.tables_to_page_list(cfg, family='biu', storage_key=True)
    assert pages[0]['key'] == 'BIU:FF'
    assert pages[0]['localKey'] == 'FF'
    assert pages[0]['family'] == 'biu'
    local = PayloadConfigLoader.tables_to_page_list(cfg, family='xl', storage_key=False)
    assert local[0]['key'] == 'FF'


def test_device_connect_entry_full_duplex() -> None:
    PayloadConfigLoader.get_device_connect_cfg(reload=True)
    cam = PayloadConfigLoader.get_device_connect_entry('camera_ctrl')
    assert cam.get('fullDuplex') is True
    dj = PayloadConfigLoader.get_device_connect_entry('xl_udp_dj')
    assert dj.get('kind') == 'udp'
    assert dj.get('localPort') == 66
    assert dj.get('remotePort') == 99
    assert 'hostEditable' not in dj
    assert 'portEditable' not in dj
    can = PayloadConfigLoader.get_device_connect_entry('biu_can_a')
    assert can.get('fullDuplex') is False
    assert PayloadConfigLoader.get_device_connect_entry('') == {}
    assert PayloadConfigLoader.get_device_connect_entry('missing') == {}


def test_cache_key_for_known_files() -> None:
    from pathlib import Path

    assert PayloadConfigLoader._cache_key_for_path(Path(DEVICE_CONNECT_CFG_NAME)) == 'device_connect'
    assert PayloadConfigLoader._cache_key_for_path(Path('BIU-TeleMetryCfg.json')) == 'telemetry:biu'
    assert PayloadConfigLoader._cache_key_for_path(Path('XL-RKDJ-TeleMetryCfg.json')) == 'xl_tm:rkdj'


def test_find_telemetry_table_bus_and_local() -> None:
    meta = PayloadConfigLoader.find_telemetry_table_meta('BIU:FF', reload=True)
    assert meta.get('table')
    assert meta.get('source', '').endswith('TeleMetryCfg.json')
    d8 = PayloadConfigLoader.find_telemetry_table('D8', reload=True)
    assert d8
    empty = PayloadConfigLoader.find_telemetry_table_meta('')
    assert empty['table'] == {}


def test_merge_telemetry_pages_has_bus_and_boards() -> None:
    pages = PayloadConfigLoader.merge_telemetry_pages(reload=True)
    keys = {p['key'] for p in pages}
    assert any(k.startswith('BIU:') or k.startswith('XL:') for k in keys)
    assert 'RKDJ' in keys or 'ZK' in keys or 'D8' in keys
