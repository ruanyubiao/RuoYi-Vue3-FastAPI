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


def test_invoke_times_out_when_supervisor_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        'module_payload.collectors.supervisor_client.create_sync_redis',
        lambda: _CmdRedis(),
    )
    with pytest.raises(RuntimeError, match=OFFLINE_MESSAGE):
        invoke('stop', {'deviceId': 'serial:COM1'}, timeout_s=0.15)
