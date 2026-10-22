"""CAN 载荷设备模型（纯逻辑）：用 gpcan 的 ProtocolParser 拼工控机下行帧，用 ProtocolBuilder.build_telemetry_response 组上行遥测。

行为（依据 module_payload/protocol/{biu,xl,yj216}/can 与 gpcan.protocol）：
- BIU   ：遥测请求 `00 <code> 00×6` → 回 passthrough_biu_<code> 黄金样本（add_frame=False，样本已含 DataLen|3A|表号|..|SUM）
          `30 00 ...` 时间广播只记录；其它为遥控，只记录（BIU 遥控无总线应答帧）
- XL    ：遥测包（packet_type=0、无数据、副导头 01 速变/02 缓变）→ 回 passthrough_xlcan_ff（包格式，副导头同请求）
          遥控包（packet_type=1）只记录；实时遥控包的「下位机应答」格式代码中未定义，见 README 待确认
- YJ216 ：遥测请求 `00 FF 00×6` → 回 passthrough_yj216_ff，并按协议刷新 YJ001 遥测请求计数、YJ002 遥控正确计数，重算 SUM
          其它为遥控，只记录并计数
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field

from hil.samples import get_bytes

BIU_TM_GOLDEN = {
    0xFF: 'passthrough_biu_ff_1', 0xFD: 'passthrough_biu_fd_1', 0xFB: 'passthrough_biu_fb',
    0xF9: 'passthrough_biu_f9', 0xF7: 'passthrough_biu_f7', 0xFE: 'passthrough_biu_fe', 0xFC: 'passthrough_biu_fc',
}


def gpcan_available() -> tuple[bool, str]:
    try:
        importlib.import_module('gpcan.protocol.biu')
        return True, ''
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


@dataclass
class CanEvent:
    kind: str           # tm_request / telecommand / broadcast / unknown
    payload: bytes
    can_id: int
    meta: dict = field(default_factory=dict)


def _msg_payload(msg) -> bytes:
    """优先取解包后的 payload（XL 遥测请求包 payload 为空，不能回落到 data）。"""
    if getattr(msg, 'payload', None) is not None:
        return bytes(msg.payload)
    return bytes(msg.data or b'')


def to_recv_objs(frames: list[tuple[int, bytes]]) -> list:
    from gpcan.sdk.can_sdk_def import CanRecvObj

    out = []
    for cid, data in frames:
        r = CanRecvObj()
        r.un_id = int(cid)
        r.str_data = bytes(data)
        r.un_data_len = len(data)
        out.append(r)
    return out


def send_objs_to_tuples(objs) -> list[tuple[int, bytes]]:
    return [(int(o.un_id), bytes(o.str_data)[: int(o.un_data_len)]) for o in objs]


class CanDeviceModel:
    def __init__(self, family: str) -> None:
        self.family = family
        self.mod = importlib.import_module(f'gpcan.protocol.{family}')
        self.parser = self.mod.ProtocolParser({})
        self.events: list[CanEvent] = []
        self.tm_req_count = 0
        self.tc_count = 0

    # ------------------------------------------------------------------
    def feed(self, frames: list[tuple[int, bytes]]) -> list[tuple[int, bytes]]:
        """喂入工控机下行 CAN 帧，返回需回送的帧 [(id, data)]。"""
        self.parser.feed(to_recv_objs(frames))
        replies: list[tuple[int, bytes]] = []
        while (msg := self.parser.get_msg()) is not None:
            replies += self._on_msg(msg)
        return replies

    def _builder_for(self, can_id: int):
        from gpcan.protocol.can_protocol_def import CanCableParam

        b = self.mod.ProtocolBuilder()
        if self.family == 'biu':
            addr = (can_id >> 3) & 0x1F
            b.set_cable_param(CanCableParam(n_node_addr_to=addr, n_cable_flag=(can_id >> 2) & 1))
        elif self.family == 'yj216':
            b.set_cable_param(CanCableParam(n_node_addr_to=(can_id >> 6) & 0xF, n_cable_flag=(can_id >> 2) & 1))
        return b

    def _on_msg(self, msg) -> list[tuple[int, bytes]]:
        payload = _msg_payload(msg)
        pp = dict(getattr(msg, 'packet_param', None) or {})
        src = list(getattr(msg, 'src', None) or [])
        can_id = int(src[0].un_id) if src else int(pp.get('un_id') or 0)
        if self.family == 'xl':
            return self._on_xl(payload, pp, can_id)
        if len(payload) == 8 and payload[0] == 0x00 and not any(payload[2:]):
            self.tm_req_count += 1
            self.events.append(CanEvent('tm_request', payload, can_id, {'code': payload[1]}))
            return self.tm_response(payload[1], can_id)
        if payload[:1] == b'\x30' and self.family == 'biu':
            self.events.append(CanEvent('broadcast', payload, can_id))
            return []
        self.tc_count += 1
        self.events.append(CanEvent('telecommand', payload, can_id))
        return []

    def _on_xl(self, payload: bytes, pp: dict, can_id: int) -> list[tuple[int, bytes]]:
        if pp.get('packet') and pp.get('packet_type') == 0 and not payload:
            sh = int(pp.get('sec_header') or 1)
            self.tm_req_count += 1
            self.events.append(CanEvent('tm_request', payload, can_id, {'sec_header': sh}))
            return self.tm_response(sh, can_id)
        kind = 'telecommand' if pp.get('packet_type') == 1 else 'broadcast'
        if kind == 'telecommand':
            self.tc_count += 1
        self.events.append(CanEvent(kind, payload, can_id, pp))
        return []

    # ------------------------------------------------------------------
    def tm_payload(self, code: int) -> bytes | None:
        if self.family == 'biu':
            key = BIU_TM_GOLDEN.get(code)
            return get_bytes(key) if key else None
        if self.family == 'xl':
            return get_bytes('passthrough_xlcan_ff')  # 速变/缓变均回 FF 主要包（仅此一份样本）
        if self.family == 'yj216':
            if code != 0xFF:
                return None
            fr = bytearray(get_bytes('passthrough_yj216_ff'))
            fr[2] = self.tm_req_count & 0xFF     # YJ001 遥测请求指令计数
            fr[3] = self.tc_count & 0xFF         # YJ002 遥控正确指令计数
            fr[-1] = sum(fr[:-1]) & 0xFF
            return bytes(fr)
        return None

    def tm_response(self, code: int, can_id: int = 0) -> list[tuple[int, bytes]]:
        data = self.tm_payload(code)
        if data is None:
            return []
        b = self._builder_for(can_id)
        if self.family == 'xl':
            built = b.build_telemetry_response(data, sec_header=code, add_frame=True)
        else:
            built = b.build_telemetry_response(data, add_frame=False)
        return send_objs_to_tuples(built.frames)

    def periodic_frames(self) -> list[tuple[int, bytes]]:
        """无请求时的主动推送（默认不用：三条总线都是请求-应答）。"""
        code = {'biu': 0xFF, 'xl': 0x01, 'yj216': 0xFF}[self.family]
        return self.tm_response(code)

    def telecommands(self) -> list[bytes]:
        return [e.payload for e in self.events if e.kind == 'telecommand']


def ground_build(family: str, kind: str, data: bytes = b'', **kw) -> list[tuple[int, bytes]]:
    """模拟工控机侧组帧（自测用）：kind = telecommand / tm_request。"""
    mod = importlib.import_module(f'gpcan.protocol.{family}')
    b = mod.ProtocolBuilder()
    built = b.build_telecommand(data) if kind == 'telecommand' else b.build_telemetry_request(**kw)
    return send_objs_to_tuples(built.frames)


def ground_parse(family: str, frames: list[tuple[int, bytes]]) -> list[bytes]:
    """模拟工控机侧拼帧（自测用）。"""
    mod = importlib.import_module(f'gpcan.protocol.{family}')
    p = mod.ProtocolParser({})
    p.feed(to_recv_objs(frames))
    out = []
    while (m := p.get_msg()) is not None:
        out.append(_msg_payload(m))
    return out
