"""串口/UDP 帧工具：校验和与按协议拆帧（与 module_payload/protocol 下各协议保持一致，只读复刻，不 import 后端）。

协议出处（仓库源码）：
- 相机 v1.6/v1.7  xl/camera/tc.py、tm_base.py：EB90 | type | id | len(2) | seq(2) | data | chk，chk=sum(type..data)&0xFF
- 单板 RKDJ/ZK/DJ xl/board/tc.py、tm.py：遥测 EB90 | len(2) | src | dst | data | chk，chk=sum(len..data)&0xFF；
                  遥控复合帧 EB90 | 0F | len(2) | 设备号 | 指令码 | 参数 | chk
- CPA 指向       xl/cpazx/tc.py、tm.py：遥控 12B EB90|cmd|data8|chk(含EB90)；遥测 29B 55AA|26B|chk(含55AA)
- YJ216 RS422     yj216/rs422/tc.py、tm.py：请求 EB90|cmd|len|data|sum16(cmd..data)；
                  应答 EB90|3A|len(2)|seq|data|sum16(data)
- 地检板 UDP      xl/eng.py：1BCF|len|src|dst|总包数|序号|828B|sum16|0A0D，定长 844
"""
from __future__ import annotations

EB90 = b'\xEB\x90'


def sum8(data: bytes) -> int:
    return sum(data) & 0xFF


def sum16(data: bytes) -> int:
    return sum(data) & 0xFFFF


# ---------------- 相机 ----------------
def camera_frame(frame_type: int, frame_id: int, seq: int, data: bytes) -> bytes:
    body = bytes([frame_type & 0xFF, frame_id & 0xFF, (len(data) >> 8) & 0xFF, len(data) & 0xFF,
                  (seq >> 8) & 0xFF, seq & 0xFF]) + bytes(data)
    return EB90 + body + bytes([sum8(body)])


def camera_parse(frame: bytes) -> dict | None:
    """解析一帧相机帧；不合法返回 None。"""
    if len(frame) < 9 or frame[:2] != EB90:
        return None
    n = (frame[4] << 8) | frame[5]
    if len(frame) != 9 + n:
        return None
    if sum8(frame[2:8 + n]) != frame[8 + n]:
        return None
    return {'type': frame[2], 'id': frame[3], 'seq': (frame[6] << 8) | frame[7], 'data': bytes(frame[8:8 + n])}


def camera_frame_len(buf: bytes) -> int | None:
    if len(buf) < 6:
        return None
    return 9 + ((buf[4] << 8) | buf[5])


def camera_patch(frame: bytes, *, data_patch: dict[int, int] | None = None, seq: int | None = None) -> bytes:
    """改相机帧数据区若干字节 / 帧序号，并重算校验。"""
    p = camera_parse(frame)
    if p is None:
        raise ValueError('不是合法相机帧')
    data = bytearray(p['data'])
    for i, v in (data_patch or {}).items():
        data[i] = v & 0xFF
    return camera_frame(p['type'], p['id'], p['seq'] if seq is None else seq, bytes(data))


# ---------------- 单板 ----------------
def board_frame_len(buf: bytes) -> int | None:
    """单板遥控：EB90 0F len(2) ... chk → 6+len；其它 EB90 帧按「空闲间隔」整块处理。"""
    if len(buf) < 5:
        return None
    if buf[2] == 0x0F:
        return 6 + ((buf[3] << 8) | buf[4])
    return None


def board_tm_valid(frame: bytes) -> bool:
    if len(frame) < 6 or frame[:2] != EB90:
        return False
    n = (frame[2] << 8) | frame[3]
    return len(frame) == 5 + n and sum8(frame[2:4 + n]) == frame[4 + n]


# ---------------- CPA 指向 ----------------
CPAZX_TC_LEN = 12
CPAZX_TM_LEN = 29


def cpazx_tm_valid(frame: bytes) -> bool:
    return len(frame) == CPAZX_TM_LEN and frame[:2] == b'\x55\xAA' and sum8(frame[:28]) == frame[28]


# ---------------- YJ216 RS422 ----------------
RS422_CMD_TO_TABLE = {0x01: 'LCWP20', 0x02: 'LCWP30', 0x03: 'LCWP40', 0x04: 'LCWP50',
                      0x05: 'LCWP60', 0x06: 'LCOS', 0x07: 'UPHI'}


def rs422_request(cmd: int, data: bytes = b'') -> bytes:
    body = bytes([cmd & 0xFF, len(data)]) + bytes(data)
    s = sum16(body)
    return EB90 + body + bytes([s >> 8, s & 0xFF])


def rs422_request_len(buf: bytes) -> int | None:
    if len(buf) < 4:
        return None
    return 6 + buf[3]


def rs422_parse_request(frame: bytes) -> dict | None:
    if len(frame) < 6 or frame[:2] != EB90:
        return None
    n = frame[3]
    if len(frame) != 6 + n:
        return None
    if sum16(frame[2:4 + n]) != ((frame[4 + n] << 8) | frame[5 + n]):
        return None
    return {'cmd': frame[2], 'data': bytes(frame[4:4 + n])}


def rs422_response(seq: int, data: bytes) -> bytes:
    s = sum16(data)
    n = len(data)
    return EB90 + bytes([0x3A, (n >> 8) & 0xFF, n & 0xFF, seq & 0xFF]) + bytes(data) + bytes([s >> 8, s & 0xFF])


def rs422_response_valid(frame: bytes) -> bool:
    if len(frame) < 8 or frame[:2] != EB90 or frame[2] != 0x3A:
        return False
    n = (frame[3] << 8) | frame[4]
    return len(frame) == 8 + n and sum16(frame[6:6 + n]) == ((frame[6 + n] << 8) | frame[7 + n])


# ---------------- 工程遥测 UDP ----------------
ENG_FRAME_SIZE = 844


def eng_frame_valid(frame: bytes) -> bool:
    return len(frame) == ENG_FRAME_SIZE and frame[:2] == b'\x1B\xCF' and frame[-2:] in (b'\x0A\x0D', b'\x0D\x0A')
