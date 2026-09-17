"""XL CPA 指向遥控组帧（协议 V1.0）。

12 字节：EB90 | 命令字 1B | 数据 8B | 校验 1B。
多字节 Int32 小端（组件 endian=little）。
校验和：帧头～数据包全部字节相加取低 8 位（含 EB90）。
文档写遥测数据段 18 字节与样例矛盾；遥控侧本组装器按 12 字节样例实现。
"""

from __future__ import annotations

from typing import Any

from exceptions.exception import ServiceException
from module_payload.cfg.telecontrol_assembler import calc_checksum, encode_component
from module_payload.constants import EB90_HEADER

FRAME_HEADER = EB90_HEADER
FRAME_LEN = 12


def _need_checksum(order: dict[str, Any]) -> bool:
    """配置 check=是/yes 时需要追加或重算校验和。"""
    raw = str(order.get('check') or '').strip().lower()
    return raw in ('是', 'yes', 'y', '1', 'true')


def assemble_xl_cpazx_order(order: dict[str, Any], values: list[Any] | None = None) -> dict[str, Any]:
    """按指令 component 列表组装；校验含帧头 EB90。"""
    values = values or []
    components = order.get('component') or []
    parts = bytearray()
    try:
        for i, comp in enumerate(components):
            val = values[i] if i < len(values) else None
            parts.extend(encode_component(comp, val))
    except ValueError as e:
        raise ServiceException(message=str(e)) from e
    buf = bytes(parts)
    if not buf:
        raise ServiceException(message='指令数据为空')

    if _need_checksum(order):
        already_ok = (
            len(buf) >= 4
            and buf[0:2] == FRAME_HEADER
            and calc_checksum(buf[:-1]) == buf[-1]
        )
        body = buf[:-1] if already_ok else buf
        buf = bytes(body) + bytes([calc_checksum(body)])

    return {
        'hex': ' '.join(f'{b:02X}' for b in buf),
        'length': len(buf),
        'checksum': buf[-1] if buf else 0,
        'tip': '',
        'lengthCorrected': False,
    }


def assemble_xl_cpazx_order_by_id(
    order_id: str,
    values: list[Any] | None = None,
    *,
    reload: bool = False,
) -> dict[str, Any]:
    """按指令 id 从 CPA 指向遥控配置组帧。"""
    from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, cfg_id_for_board

    return TeleControlCfgManager.get(cfg_id_for_board('cpazx'), reload=reload).assemble(
        order_id, values
    )
