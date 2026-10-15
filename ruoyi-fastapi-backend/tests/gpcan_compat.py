"""gpcan 1.0.5 在 Linux / macOS 上的两个已知缺陷及测试侧规避（不修改 wheel 本身）。

缺陷 1：``CanSdkClient.get_supported_device_list()`` 会依次导入全部厂商驱动；
    ``gpcan/sdk/CanUsbAlystPro/can_usb_alyst_pro.py`` 第 4 行在模块顶层
    ``from ctypes import WinDLL``，非 Windows 上直接 ``ImportError``，
    导致整个厂商枚举失败（DEMO 虚拟厂商本身是纯 Python，跨平台可用）。
    规避：DEMO 信息直接取 ``CAN_VENDOR_DISPLAY_NAMES`` 与 ``CanDemo`` 类。

缺陷 2：``gpcan/sdk/CanDemo/virtual_hardware.py`` 中 ``VirtualHardware._close_resources()``
    末尾在 AF_UNIX 下**无条件** ``_unlink_unix_socket(self._address)``；而 ``_elect_open()``
    一开始就调用 ``_close_resources()``。于是第二个打开同一通道的进程会先删掉对端
    正在监听的 ``/tmp/vhw_<channel>.sock``，随后 ``Client`` 连接报 ``FileNotFoundError``，
    自己再建一个新 Listener —— 两端都在“监听”，永远配不上对，收方收不到任何帧。
    Windows 用命名管道（无文件可删），所以只在 Linux / macOS 出现。
    规避：只有本实例确实持有 Listener 时才允许删除 socket 文件。
"""

from __future__ import annotations

import sys
from typing import Any

_PATCHED_ATTR = '_pgt_unix_unlink_patched'


def patch_virtual_hardware_unix_unlink() -> bool:
    """幂等地修补缺陷 2；Windows、未安装 gpcan、或 gpcan 已修复时什么也不做。返回是否打了补丁。"""
    if sys.platform == 'win32':
        return False
    try:
        from gpcan.sdk.CanDemo import virtual_hardware as vh
    except Exception:
        return False
    cls = vh.VirtualHardware
    if getattr(cls, _PATCHED_ATTR, False):
        return True
    if not _unlink_bug_present(vh):
        return False  # 已修复的 gpcan（不再误删对端 socket）：不打补丁，完全 no-op
    original = cls._close_resources

    def _close_resources(self: Any) -> None:
        if self._listener is not None:
            original(self)
            return
        # 本实例没有 Listener（从未监听，或作为 Client 连上了对端）：不能删对端的 socket 文件
        saved = vh._unlink_unix_socket
        vh._unlink_unix_socket = lambda _addr: None
        try:
            original(self)
        finally:
            vh._unlink_unix_socket = saved

    cls._close_resources = _close_resources
    setattr(cls, _PATCHED_ATTR, True)
    return True


def _unlink_bug_present(vh: Any) -> bool:
    """行为探测：未持有 Listener 的实例调用 ``_close_resources`` 后，socket 文件是否被删。

    探测失败（gpcan 内部结构变化等）时保守地返回 True —— 补丁本身只在“不持有 Listener”时
    阻止删除，对已修复版本也无副作用。
    """
    import os
    import tempfile
    import threading

    path = os.path.join(tempfile.gettempdir(), f'vhw_probe-{os.getpid()}.sock')
    try:
        open(path, 'w').close()
        probe = vh.VirtualHardware.__new__(vh.VirtualHardware)
        probe._lock = threading.Lock()
        probe._accept_shutdown = False
        probe._listener = None
        probe._conn = None
        probe._paired = threading.Event()
        probe._accept_thread = None
        probe._family = 'AF_UNIX'
        probe._address = path
        vh.VirtualHardware._close_resources(probe)
        return not os.path.exists(path)
    except Exception:
        return True
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def demo_vendor_info() -> tuple[str, int] | None:
    """DEMO 厂商显示名与通道数；不经过会导入 Windows 驱动的 get_supported_device_list。"""
    try:
        from gpcan import CanVendorType
        from gpcan.sdk.can_sdk_def import CAN_VENDOR_DISPLAY_NAMES
        from gpcan.sdk.CanDemo.can_demo import CanDemo
    except Exception:
        return None
    demo = int(CanVendorType.CAN_VENDOR_DEMO)
    return str(CAN_VENDOR_DISPLAY_NAMES.get(demo, '')), int(CanDemo.get_channel_count())


def vendor_enumeration_error() -> str:
    """get_supported_device_list 失败原因（成功返回空串），用于跳过说明。"""
    try:
        from gpcan import CanSdkClient

        CanSdkClient.get_supported_device_list()
    except Exception as exc:
        return f'{type(exc).__name__}: {exc}'
    return ''
