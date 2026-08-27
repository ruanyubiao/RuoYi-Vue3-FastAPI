"""XL 单板遥控组帧（热控电机 / CPA-ZK）。

配置里多为完整固定帧或 EB90+分量；check=是 时对「长度字段～校验前」做字节累加和（不含帧头 EB90）。

复合帧（>8 字节）布局（与单帧统一：帧头后即为数据类型）：
  EB90 | type(0x0F) | len_be(2) | 设备号 | 指令码 | 参数… | chk
长度字段：值为「长度字段之后～校验和之前」字节数（不含长度字段自身、不含类型字节）。
"""

from __future__ import annotations

from typing import Any

from exceptions.exception import ServiceException
from module_payload.cfg.hex_text import hex_to_bytes
from module_payload.cfg.telecontrol_assembler import calc_checksum, encode_component
from module_payload.constants import EB90_HEADER

FRAME_HEADER = EB90_HEADER
# EB90(2) + type(1) + len(2)
_COMPLEX_PREFIX_LEN = 5


def _need_checksum(order: dict[str, Any]) -> bool:
    """配置 check=是/yes 时需要追加或重算校验和。"""
    raw = str(order.get('check') or '').strip().lower()
    return raw in ('是', 'yes', 'y', '1', 'true')


def _is_complex_frame(buf: bytes | bytearray) -> bool:
    """EB90 + 类型 0x0F 的复合帧。"""
    return len(buf) >= 7 and bytes(buf[0:2]) == FRAME_HEADER and buf[2] == 0x0F


def _declared_length(body: bytes | bytearray) -> int:
    """读取复合帧长度字段（大端）。"""
    return (body[3] << 8) | body[4]


def _set_declared_length(body: bytearray, value: int) -> None:
    """写入复合帧长度字段（大端）。"""
    body[3] = (value >> 8) & 0xFF
    body[4] = value & 0xFF


def _correct_complex_length(body: bytearray) -> str:
    """校正复合帧长度字段；body 不含校验和。返回提示文案（无则空）。"""
    if not _is_complex_frame(body):
        return ''
    expected = len(body) - _COMPLEX_PREFIX_LEN  # 去掉 EB90(2)+type(1)+len(2)
    if expected < 1:
        return ''
    old = _declared_length(body)
    if old == expected:
        return ''
    _set_declared_length(body, expected)
    return f'复合帧长度字段已纠正: 0x{old:04X} → 0x{expected:04X}'


def assemble_xl_board_order(order: dict[str, Any], values: list[Any] | None = None) -> dict[str, Any]:
    """按指令 component 列表组装；必要时校正复合帧长度并追加校验和。"""
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

    tip = ''
    need_chk = _need_checksum(order)

    if need_chk:
        # 已带正确校验则只剥末字节校正长度，再重算校验
        already_ok = (
            len(buf) >= 4
            and buf[0:2] == FRAME_HEADER
            and calc_checksum(buf[2:-1]) == buf[-1]
        )
        body = bytearray(buf[:-1] if already_ok else buf)
        tip = _correct_complex_length(body)
        buf = bytes(body) + bytes([calc_checksum(body[2:])])
    elif _is_complex_frame(buf) and len(buf) >= 8:
        # check=否 的固定完整帧：若末字节可视为校验，则校正长度并重算
        body_guess = bytearray(buf[:-1])
        declared = _declared_length(body_guess)
        looks_like_chk_frame = (
            len(buf) == _COMPLEX_PREFIX_LEN + declared + 1
            or calc_checksum(buf[2:-1]) == buf[-1]
        )
        if looks_like_chk_frame or declared != len(body_guess) - _COMPLEX_PREFIX_LEN:
            tip = _correct_complex_length(body_guess)
            if tip:
                buf = bytes(body_guess) + bytes([calc_checksum(body_guess[2:])])

    return {
        'hex': ' '.join(f'{b:02X}' for b in buf),
        'length': len(buf),
        'checksum': buf[-1] if buf else 0,
        'tip': tip,
        'lengthCorrected': bool(tip),
    }


def assemble_xl_board_order_by_id(
    board: str,
    order_id: str,
    values: list[Any] | None = None,
    *,
    reload: bool = False,
) -> dict[str, Any]:
    """按单板键与指令 id 从配置管理器组帧。"""
    from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, cfg_id_for_board

    return TeleControlCfgManager.get(cfg_id_for_board(board), reload=reload).assemble(order_id, values)


def classify_xl_tc_frame(data: bytes) -> str:
    """按协议判断单帧/复合帧/错误（用于调试与单测）。

    1. 长度<=8 且索引2为 0x0A → single
    2. 否则索引2为 0x0F 且长度字段与帧长一致 → complex
    3. 其它 → error
    """
    if not data:
        return 'error'
    if len(data) <= 8 and len(data) >= 3 and data[2] == 0x0A:
        return 'single'
    if len(data) >= 7 and data[0:2] == FRAME_HEADER and data[2] == 0x0F:
        body_len = (data[3] << 8) | data[4]
        # EB90(2) + type(1) + len(2) + body(body_len) + chk(1)
        if len(data) == _COMPLEX_PREFIX_LEN + body_len + 1:
            return 'complex'
    if len(data) >= 4 and data[0:2] != FRAME_HEADER and data[0] == 0x0F:
        # 无帧头的复合片段：type | len | body…
        body_len = (data[1] << 8) | data[2]
        if len(data) == 1 + 2 + body_len or len(data) == 1 + 2 + body_len + 1:
            return 'complex'
    return 'error'


def parse_fixed_hex_sample(hex_text: str) -> bytes:
    """把配置里的固定 Hex 样例转成字节。"""
    return hex_to_bytes(hex_text)
