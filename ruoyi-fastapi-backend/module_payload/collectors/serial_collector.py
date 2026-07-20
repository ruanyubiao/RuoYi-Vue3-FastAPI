"""
串口采集进程：相机图像(EB 90 协议)与通用串口指令。
参考 test/showimg/serial_image_viewer.py
"""

from __future__ import annotations

import base64
import time
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collectors.base_collector import BaseCollector
from module_payload.collectors.redis_sync import dumps_json

FRAME_HEADER = bytes([0xEB, 0x90])
FRAME_TYPE = 0xD6
FRAME_ID_FIRST = 0x04
FRAME_ID_MID = 0x02
FRAME_ID_LAST = 0x01
DATA_LEN_REQ = 0x0001
DATA_CHUNK_SIZE = 256
FRAME_FAIL_RETRY = 5

RESOLUTION_MAP = {
    '400×400': (400, 400),
    '256×256': (256, 256),
    '128×128': (128, 128),
    '64×64': (64, 64),
}


def _calc_checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def _build_request_frame(frame_id: int, seq: int, image_no: int) -> bytes:
    body = bytes(
        [
            FRAME_TYPE,
            frame_id,
            (DATA_LEN_REQ >> 8) & 0xFF,
            DATA_LEN_REQ & 0xFF,
            (seq >> 8) & 0xFF,
            seq & 0xFF,
            image_no,
        ]
    )
    return FRAME_HEADER + body + bytes([_calc_checksum(body)])


def _parse_response_frame(data: bytes):
    if len(data) < 266 or data[0:2] != FRAME_HEADER or data[2] != FRAME_TYPE:
        return None
    seq = (data[6] << 8) | data[7]
    image_no = data[8]
    chunk = data[9:265]
    if _calc_checksum(data[2:265]) != data[265]:
        return None
    return seq, image_no, bytes(chunk)


class SerialCollector(BaseCollector):
    def __init__(self, device_id: str, config: dict[str, Any]) -> None:
        super().__init__(device_id, config)
        self._ser = None
        self._camera_enabled = False
        self._camera_cfg: dict[str, Any] = {}

    def setup(self) -> bool:
        import serial

        port = self.config.get('port') or self.device_id.replace('serial:', '')
        data_bits = int(self.config.get('data_bits', 8))
        stop_bits = float(self.config.get('stop_bits', 1))
        parity = str(self.config.get('parity', 'O')).upper()
        flow = str(self.config.get('flow_control', 'none')).upper().replace('/', '_').replace(' ', '')

        bytesize_map = {
            5: serial.FIVEBITS,
            6: serial.SIXBITS,
            7: serial.SEVENBITS,
            8: serial.EIGHTBITS,
        }
        stopbits_map = {
            1.0: serial.STOPBITS_ONE,
            1.5: serial.STOPBITS_ONE_POINT_FIVE,
            2.0: serial.STOPBITS_TWO,
        }
        parity_map = {
            'N': serial.PARITY_NONE,
            'E': serial.PARITY_EVEN,
            'O': serial.PARITY_ODD,
            'M': serial.PARITY_MARK,
            'S': serial.PARITY_SPACE,
        }

        try:
            self._ser = serial.Serial(
                port=port,
                baudrate=int(self.config.get('baudrate', 2_000_000)),
                bytesize=bytesize_map.get(data_bits, serial.EIGHTBITS),
                parity=parity_map.get(parity, serial.PARITY_ODD),
                stopbits=stopbits_map.get(stop_bits, serial.STOPBITS_ONE),
                xonxoff=flow in ('XONXOFF', 'XON_XOFF', 'RTSCTS_XONXOFF', 'RTS_CTS_XON_XOFF', 'DTRDSR_XONXOFF', 'DTR_DSR_XON_XOFF'),
                rtscts=flow in ('RTSCTS', 'RTS_CTS', 'RTSCTS_XONXOFF', 'RTS_CTS_XON_XOFF'),
                dsrdtr=flow in ('DTRDSR', 'DTR_DSR', 'DTRDSR_XONXOFF', 'DTR_DSR_XON_XOFF'),
                timeout=0.1,
            )
        except Exception as e:
            # 端口被占用 / 无权限等：写 error 状态供主进程 _wait_channel_ready 感知
            self._ser = None
            msg = str(e) or e.__class__.__name__
            self._write_status('error', f'串口打开失败: {msg}')
            return False
        self._camera_enabled = self.config.get('mode') == 'camera'
        self._camera_cfg = {
            'resolution': self.config.get('resolution', '256×256'),
            'image_no': int(self.config.get('image_no', 1)),
        }
        return True

    def handle_control(self, msg: dict[str, Any]) -> None:
        if msg.get('op') == 'camera_start':
            self._camera_enabled = True
            self._camera_cfg.update(msg.get('config') or {})
        elif msg.get('op') == 'camera_stop':
            self._camera_enabled = False

    def read_and_parse(self) -> None:
        if self._camera_enabled:
            self._acquire_image_once()
            return
        if not self._ser:
            return
        try:
            waiting = self._ser.in_waiting or 0
            if waiting <= 0:
                return
            data = self._ser.read(waiting)
            if data:
                self._push_io('recv', data)
                self._rx_count += 1
                from module_payload.constants import SRC_KIND_SERIAL

                self._try_session_ingest(data, self.device_id, SRC_KIND_SERIAL)
        except Exception:
            pass

    def _recv_response(self, timeout_s: float = 3.0) -> bytes | None:
        buf = b''
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline and self._running:
            waiting = self._ser.in_waiting or 1
            buf += self._ser.read(waiting)
            while len(buf) >= 2:
                idx = buf.find(FRAME_HEADER)
                if idx == -1:
                    buf = b''
                    break
                if idx > 0:
                    buf = buf[idx:]
                if len(buf) >= 266:
                    return buf[:266]
                break
        return None

    def _fetch_one_frame(self, frame_id: int, seq: int, image_no: int) -> bytes | None:
        for _ in range(FRAME_FAIL_RETRY):
            self._ser.reset_input_buffer()
            req = _build_request_frame(frame_id, seq, image_no)
            self._ser.write(req)
            resp = self._recv_response()
            if resp is None:
                continue
            parsed = _parse_response_frame(resp)
            if parsed:
                return parsed[2]
        return None

    def _acquire_image_once(self) -> None:
        res_key = self._camera_cfg.get('resolution', '256×256')
        width, height = RESOLUTION_MAP.get(res_key, (256, 256))
        image_no = int(self._camera_cfg.get('image_no', 1))
        total_pixels = width * height
        total_frames = total_pixels // DATA_CHUNK_SIZE
        mid_count = total_frames - 2
        image_data = bytearray()

        chunk = self._fetch_one_frame(FRAME_ID_FIRST, 0, image_no)
        if chunk is None:
            self._write_status('running', '图像采集失败(首帧)')
            time.sleep(1.0)
            return
        image_data.extend(chunk)
        for i in range(mid_count):
            chunk = self._fetch_one_frame(FRAME_ID_MID, i + 1, image_no)
            if chunk is None:
                self._write_status('running', f'图像采集失败(中间帧{i + 1})')
                time.sleep(1.0)
                return
            image_data.extend(chunk)
        last_seq = mid_count + 1
        chunk = self._fetch_one_frame(FRAME_ID_LAST, last_seq, image_no)
        if chunk is None:
            self._write_status('running', '图像采集失败(尾帧)')
            time.sleep(1.0)
            return
        image_data.extend(chunk)

        try:
            from PIL import Image
            import io

            img = Image.frombytes('L', (width, height), bytes(image_data[:total_pixels]))
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            b64 = base64.b64encode(buf.getvalue()).decode('ascii')
        except Exception:
            b64 = base64.b64encode(bytes(image_data[:total_pixels])).decode('ascii')

        meta = {
            'width': width,
            'height': height,
            'imageNo': image_no,
            'format': 'png',
            'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        self._redis.set(f'{rk.PREFIX}:{self.device_id}:image:meta', dumps_json(meta))
        self._redis.set(f'{rk.PREFIX}:{self.device_id}:image:data', b64)
        time.sleep(1.0)

    def execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        raw = bytes.fromhex(command.get('hex', '').replace(' ', ''))
        self._ser.write(raw)
        return {'success': True, 'message': 'OK'}

    def teardown(self) -> None:
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
