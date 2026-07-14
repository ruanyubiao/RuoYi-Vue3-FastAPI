"""主进程退出时带走采集子进程。

- Windows：Job Object + JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE（调试器强杀主进程也会关句柄杀子进程）
- POSIX：子进程 prctl(PR_SET_PDEATHSIG) + 主进程 atexit/信号兜底
"""

from __future__ import annotations

import atexit
import os
import signal
import sys
from subprocess import Popen
from typing import Any, Callable

_job_handle: Any = None
_hooks_installed = False


def _windows_ensure_job() -> Any:
    """创建（或复用）Kill-on-close 作业对象。"""
    global _job_handle
    if _job_handle is not None:
        return _job_handle

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ('ReadOperationCount', ctypes.c_uint64),
            ('WriteOperationCount', ctypes.c_uint64),
            ('OtherOperationCount', ctypes.c_uint64),
            ('ReadTransferCount', ctypes.c_uint64),
            ('WriteTransferCount', ctypes.c_uint64),
            ('OtherTransferCount', ctypes.c_uint64),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ('PerProcessUserTimeLimit', wintypes.LARGE_INTEGER),
            ('PerJobUserTimeLimit', wintypes.LARGE_INTEGER),
            ('LimitFlags', wintypes.DWORD),
            ('MinimumWorkingSetSize', ctypes.c_size_t),
            ('MaximumWorkingSetSize', ctypes.c_size_t),
            ('ActiveProcessLimit', wintypes.DWORD),
            ('Affinity', ctypes.c_size_t),
            ('PriorityClass', wintypes.DWORD),
            ('SchedulingClass', wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ('IoInfo', IO_COUNTERS),
            ('ProcessMemoryLimit', ctypes.c_size_t),
            ('JobMemoryLimit', ctypes.c_size_t),
            ('PeakProcessMemoryUsed', ctypes.c_size_t),
            ('PeakJobMemoryUsed', ctypes.c_size_t),
        ]

    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        return None

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(
        handle,
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        kernel32.CloseHandle(handle)
        return None

    _job_handle = handle
    return _job_handle


def assign_to_kill_job(proc: Popen) -> bool:
    """把子进程加入 Kill-on-close Job（Windows）。失败返回 False，调用方可依赖 atexit。"""
    if sys.platform != 'win32' or proc is None:
        return False
    handle = getattr(proc, '_handle', None)
    if not handle:
        return False
    job = _windows_ensure_job()
    if not job:
        return False
    import ctypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    if not kernel32.AssignProcessToJobObject(job, handle):
        # 常见于父进程已在不可嵌套 Job 中（部分 IDE）；忽略，走 atexit
        return False
    return True


def unix_child_preexec() -> None:
    """POSIX：父进程死后向本进程发 SIGTERM。"""
    if sys.platform == 'win32':
        return
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        PR_SET_PDEATHSIG = 1
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except Exception:
        pass
    # 父已先于 prctl 退出的竞态：再确认一次
    if os.getppid() == 1:
        os.kill(os.getpid(), signal.SIGTERM)


def install_shutdown_hooks(shutdown_fn: Callable[[], None]) -> None:
    """注册 atexit + SIGINT/SIGTERM，保证正常退出路径也会停采集进程。"""
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True

    def _safe_shutdown() -> None:
        try:
            shutdown_fn()
        except Exception:
            pass

    atexit.register(_safe_shutdown)

    def _signal_handler(signum: int, frame: Any) -> None:
        _safe_shutdown()
        # 恢复默认后再次抛出，让 uvicorn/调试器按原逻辑退出
        try:
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)
        except Exception:
            raise SystemExit(128 + int(signum)) from None

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)
        except Exception:
            pass
