"""TeleControlCfg / Manager 冒烟与回归测试。"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from exceptions.exception import ServiceException
from module_payload.cfg.payload_config_loader import PayloadConfigLoader
from module_payload.cfg.telecontrol_cfg import (
    TeleControlCfgManager,
    cfg_id_from_filename,
    cfg_id_for_board,
    cfg_id_for_camera,
    cfg_id_for_family,
    protocol_for_cfg_id,
)


def test_cfg_id_from_filename():
    assert cfg_id_from_filename('BIU-TeleControlCfg.json') == 'biu-tc'
    assert cfg_id_from_filename('XL-TeleControlCfg.json') == 'xl-tc'
    assert cfg_id_from_filename('XL-RKDJ-TeleControlCfg.json') == 'xl-rkdj-tc'
    assert cfg_id_from_filename('XL-ZK-TeleControlCfg.json') == 'xl-zk-tc'
    assert cfg_id_from_filename('XL-Camera-TeleControlCfg.json') == 'xl-camera-tc'


def test_route_aliases():
    assert cfg_id_for_family('biu') == 'biu-tc'
    assert cfg_id_for_family('xl') == 'xl-tc'
    assert cfg_id_for_board('rkdj') == 'xl-rkdj-tc'
    assert cfg_id_for_camera() == 'xl-camera-tc'


def test_protocol_from_registry_only():
    assert protocol_for_cfg_id('biu-tc') == 'can_bus'
    assert protocol_for_cfg_id('xl-rkdj-tc') == 'xl_board'
    assert protocol_for_cfg_id('xl-camera-tc') == 'camera'
    with pytest.raises(ServiceException):
        protocol_for_cfg_id('unknown-foo-tc')


def test_manager_loads_all_registered():
    TeleControlCfgManager.reload_all()
    for cid in TeleControlCfgManager.known_ids():
        tc = TeleControlCfgManager.get(cid)
        assert tc.cfg_id == cid
        assert isinstance(tc.raw, dict)
        assert tc.protocol in ('can_bus', 'xl_board', 'camera')


def test_assemble_xl_rkdj_d1503_formula():
    TeleControlCfgManager.reload('xl-rkdj-tc')
    result = TeleControlCfgManager.assemble('xl-rkdj-tc', 'D1503', [None, None, None, None, '0xAA', 1.5])
    raw = bytes.fromhex(result['hex'].replace(' ', ''))
    assert raw[0:5] == bytes([0xEB, 0x90, 0x0F, 0x00, 0x08])
    assert raw[9:13] == struct.pack('>i', 150000)


def test_assemble_can_bus_smoke():
    TeleControlCfgManager.reload('biu-tc')
    tc = TeleControlCfgManager.get('biu-tc')
    orders = tc.list_orders()
    assert orders, 'BIU 遥控配置应有指令'
    oid = orders[0].get('id')
    assert oid
    result = tc.assemble(oid, [])
    assert result.get('hex')
    assert result.get('length', 0) > 0


def test_assemble_camera_smoke():
    TeleControlCfgManager.reload('xl-camera-tc')
    tc = TeleControlCfgManager.get('xl-camera-tc')
    orders = tc.list_orders()
    assert orders
    oid = orders[0].get('id')
    result = tc.assemble(oid, [], seq=0)
    assert result.get('hex')
    assert 'EB 90' in result['hex'] or result['hex'].startswith('EB90') or 'EB' in result['hex']


def test_reload_file_syncs_loader_aliases():
    from config.paths import resolve_config_file

    path = resolve_config_file('BIU-TeleControlCfg.json')
    cid = TeleControlCfgManager.reload(path)
    assert cid == 'biu-tc'
    raw = TeleControlCfgManager.get('biu-tc').raw
    assert PayloadConfigLoader._cache.get('biu-tc') is raw
    assert PayloadConfigLoader._cache.get('telecontrol:biu') is raw
    assert PayloadConfigLoader._cache.get('telecontrol') is raw


def test_get_order_returns_deepcopy():
    TeleControlCfgManager.reload('biu-tc')
    tc = TeleControlCfgManager.get('biu-tc')
    orders = tc.list_orders()
    oid = orders[0]['id']
    a = tc.get_order(oid)
    b = tc.get_order(oid)
    assert a is not b
    if a.get('component'):
        a['component'][0] = {'__mutated__': True}
        assert b.get('component')[0] != {'__mutated__': True}


def test_missing_file_raises(tmp_path, monkeypatch):
    from config import paths as cfg_paths

    def _missing(name: str):
        raise FileNotFoundError(name)

    monkeypatch.setattr(cfg_paths, 'read_config_json', _missing)
    TeleControlCfgManager._instances.pop('biu-tc', None)
    with pytest.raises(ServiceException) as ei:
        TeleControlCfgManager.get('biu-tc', reload=True)
    assert '不存在' in str(ei.value.message)


def test_export_protocol_selection_board_vs_camera():
    """export 走 Manager 时 board / camera 协议应不同。"""
    board = TeleControlCfgManager.get('xl-rkdj-tc', reload=True)
    camera = TeleControlCfgManager.get('xl-camera-tc', reload=True)
    assert board.protocol == 'xl_board'
    assert camera.protocol == 'camera'
    b_orders = board.list_orders()
    c_orders = camera.list_orders()
    assert b_orders and c_orders
    b_hex = board.assemble(b_orders[0]['id'], []).get('hex', '')
    c_hex = camera.assemble(c_orders[0]['id'], [], seq=0).get('hex', '')
    assert b_hex and c_hex
