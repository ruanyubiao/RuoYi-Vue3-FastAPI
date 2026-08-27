"""采集/回放管理器：主进程 Redis 客户端复用，shutdown 时关闭。"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from module_payload.collectors.process_manager import CollectorProcessManager
from module_payload.fileplay.manager import FilePlayManager


def _collector_mgr() -> CollectorProcessManager:
    mgr = CollectorProcessManager.__new__(CollectorProcessManager)
    mgr._registry = {}
    mgr._lifecycle_lock = threading.RLock()
    mgr._shutting_down = False
    mgr._redis = None
    return mgr


def test_process_manager_reuses_redis_across_ctrl_pushes() -> None:
    mgr = _collector_mgr()
    client = MagicMock()
    with patch(
        'module_payload.collectors.redis_sync.create_sync_redis',
        return_value=client,
    ) as factory:
        mgr._push_ctrl('serial:COM1', {'op': 'stop'})
        mgr._push_ctrl('serial:COM1', {'op': 'session_changed'})
        mgr._clear_channel_status('can:3:0:0')
    assert factory.call_count == 1
    assert client.lpush.call_count == 2
    client.close.assert_not_called()
    mgr.shutdown_all()
    client.close.assert_called()


def test_process_manager_wait_ready_does_not_close_shared_client() -> None:
    mgr = _collector_mgr()
    client = MagicMock()
    client.get.return_value = '{"state":"running","connected":true}'
    with patch(
        'module_payload.collectors.redis_sync.create_sync_redis',
        return_value=client,
    ):
        ok, err = mgr._wait_channel_ready('serial:COM1', proc=None, timeout_s=1.0)
    assert ok is True
    assert err == ''
    client.close.assert_not_called()


def test_fileplay_manager_reuses_redis() -> None:
    mgr = FilePlayManager.__new__(FilePlayManager)
    mgr._proc = None
    mgr._lock = threading.RLock()
    mgr._local_engine = None
    mgr._use_local = False
    mgr._log_fp = None
    mgr._redis = None
    client = MagicMock()
    with (
        patch.object(mgr, 'ensure_worker', return_value=None),
        patch(
            'module_payload.collectors.redis_sync.create_sync_redis',
            return_value=client,
        ) as factory,
    ):
        mgr.send({'op': 'ensure', 'pathHash': 'h', 'index': 1})
        mgr.send({'op': 'ensure', 'pathHash': 'h', 'index': 2})
    assert factory.call_count == 1
    assert client.lpush.call_count == 2
    client.close.assert_not_called()
    mgr.shutdown()
    client.close.assert_called()
