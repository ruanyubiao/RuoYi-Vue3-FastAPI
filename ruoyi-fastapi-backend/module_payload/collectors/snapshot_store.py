"""采集机快照：监工写入，网页按 host 读取。"""

from __future__ import annotations

import json
import threading
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collector_host import current_collector_host, normalize_collector_host

_publish_enabled = False
_hw_lock = threading.Lock()


def enable_publish() -> None:
    """只有监工进程打开。网页进程里的空进程表不能覆盖快照。"""
    global _publish_enabled
    _publish_enabled = True
_hw: dict[str, Any] = {
    'serialPorts': [],
    'canVendors': [],
    'defaultCanVendor': 0,
    'localAddrs': [],
    'serialScanOk': False,
}


def set_hardware(hw: dict[str, Any]) -> None:
    """监工扫描完成后更新内存里的硬件清单，下一拍快照会带上。"""
    global _hw
    with _hw_lock:
        _hw = {
            'serialPorts': list(hw.get('serialPorts') or []),
            'canVendors': list(hw.get('canVendors') or []),
            'defaultCanVendor': int(hw.get('defaultCanVendor') or 0),
            'localAddrs': list(hw.get('localAddrs') or []),
            'serialScanOk': bool(hw.get('serialScanOk')),
        }


def hardware() -> dict[str, Any]:
    """当前缓存的硬件清单副本。"""
    with _hw_lock:
        return {
            'serialPorts': list(_hw.get('serialPorts') or []),
            'canVendors': list(_hw.get('canVendors') or []),
            'defaultCanVendor': int(_hw.get('defaultCanVendor') or 0),
            'localAddrs': list(_hw.get('localAddrs') or []),
            'serialScanOk': bool(_hw.get('serialScanOk')),
        }


def build_document(host: str, opened: list[dict[str, Any]], hw: dict[str, Any] | None = None) -> dict[str, Any]:
    """把已打开进程表和硬件清单合成一页快照。"""
    spec = hw if hw is not None else hardware()
    return {
        'host': host,
        'serialPorts': list(spec.get('serialPorts') or []),
        'canVendors': list(spec.get('canVendors') or []),
        'defaultCanVendor': int(spec.get('defaultCanVendor') or 0),
        'localAddrs': list(spec.get('localAddrs') or []),
        'serialScanOk': bool(spec.get('serialScanOk')),
        'registry': opened,
    }


def publish_registry(manager) -> None:
    """用监工进程里的进程表重写快照。Redis 失败时忽略，避免挡住开闭。"""
    if not _publish_enabled:
        return
    try:
        from module_payload.collectors.redis_sync import create_sync_redis

        host = current_collector_host()
        opened = manager.list_opened()
        doc = build_document(host, opened)
        raw = json.dumps(doc, ensure_ascii=False)
        redis = create_sync_redis()
        try:
            redis.setex(rk.collector_snapshot_key(host), rk.SNAPSHOT_TTL_S, raw)
            redis.sadd(rk.collector_hosts_key(), host)
        finally:
            redis.close()
    except Exception:
        pass


def delete_snapshot(host: str | None = None) -> None:
    """正常退出时删掉快照，并从目录集合移除。"""
    try:
        from module_payload.collectors.redis_sync import create_sync_redis

        name = normalize_collector_host(host) if host else current_collector_host()
        redis = create_sync_redis()
        try:
            redis.delete(rk.collector_snapshot_key(name))
            redis.srem(rk.collector_hosts_key(), name)
        finally:
            redis.close()
    except Exception:
        pass


def _loads(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_snapshot(redis, host: str) -> dict[str, Any] | None:
    """读一台采集机的快照。没有或过期返回 None。"""
    name = normalize_collector_host(host)
    raw = redis.get(rk.collector_snapshot_key(name))
    return _loads(raw)


def list_machines(redis, hosts: list[str] | None = None) -> list[dict[str, Any]]:
    """不传 hosts 时返回目录里还在线的采集机。点名的 host 没有快照时 online 为 false。"""
    named = [normalize_collector_host(item) for item in (hosts or []) if str(item or '').strip()]
    if named:
        wanted = named
        drop_missing = False
    else:
        members = redis.smembers(rk.collector_hosts_key()) or set()
        wanted = []
        for item in members:
            text = item.decode() if isinstance(item, bytes) else str(item)
            if text:
                wanted.append(normalize_collector_host(text))
        drop_missing = True
    out: list[dict[str, Any]] = []
    stale: list[str] = []
    for host in wanted:
        doc = load_snapshot(redis, host)
        if doc is None:
            if drop_missing:
                stale.append(host)
                continue
            out.append({'host': host, 'online': False, 'serialPorts': [], 'canVendors': [], 'defaultCanVendor': 0, 'localAddrs': [], 'registry': []})
            continue
        doc['host'] = host
        doc['online'] = True
        out.append(doc)
    if stale:
        try:
            redis.srem(rk.collector_hosts_key(), *stale)
        except Exception:
            pass
    return out


def sync_snapshot(host: str | None = None) -> dict[str, Any] | None:
    """用同步客户端读当前采集机快照。"""
    from module_payload.collectors.redis_sync import create_sync_redis

    redis = create_sync_redis()
    try:
        name = current_collector_host() if host is None else normalize_collector_host(host)
        return load_snapshot(redis, name)
    finally:
        redis.close()


def visible_opened() -> list[dict[str, Any]]:
    """本进程进程表非空时用它（监工、单测桩）；否则读快照（网页进程）。"""
    try:
        from module_payload.collectors.process_manager import CollectorProcessManager

        local = CollectorProcessManager.instance().list_opened()
    except Exception:
        local = []
    if local:
        return list(local)
    return sync_registry()


def sync_registry(host: str | None = None) -> list[dict[str, Any]]:
    """当前采集机已打开进程表。离线时为空列表。"""
    doc = sync_snapshot(host)
    if not doc:
        return []
    rows = doc.get('registry') or []
    return [row for row in rows if isinstance(row, dict)]


def registry_of(redis, host: str | None = None) -> list[dict[str, Any]]:
    """当前采集机快照里的已打开进程表。离线时为空。"""
    name = current_collector_host() if host is None else normalize_collector_host(host)
    doc = load_snapshot(redis, name)
    if not doc:
        return []
    rows = doc.get('registry') or []
    return [row for row in rows if isinstance(row, dict)]
