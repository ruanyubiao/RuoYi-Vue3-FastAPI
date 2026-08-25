"""相机 SC-LINK41EP 遥控组帧：EB90 | type | id | len | seq | data | chk。"""

from __future__ import annotations

from module_payload.cfg.camera_telecontrol_assembler import assemble_camera_order
from module_payload.cfg.telecontrol_assembler import calc_checksum
from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, cfg_id_for_camera


def _chk(frame: bytes) -> int:
    return calc_checksum(frame[2:-1])


def test_d0_prepends_cmd_in_data() -> None:
    order = {
        'frameType': 'D0',
        'frameId': '00',
        'cmd': '14',
        'component': [
            {'componentType': 'number', 'dataType': 'UINT8', 'defaultVal': '1'},
        ],
    }
    result = assemble_camera_order(order, [7], seq=0x0102)
    raw = bytes.fromhex(result['hex'].replace(' ', ''))
    assert raw[0:2] == bytes([0xEB, 0x90])
    assert raw[2] == 0xD0
    assert raw[3] == 0x00
    data_len = (raw[4] << 8) | raw[5]
    assert data_len == 2  # cmd + UINT8
    assert (raw[6] << 8 | raw[7]) == 0x0102
    assert raw[8] == 0x14
    assert raw[9] == 7
    assert raw[-1] == _chk(raw)
    assert result['seq'] == 0x0102
    assert result['dataLen'] == 2


def test_non_d0_data_is_params_only() -> None:
    order = {
        'frameType': 'D7',
        'frameId': '01',
        'cmd': '14',
        'component': [
            {'componentType': 'number', 'dataType': 'UINT8', 'defaultVal': '3'},
        ],
    }
    result = assemble_camera_order(order, [None], seq=0)
    raw = bytes.fromhex(result['hex'].replace(' ', ''))
    assert raw[2] == 0xD7
    assert ((raw[4] << 8) | raw[5]) == 1
    assert raw[8] == 3
    assert raw[-1] == _chk(raw)


def test_empty_value_falls_back_to_default() -> None:
    order = {
        'frameType': 'D0',
        'cmd': '01',
        'component': [
            {'componentType': 'number', 'dataType': 'UINT8', 'defaultVal': '9'},
        ],
    }
    raw = bytes.fromhex(assemble_camera_order(order, [''])['hex'].replace(' ', ''))
    assert raw[9] == 9


def test_assemble_by_id_matches_manager() -> None:
    TeleControlCfgManager.reload('xl-camera-tc')
    tc = TeleControlCfgManager.get(cfg_id_for_camera())
    oid = tc.list_orders()[0]['id']
    a = assemble_camera_order(tc.get_order(oid), [], seq=3)
    b = TeleControlCfgManager.assemble(cfg_id_for_camera(), oid, [], seq=3)
    assert a['hex'] == b['hex']
    assert a['length'] == b['length']
