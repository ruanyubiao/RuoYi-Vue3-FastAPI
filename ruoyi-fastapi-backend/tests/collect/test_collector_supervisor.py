"""监工命令分发、快照筛选和打开超时。"""

from __future__ import annotations

import json

import pytest

from module_payload import redis_keys as rk
from module_payload.collectors.snapshot_store import list_machines
from module_payload.collectors.supervisor import _dispatch
from module_payload.collectors.supervisor_client import OFFLINE_MESSAGE, invoke


class _Redis:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.members = set()
        self.removed = []

    def get(self, key):
        return self.data.get(key)

    def smembers(self, key):
        return set(self.members)

    def srem(self, key, *names):
        self.removed.extend(names)
        self.members.difference_update(names)


class _CmdRedis:
    def __init__(self):
        self.deleted = []
        self.pushed = []

    def delete(self, key):
        self.deleted.append(key)

    def lpush(self, key, value):
        self.pushed.append((key, value))

    def get(self, key):
        return None

    def close(self):
        pass


def test_dispatch_stop_and_unknown() -> None:
    class Manager:
        def stop(self, device_id):
            self.device_id = device_id

    manager = Manager()
    assert _dispatch(manager, 'stop', {'deviceId': 'serial:COM3'})['ok'] is True
    assert manager.device_id == 'serial:COM3'
    missed = _dispatch(manager, 'nope', {})
    assert missed['ok'] is False
    assert '未知命令' in missed['error']


def test_snapshot_hosts_filter_marks_offline() -> None:
    host = 'lab'
    key = rk.collector_snapshot_key(host)
    redis = _Redis({key: json.dumps({'host': host, 'registry': [{'deviceId': 'serial:COM1'}]})})
    named = list_machines(redis, ['lab', 'gone'])
    by_host = {item['host']: item for item in named}
    assert by_host['lab']['online'] is True
    assert by_host['gone']['online'] is False
    assert by_host['gone']['registry'] == []

    redis.members.update({'lab', 'stale'})
    listed = list_machines(redis, None)
    assert [item['host'] for item in listed] == ['lab']
    assert 'stale' in redis.removed


def test_build_document_writes_serial_scan_ok() -> None:
    from module_payload.collectors.snapshot_store import build_document

    assert build_document('lab', [], {'serialScanOk': True})['serialScanOk'] is True
    assert build_document('lab', [], {})['serialScanOk'] is False


def test_reconcile_serial_removes_missing_port(monkeypatch) -> None:
    from module_payload.collectors.supervisor import _reconcile_serial

    stopped: list[str] = []

    class Manager:
        def list_opened(self):
            return [
                {'type': 'serial', 'alive': True, 'deviceId': 'serial:COM9'},
                {'type': 'serial', 'alive': True, 'deviceId': 'serial:COM1'},
            ]

        def stop(self, device_id):
            stopped.append(device_id)

    deleted: list[str] = []

    class _Client:
        def close(self) -> None:
            return None

    monkeypatch.setattr(
        'module_payload.collectors.supervisor.create_sync_redis',
        lambda: _Client(),
    )
    monkeypatch.setattr(
        'module_payload.store.session_store.delete_session_sync',
        lambda _redis, device_id, _kind: deleted.append(device_id),
    )
    _reconcile_serial(
        Manager(),
        {'serialScanOk': True, 'serialPorts': [{'port': 'COM1'}]},
    )
    assert stopped == ['serial:COM9']
    assert deleted == ['serial:COM9']

    stopped.clear()
    _reconcile_serial(Manager(), {'serialScanOk': False, 'serialPorts': []})
    assert stopped == []


def test_invoke_times_out_when_supervisor_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.collectors.supervisor_client.create_sync_redis',
        lambda: _CmdRedis(),
    )
    with pytest.raises(RuntimeError, match=OFFLINE_MESSAGE):
        invoke('stop', {'deviceId': 'serial:COM1'}, timeout_s=0.15)


def test_alive_src_params_expands_can_and_skips_dead() -> None:
    from module_payload.collectors.supervisor import _alive_src_params

    alive = _alive_src_params(
        [
            {"type": "can", "alive": True, "deviceId": "can:3:0", "channels": [0, 1]},
            {"type": "can", "alive": False, "deviceId": "can:9:0", "channels": [0]},
            {"type": "serial", "alive": True, "deviceId": "serial:COM3"},
            {"type": "serial", "alive": True, "deviceId": ""},
            {"type": "can", "alive": True, "deviceId": "can:bad", "channels": [0]},
        ]
    )
    assert alive == {"can:3:0:0", "can:3:0:1", "serial:COM3"}


def _install_orphan_redis(monkeypatch, session_key: str, session_blob, *, fail_delete: bool = False) -> list:
    """三份孤儿对账用例共用的假 Redis。返回已删除的 key 列表。"""
    deleted: list = []

    class _FakeRedis:
        def scan(self, cursor=0, match=None, count=200):
            assert match == "payload:collector:lab:session:*"
            return 0, [session_key] if cursor == 0 else []

        def get(self, key):
            assert key == session_key
            return session_blob

        def delete(self, *keys):
            if fail_delete:
                raise RuntimeError("redis down")
            deleted.extend(keys)
            return len(keys)

        def close(self):
            return None

    monkeypatch.setattr(
        "module_payload.collectors.supervisor.create_sync_redis",
        lambda: _FakeRedis(),
    )
    monkeypatch.setattr(
        "module_payload.collectors.supervisor.normalize_collector_host",
        lambda h: h,
    )
    return deleted


def test_reconcile_orphan_sessions_deletes_when_process_table_empty(monkeypatch) -> None:
    """假 Redis + 空进程表：应删掉 session 及对应 status/heartbeat。"""
    from module_payload.collectors.supervisor import _reconcile_orphan_sessions
    from module_payload.store.session_store import dumps_session

    host = "lab"
    session_key = f"payload:collector:{host}:session:can:3:0:0"
    deleted = _install_orphan_redis(
        monkeypatch,
        session_key,
        dumps_session({"srcParam": "can:3:0:0", "openedAt": "2026-10-24 18:34:26"}),
    )

    class Manager:
        def list_opened(self):
            return []

    _reconcile_orphan_sessions(Manager(), host)
    assert session_key in deleted
    assert rk.status_key("can:3:0:0") in deleted
    assert rk.heartbeat_key("can:3:0:0") in deleted


def test_reconcile_orphan_sessions_reads_src_from_key_when_blob_empty(monkeypatch) -> None:
    """会话体没有 srcParam 时，从键前缀后面还原 can:3:0:0，并清 status/heartbeat。"""
    from module_payload.collectors.supervisor import _reconcile_orphan_sessions
    from module_payload.store.session_store import dumps_session

    host = "lab"
    session_key = f"payload:collector:{host}:session:can:3:0:0"
    deleted = _install_orphan_redis(monkeypatch, session_key, dumps_session({}))

    class Manager:
        def list_opened(self):
            return []

    _reconcile_orphan_sessions(Manager(), host)
    assert rk.status_key("can:3:0:0") in deleted
    assert rk.heartbeat_key("can:3:0:0") in deleted


def test_reconcile_orphan_sessions_keeps_alive_src(monkeypatch) -> None:
    from module_payload.collectors.supervisor import _reconcile_orphan_sessions
    from module_payload.store.session_store import dumps_session

    host = "lab"
    session_key = f"payload:collector:{host}:session:can:3:0:0"
    deleted = _install_orphan_redis(
        monkeypatch,
        session_key,
        dumps_session({"srcParam": "can:3:0:0"}),
    )

    class Manager:
        def list_opened(self):
            return [{"type": "can", "alive": True, "deviceId": "can:3:0", "channels": [0]}]

    _reconcile_orphan_sessions(Manager(), host)
    assert deleted == []


def test_reconcile_orphan_sessions_warns_on_delete_fail(monkeypatch) -> None:
    from module_payload.collectors.supervisor import _reconcile_orphan_sessions
    from module_payload.store.session_store import dumps_session

    host = "lab"
    warnings: list[str] = []
    _install_orphan_redis(
        monkeypatch,
        f"payload:collector:{host}:session:serial:COM9",
        dumps_session({"srcParam": "serial:COM9"}),
        fail_delete=True,
    )

    class Manager:
        def list_opened(self):
            return []

    monkeypatch.setattr(
        "module_payload.collectors.supervisor.logger.warning",
        lambda msg, *a, **k: warnings.append(str(msg)),
    )
    _reconcile_orphan_sessions(Manager(), host)
    assert any("orphan session delete failed" in w for w in warnings)
