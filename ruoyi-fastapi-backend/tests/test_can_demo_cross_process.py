"""CAN 通讯测试：gpcan 演示/虚拟设备，收发必须分属两个进程。

Demo 厂商（``CanVendorType.CAN_VENDOR_DEMO == 0``）底层是跨进程命名管道
（Windows ``\\\\.\\pipe\\vhw_*``）。同一进程内同一 ``vcan-{dev}-{ch}`` 只能打开一次，
因此不能在 pytest 进程里自发自收，也不能用 ``CAN_SEND_TYPE_SEND_RECV`` 代替对端。

约定：接收端进程先打开，发送端进程后打开；发送端在配对完成前会静默丢帧，因此发送带重试。
设备序号避开界面常用的 ``dev_index=0``。
"""

from __future__ import annotations

import multiprocessing
import os
import time
from typing import Any

import pytest

from gpcan import (
    CanCardParam,
    CanRetCode,
    CanSdkClient,
    CanVendorType,
)

DEMO_VENDOR = int(CanVendorType.CAN_VENDOR_DEMO)
_OK = int(CanRetCode.CAN_RET_CODE_OK)
_JOIN_S = 12.0


def _spawn_ctx() -> multiprocessing.context.BaseContext:
    return multiprocessing.get_context('spawn')


def _demo_slot() -> tuple[int, int]:
    """本用例独占的虚拟卡/通道，避开首页默认 0:0。"""
    return 200 + (os.getpid() % 50), 0


def _card(dev_index: int, can_index: int, baud: int = 500) -> CanCardParam:
    return CanCardParam(
        n_can_index=can_index,
        n_baud_rate=baud,
        n_dev_index=dev_index,
        n_can_timeout_read_ms=10,
    )


def _open_sdk(dev_index: int, can_index: int, baud: int = 500) -> CanSdkClient:
    client = CanSdkClient(DEMO_VENDOR, _card(dev_index, can_index, baud))
    if client.init_can() != _OK:
        raise RuntimeError(f'demo init_can 失败: {client.get_last_error()}')
    if client.open_can() != _OK:
        try:
            client.deinit_can()
        except Exception:
            pass
        raise RuntimeError(f'demo open_can 失败: {client.get_last_error()}')
    return client


def _close_sdk(client: CanSdkClient | None) -> None:
    if client is None:
        return
    try:
        client.close_can()
    except Exception:
        pass
    try:
        client.deinit_can()
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
    """子进程：只收，不发。"""
    client = None
    try:
        client = _open_sdk(dev_index, can_index, baud)
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
        _close_sdk(client)


def _collector_recv_worker(
    q: multiprocessing.Queue,
    ready: multiprocessing.Event,
    vendor: int,
    dev_index: int,
    can_index: int,
    baud: int,
    n_want: int,
    timeout_s: float,
) -> None:
    """采集子进程：只收。Redis 用假对象，不走真实指令队列。"""
    from unittest.mock import MagicMock, patch

    from module_payload import redis_keys as rk
    from module_payload.constants import ASSEMBLER_PASSTHROUGH

    with patch(
        'module_payload.collectors.base_collector.create_sync_redis',
        return_value=MagicMock(),
    ):
        from module_payload.collectors.can_collector import CanCollector

        device_id = rk.can_card_id(vendor, dev_index)
        coll = CanCollector(
            device_id,
            {
                'vendor': vendor,
                'dev_index': dev_index,
                'channels': [
                    {
                        'vendor': vendor,
                        'dev_index': dev_index,
                        'can_index': can_index,
                        'baud_rate': baud,
                        'assembler_id': ASSEMBLER_PASSTHROUGH,
                    }
                ],
            },
        )
        seen: list[tuple[int, bytes]] = []

        def _capture(direction: str, data: bytes, **kwargs: Any) -> None:
            if direction == 'recv':
                seen.append((int(kwargs.get('frame_id') or 0), bytes(data or b'')))

        coll._push_io = _capture  # type: ignore[method-assign]
        coll._write_status = MagicMock()  # type: ignore[method-assign]
        coll._write_channel_status = MagicMock()  # type: ignore[method-assign]
        coll._ingest_can_frames = lambda *a, **k: None  # type: ignore[method-assign]
        coll._get_session_cached = lambda *a, **k: {}  # type: ignore[method-assign]
        try:
            if not coll.setup():
                raise RuntimeError('CanCollector.setup 失败')
            ready.set()
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline and len(seen) < n_want:
                coll.read_and_parse()
                if len(seen) < n_want:
                    time.sleep(0.02)
            q.put(('ok', list(seen)))
        except Exception as exc:
            try:
                ready.set()
            except Exception:
                pass
            q.put(('err', f'{type(exc).__name__}: {exc}'))
        finally:
            try:
                coll.teardown()
            except Exception:
                pass


def _collector_send_worker(
    q: multiprocessing.Queue,
    ready: multiprocessing.Event,
    go_send: multiprocessing.Event,
    vendor: int,
    dev_index: int,
    can_index: int,
    baud: int,
    frame_id: int,
    hex_text: str,
    timeout_s: float,
) -> None:
    """采集子进程：只发。对端必须已在另一进程打开。"""
    from unittest.mock import MagicMock, patch

    from module_payload import redis_keys as rk
    from module_payload.constants import ASSEMBLER_PASSTHROUGH

    with patch(
        'module_payload.collectors.base_collector.create_sync_redis',
        return_value=MagicMock(),
    ):
        from module_payload.collectors.can_collector import CanCollector

        device_id = rk.can_card_id(vendor, dev_index)
        coll = CanCollector(
            device_id,
            {
                'vendor': vendor,
                'dev_index': dev_index,
                'channels': [
                    {
                        'vendor': vendor,
                        'dev_index': dev_index,
                        'can_index': can_index,
                        'baud_rate': baud,
                        'assembler_id': ASSEMBLER_PASSTHROUGH,
                    }
                ],
            },
        )
        coll._push_io = MagicMock()  # type: ignore[method-assign]
        coll._write_status = MagicMock()  # type: ignore[method-assign]
        coll._write_channel_status = MagicMock()  # type: ignore[method-assign]
        coll._ingest_can_frames = lambda *a, **k: None  # type: ignore[method-assign]
        coll._get_session_cached = lambda *a, **k: {}  # type: ignore[method-assign]
        try:
            if not coll.setup():
                raise RuntimeError('CanCollector.setup 失败')
            ready.set()
            if not go_send.wait(timeout_s):
                raise TimeoutError('等待发送信号超时')
            result = None
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                result = coll.execute_command(
                    {
                        'can_index': can_index,
                        'frame_id': frame_id,
                        'hex': hex_text,
                    }
                )
                if result.get('success'):
                    break
                time.sleep(0.05)
            q.put(('ok', result))
        except Exception as exc:
            try:
                ready.set()
            except Exception:
                pass
            q.put(('err', f'{type(exc).__name__}: {exc}'))
        finally:
            try:
                coll.teardown()
            except Exception:
                pass


def _send_until(
    sender: CanSdkClient,
    frames: list[tuple[int, bytes]],
    deadline: float,
) -> None:
    while time.monotonic() < deadline:
        for un_id, data in frames:
            sender.send(un_id, data, un_data_len=len(data))
        time.sleep(0.05)


def test_demo_vendor_is_virtual_not_hardware() -> None:
    assert DEMO_VENDOR == 0
    info = CanSdkClient.get_supported_device_list()[DEMO_VENDOR]
    assert '演示' in info.name or '虚拟' in info.name
    assert info.channel_count == 4


def test_same_process_cannot_open_demo_twice() -> None:
    """进程内独占：同一虚拟通道不能在本进程再开一个对端。"""
    from gpcan.sdk.CanDemo.virtual_hardware import DeviceBusyError, VirtualHardwareError

    dev_index, can_index = _demo_slot()
    a = _open_sdk(dev_index, can_index)
    b = None
    try:
        with pytest.raises((RuntimeError, VirtualHardwareError, DeviceBusyError)):
            b = _open_sdk(dev_index, can_index)
    finally:
        _close_sdk(b)
        _close_sdk(a)


def test_sdk_parent_send_child_recv() -> None:
    """父进程只发、子进程只收。"""
    ctx = _spawn_ctx()
    q: multiprocessing.Queue = ctx.Queue()
    ready = ctx.Event()
    dev_index, can_index = _demo_slot()
    want = [(0x123, bytes([0x11, 0x22, 0x33, 0x44])), (0x124, bytes([0xAA, 0xBB]))]
    proc = ctx.Process(
        target=_recv_worker,
        args=(q, ready, dev_index, can_index, 500, len(want), 8.0),
        daemon=True,
    )
    sender = None
    proc.start()
    try:
        assert ready.wait(8.0), '接收子进程未能打开 demo CAN'
        sender = _open_sdk(dev_index, can_index)
        _send_until(sender, want, time.monotonic() + 6.0)
        proc.join(_JOIN_S)
        assert not proc.is_alive(), '接收子进程未退出'
        kind, payload = q.get(timeout=2)
        assert kind == 'ok', payload
        assert payload[: len(want)] == want
    finally:
        _close_sdk(sender)
        _kill(proc)


def test_collector_child_recv_parent_send() -> None:
    """CanCollector 在子进程只收；本进程只发。"""
    ctx = _spawn_ctx()
    q: multiprocessing.Queue = ctx.Queue()
    ready = ctx.Event()
    dev_index, can_index = _demo_slot()
    want = [(0x321, bytes([0xDE, 0xAD, 0xBE, 0xEF]))]
    proc = ctx.Process(
        target=_collector_recv_worker,
        args=(q, ready, DEMO_VENDOR, dev_index, can_index, 500, len(want), 8.0),
        daemon=True,
    )
    sender = None
    proc.start()
    try:
        assert ready.wait(10.0), '采集子进程未能打开 demo CAN'
        sender = _open_sdk(dev_index, can_index)
        _send_until(sender, want, time.monotonic() + 6.0)
        proc.join(_JOIN_S)
        assert not proc.is_alive(), '采集接收子进程未退出'
        kind, payload = q.get(timeout=2)
        assert kind == 'ok', payload
        assert payload[: len(want)] == want
    finally:
        _close_sdk(sender)
        _kill(proc)


def test_collector_child_send_parent_recv() -> None:
    """CanCollector 在子进程只发；本进程只收。"""
    ctx = _spawn_ctx()
    q: multiprocessing.Queue = ctx.Queue()
    ready = ctx.Event()
    go_send = ctx.Event()
    dev_index, can_index = _demo_slot()
    frame_id = 0x456
    payload = bytes([0x01, 0x02, 0x03, 0x04, 0x05])
    receiver = _open_sdk(dev_index, can_index)
    proc = ctx.Process(
        target=_collector_send_worker,
        args=(
            q,
            ready,
            go_send,
            DEMO_VENDOR,
            dev_index,
            can_index,
            500,
            frame_id,
            '01 02 03 04 05',
            8.0,
        ),
        daemon=True,
    )
    proc.start()
    try:
        assert ready.wait(10.0), '采集子进程未能打开 demo CAN'
        go_send.set()
        deadline = time.monotonic() + 8.0
        got: list[tuple[int, bytes]] = []
        while time.monotonic() < deadline and (frame_id, payload) not in got:
            got.extend(_frames_of(receiver.recv(64)))
            time.sleep(0.02)
        proc.join(_JOIN_S)
        kind, send_result = q.get(timeout=2)
        assert kind == 'ok', send_result
        assert send_result and send_result.get('success') is True
        assert (frame_id, payload) in got
    finally:
        _close_sdk(receiver)
        _kill(proc)
