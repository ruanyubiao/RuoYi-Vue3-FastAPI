"""YJ216 实时遥测：附录字段位置与 SUM。"""

from __future__ import annotations

import pytest

from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager
from module_payload.protocol.yj216.can.tm import TM_PAYLOAD_LEN, Yj216CanTmIngest


def _frame(payload: bytes, table: int = 0xFF) -> bytes:
    body = bytes([0x3A, table & 0xFF]) + payload
    return body + bytes([sum(body) & 0xFF])


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
    """遥控页只传分量时仍带上配置里的 check，末字节是 SUM。"""
    from module_payload.entity.vo.payload_telecontrol_vo import TelecontrolAssembleModel
    from module_payload.service.payload_telecontrol_service import PayloadTelecontrolService

    order = TeleControlCfgManager.get('yj216-tc').get_order('YJ216BB')
    result = PayloadTelecontrolService.assemble(
        TelecontrolAssembleModel(
            orderId='YJ216BB',
            components=order['component'],
            values=[],
            family='yj216',
        )
    )
    assert result['hex'] == '00 09 15 BB 11 00 00 00 00 EA'


def test_lcwp_app_matches_doc_first_frame() -> None:
    """温度 0x11、电压 0 时，数据域与表 36 一致：首帧含长度，次帧为 U4 和 SUM。"""
    from module_payload.protocol.yj216.can.tc import payload_frames

    assembled = TeleControlCfgManager.assemble('yj216-tc', 'YJ216BB')
    app = bytes(int(x, 16) for x in assembled['hex'].split())
    chunks = payload_frames(app)
    assert chunks[0] == bytes.fromhex('000915BB11000000')
    assert chunks[1] == bytes.fromhex('00EA')


def test_tec_and_power_include_fixed_length() -> None:
    """TEC、功率的长度固定为 00 06，首帧 8 字节，次帧是 SUM。"""
    from module_payload.protocol.yj216.can.tc import payload_frames

    tec = TeleControlCfgManager.assemble('yj216-tc', 'YJ216DD')
    power = TeleControlCfgManager.assemble('yj216-tc', 'YJ216EE')
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
