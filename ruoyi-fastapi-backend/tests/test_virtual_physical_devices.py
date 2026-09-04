"""虚拟物理设备联调：Windows COM1↔COM2、gpcan DEMO（须子进程收发）。

- 串口：系统同时有 COM1、COM2 时视为虚拟对；同进程两端可收发。
- CAN：``CanVendorType.CAN_VENDOR_DEMO`` 同参同进程只能开一次，收发必须分属两进程
  （说明见 ``test/pygpcan`` 与 ``test_can_demo_cross_process.py``）。

无虚拟设备时整组 skip，不影响纯单元。
"""

from __future__ import annotations

import multiprocessing
import os
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from virtual_hw import gpcan_demo_available, list_serial_port_names, virtual_com_pair

pytestmark = pytest.mark.virtual_hw

_JOIN_S = 12.0
_SERIAL_BAUD = 115_200
_SERIAL_PAYLOAD = b'PGT_VCOM_' + bytes(range(16))


# ---- 串口 COM1 ↔ COM2 ----


@pytest.fixture(scope='module')
def com_pair() -> tuple[str, str]:
    pair = virtual_com_pair()
    if not pair:
        pytest.skip('需要 Windows 虚拟串口 COM1 与 COM2（系统串口列表须同时存在）')
    return pair


def test_virtual_serial_pair_detected_in_port_list(com_pair: tuple[str, str]) -> None:
    names = list_serial_port_names()
    assert 'COM1' in names and 'COM2' in names
    assert com_pair == ('COM1', 'COM2')


def test_virtual_serial_loopback_both_directions(com_pair: tuple[str, str]) -> None:
    """COM1↔COM2 双向透传。"""
    import serial

    a, b = com_pair
    kwargs = dict(
        baudrate=_SERIAL_BAUD,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=1.0,
        write_timeout=2.0,
    )
    with serial.Serial(a, **kwargs) as sa, serial.Serial(b, **kwargs) as sb:
        for tx, rx in ((sa, sb), (sb, sa)):
            rx.reset_input_buffer()
            tx.reset_output_buffer()
            tx.write(_SERIAL_PAYLOAD)
            tx.flush()
            got = rx.read(len(_SERIAL_PAYLOAD))
            assert got == _SERIAL_PAYLOAD


def test_virtual_serial_collector_recv_peer_send(com_pair: tuple[str, str]) -> None:
    """SerialCollector 开一端收；对端 pyserial 发送。"""
    import serial

    from module_payload import redis_keys as rk
    from module_payload.collectors.serial_collector import SerialCollector

    tx_port, rx_port = com_pair
    device_id = rk.serial_id(rx_port)
    seen: list[bytes] = []

    with patch(
        'module_payload.collectors.base_collector.create_sync_redis',
        return_value=MagicMock(),
    ):
        coll = SerialCollector(
            device_id,
            {
                'port': rx_port,
                'baudrate': _SERIAL_BAUD,
                'parity': 'N',
                'dataBits': 8,
                'stopBits': 1,
                'source': 'home',
            },
        )

        def _capture_stream(direction: str, data: bytes, **_kwargs: Any) -> None:
            if direction == 'recv' and data:
                seen.append(bytes(data))

        # 原始 RX 走 _push_stream_io，不走 _push_io
        coll._push_stream_io = _capture_stream  # type: ignore[method-assign]
        coll._write_status = MagicMock()  # type: ignore[method-assign]
        coll._try_session_ingest = lambda *a, **k: None  # type: ignore[method-assign]
        coll._sync_plugin = lambda **kwargs: None  # type: ignore[method-assign]
        assert coll.setup(), 'SerialCollector 打开虚拟串口失败'
        try:
            with serial.Serial(
                tx_port,
                baudrate=_SERIAL_BAUD,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1.0,
                write_timeout=2.0,
            ) as tx:
                tx.reset_output_buffer()
                time.sleep(0.05)
                coll._reset_input_buffer()
                seen.clear()
                tx.write(_SERIAL_PAYLOAD)
                tx.flush()
                deadline = time.monotonic() + 3.0
                buf = bytearray()
                while time.monotonic() < deadline and len(buf) < len(_SERIAL_PAYLOAD):
                    coll.read_and_parse()
                    for chunk in seen:
                        buf.extend(chunk)
                    seen.clear()
                    if len(buf) < len(_SERIAL_PAYLOAD):
                        time.sleep(0.02)
                assert bytes(buf[: len(_SERIAL_PAYLOAD)]) == _SERIAL_PAYLOAD
        finally:
            coll.teardown()


# ---- CAN DEMO（子进程）----


def _spawn_ctx() -> multiprocessing.context.BaseContext:
    return multiprocessing.get_context('spawn')


def _demo_slot() -> tuple[int, int]:
    return 210 + (os.getpid() % 40), 0


def _open_demo(dev_index: int, can_index: int, baud: int = 500):
    from gpcan import CanCardParam, CanRetCode, CanSdkClient, CanVendorType

    ok = int(CanRetCode.CAN_RET_CODE_OK)
    client = CanSdkClient(
        int(CanVendorType.CAN_VENDOR_DEMO),
        CanCardParam(
            n_can_index=can_index,
            n_baud_rate=baud,
            n_dev_index=dev_index,
            n_can_timeout_read_ms=10,
        ),
    )
    if client.init_can() != ok:
        raise RuntimeError(f'demo init_can 失败: {client.get_last_error()}')
    if client.open_can() != ok:
        try:
            client.deinit_can()
        except Exception:
            pass
        raise RuntimeError(f'demo open_can 失败: {client.get_last_error()}')
    return client


def _close_demo(client: Any) -> None:
    if client is None:
        return
    for fn in ('close_can', 'deinit_can'):
        try:
            getattr(client, fn)()
        except Exception:
            pass


def _frames_of(objs: list[Any]) -> list[tuple[int, bytes]]:
    out: list[tuple[int, bytes]] = []
    for obj in objs:
        data = bytes(obj.str_data or b'')[: int(obj.un_data_len or 0)]
        out.append((int(obj.un_id), data))
    return out


def _kill(proc: multiprocessing.Process) -> None:
    if not proc.is_alive():
        return
    proc.terminate()
    proc.join(2)
    if proc.is_alive():
        proc.kill()
        proc.join(2)


def _recv_worker(
    q: multiprocessing.Queue,
    ready: multiprocessing.Event,
    dev_index: int,
    can_index: int,
    baud: int,
    n_want: int,
    timeout_s: float,
) -> None:
    client = None
    try:
        client = _open_demo(dev_index, can_index, baud)
        ready.set()
        deadline = time.monotonic() + timeout_s
        got: list[tuple[int, bytes]] = []
        while time.monotonic() < deadline and len(got) < n_want:
            got.extend(_frames_of(client.recv(64)))
            if len(got) < n_want:
                time.sleep(0.02)
        q.put(('ok', got))
    except Exception as exc:
        try:
            ready.set()
        except Exception:
            pass
        q.put(('err', f'{type(exc).__name__}: {exc}'))
    finally:
        _close_demo(client)


@pytest.fixture(scope='module')
def require_demo_can() -> None:
    if not gpcan_demo_available():
        pytest.skip('需要 gpcan 且支持 CanVendorType.CAN_VENDOR_DEMO 虚拟 CAN')


def test_demo_can_same_process_cannot_open_twice(require_demo_can: None) -> None:
    from gpcan.sdk.CanDemo.virtual_hardware import DeviceBusyError, VirtualHardwareError

    dev_index, can_index = _demo_slot()
    a = _open_demo(dev_index, can_index)
    b = None
    try:
        with pytest.raises((RuntimeError, VirtualHardwareError, DeviceBusyError)):
            b = _open_demo(dev_index, can_index)
    finally:
        _close_demo(b)
        _close_demo(a)


def test_demo_can_parent_send_child_recv(require_demo_can: None) -> None:
    """父进程发、子进程收（同参 DEMO 不能同进程两端）。"""
    ctx = _spawn_ctx()
    q: multiprocessing.Queue = ctx.Queue()
    ready = ctx.Event()
    dev_index, can_index = _demo_slot()
    want = [(0x201, bytes([0x10, 0x20, 0x30])), (0x202, bytes([0xAA]))]
    proc = ctx.Process(
        target=_recv_worker,
        args=(q, ready, dev_index, can_index, 500, len(want), 8.0),
        daemon=True,
    )
    sender = None
    proc.start()
    try:
        assert ready.wait(8.0), '接收子进程未能打开 DEMO CAN'
        sender = _open_demo(dev_index, can_index)
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            for un_id, data in want:
                sender.send(un_id, data, un_data_len=len(data))
            time.sleep(0.05)
        proc.join(_JOIN_S)
        assert not proc.is_alive(), '接收子进程未退出'
        kind, payload = q.get(timeout=2)
        assert kind == 'ok', payload
        assert payload[: len(want)] == want
    finally:
        _close_demo(sender)
        _kill(proc)
