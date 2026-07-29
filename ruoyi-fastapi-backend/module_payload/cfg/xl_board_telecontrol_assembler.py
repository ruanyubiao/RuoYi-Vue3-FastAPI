"""XL 单板遥控组帧（热控电机 / CPA-ZK）。

配置里多为完整固定帧或 EB90+分量；check=是 时对「帧头～校验前」做字节累加和。
"""

from __future__ import annotations

from typing import Any

from exceptions.exception import ServiceException
from module_payload.cfg.telecontrol_assembler import calc_checksum, encode_component, hex_to_bytes


def _need_checksum(order: dict[str, Any]) -> bool:
    raw = str(order.get('check') or '').strip().lower()
    return raw in ('是', 'yes', 'y', '1', 'true')


def assemble_xl_board_order(order: dict[str, Any], values: list[Any] | None = None) -> dict[str, Any]:
    """按指令 component 列表组装；必要时追加校验和。"""
    values = values or []
    components = order.get('component') or []
    parts = bytearray()
    for i, comp in enumerate(components):
        val = values[i] if i < len(values) else None
        parts.extend(encode_component(comp, val))
    buf = bytes(parts)
    if not buf:
        raise ServiceException(message='指令数据为空')

    if _need_checksum(order):
        if len(buf) >= 2 and calc_checksum(buf[:-1]) == buf[-1]:
            pass
        else:
            buf = buf + bytes([calc_checksum(buf)])

    return {
        'hex': ' '.join(f'{b:02X}' for b in buf),
        'length': len(buf),
        'checksum': buf[-1] if buf else 0,
    }


def assemble_xl_board_order_by_id(
    board: str,
    order_id: str,
    values: list[Any] | None = None,
    *,
    reload: bool = False,
) -> dict[str, Any]:
    from module_payload.cfg.payload_config_loader import PayloadConfigLoader

    cfg = PayloadConfigLoader.get_xl_board_telecontrol_cfg(board, reload=reload)
    order = (cfg.get('order') or {}).get(order_id)
    if not order:
        raise ServiceException(message=f'{board} 指令 {order_id} 不存在')
    return assemble_xl_board_order(order, values)


def classify_xl_tc_frame(data: bytes) -> str:
    """按协议判断单帧/复合帧/错误（用于调试与单测）。

    1. 长度<=8 且索引2为 0x0A → single
    2. 否则索引4为 0x0F 且长度字段与帧长一致 → complex
    3. 其它 → error
    """
    if not data:
        return 'error'
    if len(data) <= 8 and len(data) >= 3 and data[2] == 0x0A:
        return 'single'
    if len(data) >= 7 and data[0:2] == bytes([0xEB, 0x90]) and data[4] == 0x0F:
        body_len = (data[2] << 8) | data[3]
        # EB90(2) + len(2) + body(body_len) + chk(1)
        if len(data) == 2 + 2 + body_len + 1:
            return 'complex'
    if len(data) >= 5 and data[0:2] != bytes([0xEB, 0x90]) and data[2] == 0x0F:
        # 无帧头的复合片段（仅 body）
        body_len = (data[0] << 8) | data[1]
        if len(data) == 2 + body_len or len(data) == 2 + body_len + 1:
            return 'complex'
    return 'error'


def parse_fixed_hex_sample(hex_text: str) -> bytes:
    return hex_to_bytes(hex_text)
