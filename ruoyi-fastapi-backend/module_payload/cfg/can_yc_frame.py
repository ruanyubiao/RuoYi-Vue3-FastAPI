"""CAN 遥测应答复合帧校验与解析（对齐 C++ createCanYcAck / NetSwitchAndVerify）。"""

from __future__ import annotations

from typing import Any

from module_payload.error_text import checksum_mismatch, frame_len_mismatch, frame_len_over_limit

# PAYLOAD_CAN_FRAME_TYPE_YC_COMPLEX
CAN_YC_FRAME_TYPE_COMPLEX = 0x3A
# 与 C++ CAN_PACKET_RSP_YC_FULL_SIZE 对齐的宽松上限
CAN_YC_FULL_SIZE_MAX = 512


def hex_to_bytes(text: str) -> bytes:
    cleaned = ''.join(ch for ch in (text or '') if ch not in ' \t\r\n')
    if not cleaned:
        return b''
    if len(cleaned) % 2:
        cleaned = cleaned[:-1] + '0' + cleaned[-1]
    return bytes.fromhex(cleaned)


def calc_checksum_byte(data: bytes) -> int:
    return sum(data) & 0xFF


def verify_can_yc_frame(raw: bytes) -> tuple[bool, str, bytes]:
    """
    校验 CAN 遥测复合帧。

    帧格式: dataLen(2B, 大端) + frameType(1B) + dataType(1B) + payload + checksum(1B)
    dataLen = frameType + dataType + payload 的字节数（不含 checksum）
    realSize = dataLen + 3

    输入可长于 realSize（如外层组装缓冲、尾部填充），按头里的 dataLen 截取有效段，多余忽略。
    上限只约束「协议声明的有效帧长」，不约束输入缓冲总长。

    :return: (ok, message, normalized_frame)  normalized 为 realSize 长度的有效帧
    """
    kind = 'CAN 遥测'
    if not raw:
        return False, f'{kind} 数据为空', b''
    if len(raw) < 5:
        return False, f'{kind} 帧过短: 实际总长度：{len(raw)}，至少：5', b''

    data_len = (raw[0] << 8) | raw[1]
    real_size = data_len + 3
    if real_size > len(raw):
        return False, frame_len_mismatch(kind, data_len, real_size, len(raw)), b''
    if real_size > CAN_YC_FULL_SIZE_MAX:
        return False, frame_len_over_limit(kind, data_len, real_size, CAN_YC_FULL_SIZE_MAX), b''

    # 校验和覆盖 D1~D4（dataLen 两字节 + frameType + dataType + payload）
    expected = calc_checksum_byte(raw[0 : data_len + 2])
    actual = raw[data_len + 2]
    if expected != actual:
        return False, checksum_mismatch(kind, expected, actual), b''

    frame = raw[:real_size]
    frame_type = frame[2]
    if frame_type != CAN_YC_FRAME_TYPE_COMPLEX:
        return False, (
            f'{kind} 帧类型错误: 期望：{CAN_YC_FRAME_TYPE_COMPLEX:02X}， 帧内：{frame_type:02X}'
        ), b''

    return True, 'OK', frame


def parse_can_yc_frame(frame: bytes) -> dict[str, Any]:
    """从已校验帧提取 dataType / payload（不含 checksum）。"""
    data_len = (frame[0] << 8) | frame[1]
    data_type = frame[3]
    # payload = D4，位于 [4, data_len+2)
    payload = frame[4 : data_len + 2]
    return {
        'dataLen': data_len,
        'frameType': frame_type_hex(frame[2]),
        'dataType': f'{data_type:02X}',
        'payload': payload,
        'payloadHex': ' '.join(f'{b:02X}' for b in payload),
        'checksum': f'{frame[data_len + 2]:02X}',
        'size': len(frame),
    }


def frame_type_hex(v: int) -> str:
    return f'{v:02X}'
