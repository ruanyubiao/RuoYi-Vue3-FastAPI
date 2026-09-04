"""process_guard：Job Object / POSIX preexec / shutdown hooks（全 mock，不杀真进程）。"""

from __future__ import annotations

import signal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import module_payload.collectors.process_guard as pg


@pytest.fixture(autouse=True)
def _reset_process_guard_globals():
    prev_job = pg._job_handle
    prev_hooks = pg._hooks_installed
    pg._job_handle = None
    pg._hooks_installed = False
    yield
    pg._job_handle = prev_job
    pg._hooks_installed = prev_hooks


def test_assign_to_kill_job_non_win32_or_no_proc(monkeypatch) -> None:
    monkeypatch.setattr(pg.sys, 'platform', 'linux')
    assert pg.assign_to_kill_job(MagicMock(_handle=1)) is False
    monkeypatch.setattr(pg.sys, 'platform', 'win32')
    assert pg.assign_to_kill_job(None) is False
    assert pg.assign_to_kill_job(SimpleNamespace()) is False
    assert pg.assign_to_kill_job(SimpleNamespace(_handle=0)) is False


def test_windows_ensure_job_reuses_and_create_fail(monkeypatch) -> None:
    monkeypatch.setattr(pg.sys, 'platform', 'win32')
    pg._job_handle = object()
    assert pg._windows_ensure_job() is pg._job_handle

    pg._job_handle = None
    fake_kernel = MagicMock()
    fake_kernel.CreateJobObjectW.return_value = 0

    class FakeWinDLL:
        def __init__(self, *_a, **_k):
            pass

    with patch('ctypes.WinDLL', return_value=fake_kernel):
        # Force import path inside function
        assert pg._windows_ensure_job() is None


def test_windows_ensure_job_setinfo_fail_closes(monkeypatch) -> None:
    monkeypatch.setattr(pg.sys, 'platform', 'win32')
    pg._job_handle = None
    fake_kernel = MagicMock()
    fake_kernel.CreateJobObjectW.return_value = 99
    fake_kernel.SetInformationJobObject.return_value = 0

    with patch('ctypes.WinDLL', return_value=fake_kernel):
        assert pg._windows_ensure_job() is None
    fake_kernel.CloseHandle.assert_called_with(99)


def test_windows_ensure_job_success(monkeypatch) -> None:
    monkeypatch.setattr(pg.sys, 'platform', 'win32')
    pg._job_handle = None
    fake_kernel = MagicMock()
    fake_kernel.CreateJobObjectW.return_value = 42
    fake_kernel.SetInformationJobObject.return_value = 1

    with patch('ctypes.WinDLL', return_value=fake_kernel):
        h = pg._windows_ensure_job()
    assert h == 42
    assert pg._job_handle == 42


def test_assign_to_kill_job_job_none_and_assign_fail(monkeypatch) -> None:
    monkeypatch.setattr(pg.sys, 'platform', 'win32')
    proc = SimpleNamespace(_handle=7)
    with patch.object(pg, '_windows_ensure_job', return_value=None):
        assert pg.assign_to_kill_job(proc) is False

    fake_kernel = MagicMock()
    fake_kernel.AssignProcessToJobObject.return_value = 0
    with (
        patch.object(pg, '_windows_ensure_job', return_value=11),
        patch('ctypes.WinDLL', return_value=fake_kernel),
    ):
        assert pg.assign_to_kill_job(proc) is False

    fake_kernel.AssignProcessToJobObject.return_value = 1
    with (
        patch.object(pg, '_windows_ensure_job', return_value=11),
        patch('ctypes.WinDLL', return_value=fake_kernel),
    ):
        assert pg.assign_to_kill_job(proc) is True


def test_unix_child_preexec_win32_noop(monkeypatch) -> None:
    monkeypatch.setattr(pg.sys, 'platform', 'win32')
    pg.unix_child_preexec()  # no raise


def test_unix_child_preexec_prctl_and_orphan(monkeypatch) -> None:
    monkeypatch.setattr(pg.sys, 'platform', 'linux')
    libc = MagicMock()
    killed = []

    def fake_kill(pid, sig):
        killed.append((pid, sig))

    with (
        patch('ctypes.CDLL', return_value=libc),
        patch.object(pg.os, 'getppid', return_value=1),
        patch.object(pg.os, 'getpid', return_value=123),
        patch.object(pg.os, 'kill', side_effect=fake_kill),
    ):
        pg.unix_child_preexec()
    libc.prctl.assert_called()
    assert killed == [(123, signal.SIGTERM)]

    # prctl boom is swallowed; still checks ppid
    killed.clear()
    with (
        patch('ctypes.CDLL', side_effect=OSError('no')),
        patch.object(pg.os, 'getppid', return_value=1),
        patch.object(pg.os, 'getpid', return_value=9),
        patch.object(pg.os, 'kill', side_effect=fake_kill),
    ):
        pg.unix_child_preexec()
    assert killed == [(9, signal.SIGTERM)]


def test_install_shutdown_hooks_idempotent_and_signal(monkeypatch) -> None:
    calls = []

    def shutdown():
        calls.append(1)

    real_signal = signal.signal
    real_getsignal = signal.getsignal
    prev_int = real_getsignal(signal.SIGINT)
    prev_term = real_getsignal(signal.SIGTERM)
    try:
        with patch.object(pg.atexit, 'register') as reg:
            pg.install_shutdown_hooks(shutdown)
            pg.install_shutdown_hooks(shutdown)  # second is no-op
            assert reg.call_count == 1

            # invoke registered atexit callback once
            safe = reg.call_args[0][0]
            safe()
            safe()  # idempotent
            assert calls == [1]

        # reinstall fresh for signal path
        pg._hooks_installed = False
        calls.clear()
        boom_prev = MagicMock(side_effect=RuntimeError('prev'))
        monkeypatch.setattr(pg.signal, 'getsignal', lambda _s: boom_prev)
        captured = {}

        def capture_signal(sig, handler):
            captured[sig] = handler

        monkeypatch.setattr(pg.signal, 'signal', capture_signal)
        pg.install_shutdown_hooks(shutdown)
        handler = captured[signal.SIGINT]
        with pytest.raises(SystemExit):
            handler(signal.SIGINT, None)
        assert calls == [1]

        # callable prev that works → no SystemExit
        pg._hooks_installed = False
        calls.clear()
        ok_prev = MagicMock()
        monkeypatch.setattr(pg.signal, 'getsignal', lambda _s: ok_prev)
        captured.clear()
        pg.install_shutdown_hooks(shutdown)
        handler = captured[signal.SIGTERM]
        handler(signal.SIGTERM, None)
        ok_prev.assert_called_once()
        assert calls == [1]

        # signal.signal raises → ignored
        pg._hooks_installed = False
        monkeypatch.setattr(pg.signal, 'signal', MagicMock(side_effect=ValueError('no')))
        pg.install_shutdown_hooks(lambda: None)
    finally:
        monkeypatch.setattr(pg.signal, 'signal', real_signal)
        monkeypatch.setattr(pg.signal, 'getsignal', real_getsignal)
        real_signal(signal.SIGINT, prev_int)
        real_signal(signal.SIGTERM, prev_term)


def test_safe_shutdown_swallows_shutdown_errors(monkeypatch) -> None:
    pg._hooks_installed = False

    def boom():
        raise RuntimeError('x')

    with patch.object(pg.atexit, 'register') as reg:
        monkeypatch.setattr(signal, 'signal', lambda *_a, **_k: None)
        monkeypatch.setattr(signal, 'getsignal', lambda _s: signal.SIG_DFL)
        pg.install_shutdown_hooks(boom)
        safe = reg.call_args[0][0]
        safe()  # should not raise
