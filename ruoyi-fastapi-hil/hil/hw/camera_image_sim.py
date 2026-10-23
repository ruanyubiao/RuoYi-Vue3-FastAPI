# -*- coding: utf-8 -*-
"""Test-PC side camera image serial responder (no PyQt).

Opens the local COM (COM9), waits for D6 pull requests from IPC image serial,
replies with chunks from a fixed grayscale ndarray (v16 or v17 framing).
"""
from __future__ import annotations

import threading
import time
from typing import Callable

import numpy as np
import serial

from hil.hw.camera_image_d6 import (
    DATA_CHUNK,
    REQ_SIZE,
    RESP_SIZE,
    build_response,
    build_response_v17,
    consume_rx,
    frame_id_is_first,
    frame_id_is_last,
    infer_n_from_last_seq,
    take_row_major_chunk,
)


class CameraImageSim:
    """Blocking-safe background responder for xl-camera-image / v17-image."""

    def __init__(
        self,
        port: str,
        *,
        protocol: str = "v16",
        baudrate: int = 2_000_000,
        pixels: np.ndarray | None = None,
        parity: str = "O",
    ) -> None:
        self.port = port
        self.protocol = "v17" if str(protocol).lower() in ("v17", "v1.7", "17") else "v16"
        self.baudrate = int(baudrate)
        self.parity = parity
        self._pixels = pixels
        self._lock = threading.Lock()
        self._ser: serial.Serial | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.rx_requests: list[tuple[int, int, int, bytes]] = []
        self.tx_responses: list[bytes] = []
        self.errors: list[str] = []
        self._busy = False
        self._xfer_pixels: np.ndarray | None = None

    def set_pixels(self, arr: np.ndarray) -> None:
        with self._lock:
            self._pixels = np.ascontiguousarray(arr, dtype=np.uint8)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        parity_map = {
            "N": serial.PARITY_NONE,
            "O": serial.PARITY_ODD,
            "E": serial.PARITY_EVEN,
        }
        self._ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=parity_map.get(str(self.parity).upper()[:1], serial.PARITY_ODD),
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,
            write_timeout=5.0,
        )
        try:
            self._ser.reset_input_buffer()
            self._ser.reset_output_buffer()
        except Exception:
            pass
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=f"cam-img-{self.port}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        th = self._thread
        if th:
            th.join(timeout=2.0)
        self._thread = None
        ser = self._ser
        self._ser = None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    def wait_tx_count(self, n: int, timeout: float = 30.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if len(self.tx_responses) >= n:
                return True
            time.sleep(0.05)
        return False

    def _loop(self) -> None:
        buf = bytearray()
        ser = self._ser
        assert ser is not None
        while not self._stop.is_set():
            try:
                if not ser.is_open:
                    break
                waiting = ser.in_waiting or 0
                chunk = ser.read(waiting or 1)
                if not chunk:
                    continue
                buf.extend(chunk)
                if len(buf) > 8192:
                    keep = buf[-2048:]
                    eb = keep.find(b"\xeb")
                    buf[:] = keep[eb:] if eb >= 0 else keep[-1:]
                self._drain(buf)
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    break
                self.errors.append(str(exc))
                time.sleep(0.02)

    def _drain(self, buf: bytearray) -> None:
        for ev in consume_rx(buf):
            if ev[0] != "ok":
                continue
            _tag, parsed, raw = ev
            assert parsed is not None
            frame_id, seq, image_no = parsed
            self.rx_requests.append((frame_id, seq, image_no, raw))
            self._reply(frame_id, seq, image_no)

    def _payload_for_request(self, arr: np.ndarray, frame_id: int, seq: int) -> bytes:
        if frame_id_is_last(frame_id):
            already = seq * DATA_CHUNK
            n_infer = infer_n_from_last_seq(seq)
            if n_infer:
                valid = n_infer * n_infer - already
                return take_row_major_chunk(arr, already, valid)[:valid]
            return take_row_major_chunk(arr, already, DATA_CHUNK)
        return take_row_major_chunk(arr, seq * DATA_CHUNK, DATA_CHUNK)

    def _reply(self, frame_id: int, seq: int, image_no: int) -> None:
        with self._lock:
            snapped = None if self._pixels is None else self._pixels.copy()
        if frame_id_is_first(frame_id):
            self._busy = False
            self._xfer_pixels = snapped
            self._busy = True
        arr = self._xfer_pixels
        if arr is None:
            arr = snapped
            self._xfer_pixels = arr
            self._busy = True
        if arr is None:
            self.errors.append("no pixels for reply")
            return
        payload = self._payload_for_request(arr, frame_id, seq)
        try:
            if self.protocol == "v17":
                resp = build_response_v17(frame_id, seq, image_no, payload)
            else:
                resp = build_response(frame_id, seq, image_no, payload)
            ser = self._ser
            if ser is None or not ser.is_open:
                return
            ser.write(resp)
            self.tx_responses.append(resp)
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"tx fail: {exc}")
        finally:
            if frame_id_is_last(frame_id):
                self._busy = False
                self._xfer_pixels = None
