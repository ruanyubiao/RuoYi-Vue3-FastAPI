"""串口设备模型（纯逻辑，无 IO）：收字节 → 解析指令 → 产出应答；提供周期遥测帧。

每个模型：
- feed(data) -> list[bytes]   喂入工控机发来的字节流，返回需立即回送的帧
- telemetry() -> list[bytes]  每个遥测周期要推送的帧（遥测关闭时为空）
- received: list[bytes]       已解析出的完整指令帧（用于断言）
"""
from __future__ import annotations

import json
from collections.abc import Callable

from hil.config import CONFIG
from hil.protocol import frames as F
from hil.samples import get_bytes


class SerialDeviceModel:
    key = ''
    label = ''

    def __init__(self) -> None:
        self.received: list[bytes] = []
        self._buf = b''
        self.tm_enabled = True
        self.extra_rules: list[dict] = []  # 来自 reply_map.json 的自定义规则（{'_prefix','_reply'}）

    # 子类覆写：从缓冲区头部判断一帧长度；None=未知（按空闲间隔整块处理）
    def frame_len(self, buf: bytes) -> int | None:
        return None

    def on_frame(self, frame: bytes) -> list[bytes]:
        return []

    def telemetry(self) -> list[bytes]:
        return []

    # ------------------------------------------------------------------
    def feed(self, data: bytes, *, idle: bool = False) -> list[bytes]:
        """data 追加进缓冲；idle=True 表示串口已空闲，剩余字节视为一帧。"""
        self._buf += bytes(data)
        out: list[bytes] = []
        while self._buf:
            i = self._buf.find(F.EB90)
            if i > 0:  # 丢弃帧头前的杂字节
                self._buf = self._buf[i:]
            elif i < 0:
                if idle:
                    out += self._handle(self._buf)
                    self._buf = b''
                break
            n = self.frame_len(self._buf)
            if n is not None and len(self._buf) >= n:
                fr, self._buf = self._buf[:n], self._buf[n:]
                out += self._handle(fr)
                continue
            if n is None and idle:
                fr, self._buf = self._buf, b''
                out += self._handle(fr)
            break
        return out

    def _handle(self, frame: bytes) -> list[bytes]:
        self.received.append(bytes(frame))
        replies = self.on_frame(frame)
        for r in self.extra_rules:
            if frame.startswith(r['_prefix']):
                replies.append(r['_reply'])
        return replies


class CameraDevice(SerialDeviceModel):
    """相机控制串口（v1.6/v1.7 帧格式相同）。

    - D7「遥测开关」：data[0]=01 开始周期推 D8 慢遥测 + D9 快遥测，00 停止
    - D0 控制指令：慢遥测 CAM001「最后一条指令码」= 指令码，CAM002「指令执行情况」= AA(正确)，并立即回一帧 D8
    """

    def __init__(self, v17: bool = False, tm_on: bool = False) -> None:
        super().__init__()
        self.key = 'xl-camera-v17' if v17 else 'xl-camera'
        self.label = '相机v1.7' if v17 else '相机v1.6'
        self.d8 = get_bytes('passthrough_cam_v17_d8' if v17 else 'passthrough_cam_d8')
        self.d9 = get_bytes('passthrough_cam_v17_d9' if v17 else 'passthrough_cam_d9')
        self.tm_enabled = tm_on
        self.seq = 0
        self.last_cmd: int | None = None

    def frame_len(self, buf: bytes) -> int | None:
        return F.camera_frame_len(buf)

    def _d8(self) -> bytes:
        self.seq = (self.seq + 1) & 0xFFFF
        patch = {} if self.last_cmd is None else {0: self.last_cmd, 1: 0xAA}
        return F.camera_patch(self.d8, data_patch=patch, seq=self.seq)

    def on_frame(self, frame: bytes) -> list[bytes]:
        p = F.camera_parse(frame)
        if p is None:
            return []
        if p['type'] == 0xD7:
            self.tm_enabled = bool(p['data'][:1] and p['data'][0])
            return []
        if p['type'] == 0xD0 and p['data']:
            self.last_cmd = p['data'][0]
            return [self._d8()]
        return []

    def telemetry(self) -> list[bytes]:
        return [self._d8(), self.d9] if self.tm_enabled else []


class BoardDevice(SerialDeviceModel):
    """XL 单板（热控电机 0x33 / CPA-ZK 0x44）：周期推送 EB90 单板遥测；指令只记录（应答格式见 reply_map 待确认项）。"""

    GOLDEN = {'xl-rkdj': 'passthrough_board_rkdj', 'xl-zk': 'passthrough_board_zk'}

    def __init__(self, key: str) -> None:
        super().__init__()
        self.key = key
        self.label = key
        self.tm = get_bytes(self.GOLDEN[key])

    def frame_len(self, buf: bytes) -> int | None:
        return F.board_frame_len(buf)

    def telemetry(self) -> list[bytes]:
        return [self.tm] if self.tm_enabled else []


class CpazxDevice(SerialDeviceModel):
    """CPA 指向：遥控定长 12B；周期推送 29B 55AA 遥测。"""

    def __init__(self) -> None:
        super().__init__()
        self.key = 'xl-cpazx'
        self.label = 'CPA指向'
        self.tm = get_bytes('passthrough_cpazx')

    def frame_len(self, buf: bytes) -> int | None:
        return F.CPAZX_TC_LEN

    def telemetry(self) -> list[bytes]:
        return [self.tm] if self.tm_enabled else []


class Rs422Device(SerialDeviceModel):
    """YJ216 RS422：收到遥测请求（指令码 01~07）→ 回 EB90 3A 应答，数据区长度按 YJ216-RS422-TeleMetryCfg 对应表。
    不主动推送（协议为一问一答）。数据区默认全 0（字段值无业务含义，只验证链路与拆帧）。"""

    def __init__(self) -> None:
        super().__init__()
        self.key = 'yj216-rs422'
        self.label = 'YJ216 RS422'
        self.tm_enabled = False
        self.seq = 0
        self.spans = rs422_table_spans()
        self.fill: Callable[[str, int], bytes] = lambda table, n: bytes(n)

    def frame_len(self, buf: bytes) -> int | None:
        return F.rs422_request_len(buf)

    def on_frame(self, frame: bytes) -> list[bytes]:
        p = F.rs422_parse_request(frame)
        if p is None:
            return []
        table = F.RS422_CMD_TO_TABLE.get(p['cmd'])
        if table is None or table not in self.spans:
            return []
        self.seq = (self.seq + 1) & 0xFF
        return [F.rs422_response(self.seq, self.fill(table, self.spans[table]))]


def rs422_table_spans() -> dict[str, int]:
    """与 yj216/rs422/tm.py::_table_spans 同算法：每表 max(bytepos + ceil(bits/8))。"""
    p = CONFIG.assets_cfg_dir / 'YJ216-RS422-TeleMetryCfg.json'
    cfg = json.loads(p.read_text(encoding='utf-8'))
    spans: dict[str, int] = {}
    for key, table in (cfg.get('table') or {}).items():
        end = 0
        for row in table.get('row') or []:
            bits = int(row.get('bits') or 8)
            pos = int(row.get('bytepos') or 0)
            end = max(end, pos + (bits + 7) // 8)
        spans[str(key)] = end
    return spans


def make_serial_device(key: str) -> SerialDeviceModel:
    if key == 'xl-camera':
        return CameraDevice(v17=False)
    if key == 'xl-camera-v17':
        return CameraDevice(v17=True)
    if key in BoardDevice.GOLDEN:
        return BoardDevice(key)
    if key == 'xl-cpazx':
        return CpazxDevice()
    if key == 'yj216-rs422':
        return Rs422Device()
    raise KeyError(f'未知串口设备: {key}')
