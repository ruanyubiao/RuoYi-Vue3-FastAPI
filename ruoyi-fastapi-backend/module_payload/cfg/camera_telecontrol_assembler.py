"""SC-LINK41EP 相机遥控组帧：EB90 | type | id | len | seq | data | chk。"""

from __future__ import annotations

from typing import Any

from module_payload.cfg.telecontrol_assembler import calc_checksum, encode_component

FRAME_HEADER = bytes([0xEB, 0x90])


def assemble_camera_order(
    order: dict[str, Any],
    values: list[Any] | None = None,
    *,
    seq: int = 0,
) -> dict[str, Any]:
    """按指令定义组装完整控制帧（含帧头与校验和）。"""
    values = values or []
    components = order.get('component') or []
    parts = bytearray()
    for i, comp in enumerate(components):
        val = values[i] if i < len(values) else None
        if val is None or val == '':
            val = comp.get('defaultVal')
        parts.extend(encode_component(comp, val))

    frame_type = int(str(order.get('frameType') or 'D0'), 16) & 0xFF
    frame_id = int(str(order.get('frameId') or '00'), 16) & 0xFF
    cmd_hex = str(order.get('cmd') or '').strip()

    # D0 控制帧：数据区 = 指令码 + 参数；其它帧类型（如 D7）数据区仅为参数
    if frame_type == 0xD0 and cmd_hex:
        data = bytes([int(cmd_hex, 16) & 0xFF]) + bytes(parts)
    else:
        data = bytes(parts)

    data_len = len(data)
    seq_i = int(seq) & 0xFFFF
    body = bytearray(
        [
            frame_type,
            frame_id,
            (data_len >> 8) & 0xFF,
            data_len & 0xFF,
            (seq_i >> 8) & 0xFF,
            seq_i & 0xFF,
        ]
    )
    body.extend(data)
    chk = calc_checksum(bytes(body))
    frame = FRAME_HEADER + bytes(body) + bytes([chk])
    return {
        'hex': ' '.join(f'{b:02X}' for b in frame),
        'length': len(frame),
        'frameType': frame_type,
        'dataLen': data_len,
        'seq': seq_i,
        'checksum': chk,
    }


def assemble_camera_order_by_id(
    order_id: str,
    values: list[Any] | None = None,
    *,
    seq: int = 0,
    reload: bool = False,
) -> dict[str, Any]:
    """按指令 id 组相机遥控帧；values 为控件原值列表。"""
    from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, cfg_id_for_camera

    return TeleControlCfgManager.get(cfg_id_for_camera(), reload=reload).assemble(
        order_id, values, seq=seq
    )
