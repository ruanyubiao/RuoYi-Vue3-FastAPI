"""采集监工：监听 Redis 命令，拉起或停止 runner.py 工作进程。"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collector_host import current_collector_host, normalize_collector_host
from module_payload.collectors.redis_sync import create_sync_redis, loads_json
from module_payload.collectors.snapshot_store import (
    delete_snapshot,
    enable_publish,
    hardware,
    publish_registry,
    set_hardware,
)
from module_payload.collectors.supervisor_client import write_result

_HW_INTERVAL_S = 15.0
_SNAP_INTERVAL_S = 5.0


def _scan_hardware() -> dict[str, Any]:
    """在采集机上扫描串口、CAN 厂商和本机地址。扫描失败时保留上一拍。"""
    from module_payload.collectors.hardware import (
        build_can_vendors,
        enumerate_serial_ports,
        pick_default_can_vendor,
        scan_local_addresses,
    )
    from module_payload.collectors.hw_probe import HW_PROBE_TIMEOUT_SEC, call_with_timeout

    prev = hardware()
    serial_ports = list(prev.get('serialPorts') or [])
    serial_ok = False
    try:
        ports = call_with_timeout(
            enumerate_serial_ports,
            timeout=HW_PROBE_TIMEOUT_SEC,
            label='supervisor_serial',
        )
        serial_ports = [{'port': p.device, 'description': getattr(p, 'description', '') or ''} for p in ports]
        serial_ok = True
    except Exception:
        pass
    vendors = list(prev.get('canVendors') or [])
    default_vendor = int(prev.get('defaultCanVendor') or 0)
    try:
        vendors = call_with_timeout(
            build_can_vendors,
            timeout=HW_PROBE_TIMEOUT_SEC,
            label='supervisor_can',
        )
        default_vendor = pick_default_can_vendor(vendors)
    except Exception:
        pass
    addrs = list(prev.get('localAddrs') or [])
    try:
        addrs = scan_local_addresses()
    except Exception:
        pass
    return {
        'serialPorts': serial_ports,
        'canVendors': vendors,
        'defaultCanVendor': default_vendor,
        'localAddrs': addrs,
        'serialScanOk': serial_ok,
    }


def _reconcile_serial(manager, hw: dict[str, Any]) -> None:
    """本机已经没有的已打开串口，由监工关掉。扫描失败时不动。"""
    if not hw.get('serialScanOk'):
        return
        from module_payload.collectors.redis_sync import create_sync_redis
        from module_payload.constants import SRC_KIND_SERIAL
        from module_payload.store.session_store import delete_session_sync

    present = {str(item.get('port') or '').strip().upper() for item in hw.get('serialPorts') or []}
    for entry in list(manager.list_opened()):
        if entry.get('type') != 'serial' or not entry.get('alive'):
            continue
        device_id = str(entry.get('deviceId') or '')
        port = device_id.split(':', 1)[1] if ':' in device_id else device_id
        if not port or port.strip().upper() in present:
            continue
        try:
            manager.stop(device_id)
        except Exception:
            continue
        redis = create_sync_redis()
        try:
            delete_session_sync(redis, device_id, SRC_KIND_SERIAL)
        except Exception:
            pass
        finally:
            redis.close()


def _dispatch(manager, op: str, body: dict[str, Any]) -> dict[str, Any]:
    """执行一条开关命令。成功返回 ok，失败带 error。"""
    try:
        if op == 'start_serial':
            port = str(body.get('port') or '')
            config = dict(body.get('config') or {})
            device_id, already = manager.start_serial(port, config)
            running: dict[str, Any] = {}
            for entry in manager.list_opened():
                if entry.get('deviceId') == device_id:
                    running = dict(entry.get('config') or {})
                    break
            return {'ok': True, 'deviceId': device_id, 'alreadyOpen': already, 'config': running}
        if op == 'stop':
            manager.stop(str(body.get('deviceId') or ''))
            return {'ok': True}
        if op == 'open_can':
            device_id, already = manager.open_can_channel(
                int(body['vendor']),
                int(body['devIndex']),
                int(body['canIndex']),
                dict(body.get('config') or {}),
            )
            return {'ok': True, 'deviceId': device_id, 'alreadyOpen': already}
        if op == 'close_can':
            manager.close_can_channel(int(body['vendor']), int(body['devIndex']), int(body['canIndex']))
            return {'ok': True, 'deviceId': body.get('deviceId') or ''}
        if op == 'start_net':
            device_id, already = manager.start_net(
                str(body.get('proto') or 'udp'),
                str(body.get('localHost') or '0.0.0.0'),
                int(body.get('localPort') or 0),
                dict(body.get('config') or {}),
            )
            if already:
                manager.apply_net_reuse_params(
                    device_id,
                    remote_host=str((body.get('config') or {}).get('remote_host') or ''),
                    remote_port=int((body.get('config') or {}).get('remote_port') or 0),
                )
            return {'ok': True, 'deviceId': device_id, 'alreadyOpen': already}
        if op == 'shutdown':
            manager.shutdown_all()
            return {'ok': True, 'shutdown': True}
        return {'ok': False, 'error': f'未知命令: {op}'}
    except Exception as exc:
        return {'ok': False, 'error': str(exc) or '采集命令失败'}


def _handle(redis, manager, host: str, raw: str) -> bool:
    """处理一条命令。返回 False 表示监工该退出。"""
    body = loads_json(raw) or {}
    if not isinstance(body, dict):
        return True
    req_id = str(body.get('reqId') or '')
    op = str(body.get('op') or '')
    result = _dispatch(manager, op, body)
    if req_id:
        try:
            write_result(redis, host, req_id, result)
        except Exception:
            pass
    return not result.get('shutdown')


def serve() -> None:
    """阻塞运行监工，直到收到 shutdown 或进程被打断。"""
    from module_payload.collectors.process_manager import CollectorProcessManager

    enable_publish()
    host = normalize_collector_host(os.environ.get('COLLECTOR_HOST') or current_collector_host())
    os.environ['COLLECTOR_HOST'] = host
    manager = CollectorProcessManager.instance()
    redis = create_sync_redis()
    last_hw = 0.0
    last_snap = 0.0
    try:
        while True:
            item = None
            try:
                item = redis.brpop(rk.collector_cmd_key(host), timeout=1)
            except Exception:
                time.sleep(0.2)
            if item:
                raw = item[1]
                if isinstance(raw, bytes):
                    raw = raw.decode()
                if not _handle(redis, manager, host, raw):
                    break
            now = time.time()
            if last_hw == 0.0 or now - last_hw >= _HW_INTERVAL_S:
                hw = _scan_hardware()
                set_hardware(hw)
                _reconcile_serial(manager, hw)
                publish_registry(manager)
                last_hw = now
                last_snap = now
            elif now - last_snap >= _SNAP_INTERVAL_S:
                publish_registry(manager)
                last_snap = now
    except KeyboardInterrupt:
        pass
    finally:
        try:
            manager.shutdown_all()
        except (Exception, KeyboardInterrupt):
            pass
        try:
            delete_snapshot(host)
        except (Exception, KeyboardInterrupt):
            pass
        try:
            redis.close()
        except (Exception, KeyboardInterrupt):
            pass


def main() -> None:
    """供脚本和 ``python -c`` 调用。"""
    serve()
