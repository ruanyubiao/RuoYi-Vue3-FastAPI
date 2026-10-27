"""YJ216 实时遥测：附录字段位置与 SUM。"""

from __future__ import annotations

import pytest

from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager
from module_payload.protocol.yj216.can.tm import TM_PAYLOAD_LEN, Yj216CanTmIngest


def _frame(payload: bytes, table: int = 0xFF) -> bytes:
    """长度(2) + 3A + 表号 + 数据区 + SUM。长度值不含长度自身和 SUM。"""
    body = bytes([0x3A, table & 0xFF]) + payload
    head = bytes([(len(body) >> 8) & 0xFF, len(body) & 0xFF]) + body
    return head + bytes([sum(head) & 0xFF])


def test_realtime_frame_checksum_and_fields() -> None:
    payload = bytearray(TM_PAYLOAD_LEN)
    payload[0] = 5
    payload[3] = 0x11
    payload[6] = 0xFB  # INT8 -5
    payload[32] = 0x03
    payload[33] = 0xE8  # 1000 → D*0.001 = 1
    parsed = Yj216CanTmIngest.parse_bytes(_frame(bytes(payload)))
    assert parsed.table_key == 'YJ216:FF'
    assert parsed.frame_type == '3A'
    by_id = {f.get('id'): f for f in parsed.fields}
    assert by_id['YJ001']['value'] in (5, '5')
    assert str(by_id['YJ004'].get('hex') or '').upper().endswith('11')
    tec = by_id['YJ033']
    calc = tec.get('calc_val', tec.get('value'))
    assert float(calc) == pytest.approx(1.0)


def test_bad_checksum_is_rejected() -> None:
    raw = bytearray(_frame(bytes(TM_PAYLOAD_LEN)))
    raw[-1] ^= 0xFF
    with pytest.raises(ValueError, match='校验和错误'):
        Yj216CanTmIngest.parse_bytes(bytes(raw))


def test_page_assemble_keeps_lcwp_sum() -> None:
    """有 orderId 时读服务端配置组帧；末字节是 SUM；长度按实际 7。"""
    from module_payload.entity.vo.payload_telecontrol_vo import TelecontrolAssembleModel
    from module_payload.service.payload_telecontrol_service import PayloadTelecontrolService

    TeleControlCfgManager.get('yj216-tc', reload=True)
    # 即使请求里带错误长度 fixed，也以服务端配置为准
    order = TeleControlCfgManager.get('yj216-tc').get_order('YJ216BB')
    bad_comps = [{**order['component'][0], 'defaultVal': '0x0000'}, *order['component'][1:]]
    result = PayloadTelecontrolService.assemble(
        TelecontrolAssembleModel(
            orderId='YJ216BB',
            components=bad_comps,
            values=[],
            family='yj216',
        )
    )
    assert result['hex'] == '00 07 15 BB 11 00 00 00 00 E8'
    assert result.get('tip') == ''


def test_assemble_service_uses_server_order_not_client_components() -> None:
    """服务层有 orderId 时忽略请求里错误的长度 fixed，以磁盘配置为准。"""
    from module_payload.entity.vo.payload_telecontrol_vo import TelecontrolAssembleModel
    from module_payload.protocol.yj216.can.tc import assemble as yj_assemble
    from module_payload.service.payload_telecontrol_service import PayloadTelecontrolService

    TeleControlCfgManager.get('yj216-tc', reload=True)
    order = TeleControlCfgManager.get('yj216-tc').get_order('YJ216BB')
    bad = {
        **order,
        'component': [{**order['component'][0], 'defaultVal': '0x0000'}, *order['component'][1:]],
    }
    assert yj_assemble(bad, []).get('tip')
    # 经 service + orderId 则读服务端 0x0007，tip 为空
    result = PayloadTelecontrolService.assemble(
        TelecontrolAssembleModel(orderId='YJ216BB', components=bad['component'], values=[], family='yj216')
    )
    assert result['hex'] == '00 07 15 BB 11 00 00 00 00 E8'
    assert result.get('tip') == ''


def test_lcwp_app_matches_measured_length_frames() -> None:
    """温度 0x11、电压 0：长度=7（D2~D4），首帧 8 字节，次帧为 U4+SUM。"""
    from module_payload.protocol.yj216.can.tc import payload_frames

    assembled = TeleControlCfgManager.assemble('yj216-tc', 'YJ216BB')
    app = bytes(int(x, 16) for x in assembled['hex'].split())
    chunks = payload_frames(app)
    assert chunks[0] == bytes.fromhex('000715BB11000000')
    assert chunks[1] == bytes.fromhex('00E8')


def test_lcwp_wrong_cfg_length_is_fixed_with_error() -> None:
    """配置长度与实际不符时覆盖为实测值，tip 带说明。"""
    from module_payload.protocol.yj216.can.tc import assemble

    order = TeleControlCfgManager.get('yj216-tc').get_order('YJ216BB')
    bad = {
        **order,
        'component': [
            {**order['component'][0], 'defaultVal': '0x0009'},
            *order['component'][1:],
        ],
    }
    got = assemble(bad, [])
    assert got['hex'] == '00 07 15 BB 11 00 00 00 00 E8'
    assert '0x0009' in got['tip']
    assert '0x0007' in got['tip']
    assert 'lengthError' not in got


def test_tec_and_power_include_fixed_length() -> None:
    """TEC、功率长度与实测一致为 00 06，首帧 8 字节，次帧是 SUM。"""
    from module_payload.protocol.yj216.can.tc import payload_frames

    tec = TeleControlCfgManager.assemble('yj216-tc', 'YJ216DD')
    power = TeleControlCfgManager.assemble('yj216-tc', 'YJ216EE')
    assert tec.get('tip') == '' and power.get('tip') == ''
    tec_app = bytes(int(x, 16) for x in tec['hex'].split())
    power_app = bytes(int(x, 16) for x in power['hex'].split())
    assert payload_frames(tec_app) == [
        bytes.fromhex('000615DD00000000'),
        bytes.fromhex('F8'),
    ]
    assert payload_frames(power_app) == [
        bytes.fromhex('000615EE00000000'),
        bytes.fromhex('09'),
    ]
