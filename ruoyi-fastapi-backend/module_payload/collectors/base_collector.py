"""
采集进程基类：Redis 通信、指令队列、心跳与状态上报。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collectors.redis_sync import create_sync_redis, dumps_json, loads_json

HISTORY_MAX = 100
HEARTBEAT_TTL = 15
CMD_RESULT_TTL = 120
CURVE_MAX_POINTS = 50000


class BaseCollector:
    """采集进程基类。"""

    def __init__(self, device_id: str, config: dict[str, Any]) -> None:
        self.device_id = device_id
        self.config = config
        self._running = False
        self._redis = create_sync_redis()
        self._rx_count = 0
        self._tx_count = 0

    def setup(self) -> bool:
        raise NotImplementedError

    def read_and_parse(self) -> None:
        raise NotImplementedError

    def execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def handle_control(self, msg: dict[str, Any]) -> None:
        """子类可覆盖：处理开/关通道等控制消息。"""

    def teardown(self) -> None:
        pass

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        if not self.setup():
            self._write_status('error', '设备初始化失败')
            return
        self._running = True
        self._write_status('running', '采集中')
        try:
            while self._running:
                self._consume_control()
                self._consume_commands()
                self.read_and_parse()
                self._heartbeat()
                time.sleep(float(self.config.get('loop_interval_s', 0.01)))
        finally:
            self.teardown()
            self._write_status('stopped', '已停止')

    def _consume_control(self) -> None:
        key = rk.ctrl_queue_key(self.device_id)
        for _ in range(8):
            raw = self._redis.lpop(key)
            if not raw:
                break
            msg = loads_json(raw)
            if not msg:
                continue
            if msg.get('op') == 'stop':
                self._running = False
                return
            self.handle_control(msg)

    def _consume_commands(self) -> None:
        key = rk.cmd_queue_key(self.device_id)
        for _ in range(16):
            raw = self._redis.lpop(key)
            if not raw:
                break
            cmd = loads_json(raw)
            if not cmd:
                continue
            cmd_id = cmd.get('cmd_id') or str(uuid.uuid4())
            try:
                result = self.execute_command(cmd)
                result.setdefault('success', True)
            except Exception as e:
                result = {'success': False, 'message': str(e)}
            result['cmd_id'] = cmd_id
            result['ts'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            self._redis.setex(rk.cmd_result_key(self.device_id, cmd_id), CMD_RESULT_TTL, dumps_json(result))
            if result.get('success'):
                self._push_history(cmd, result)
            self._tx_count += 1

    def _push_history(
        self, cmd: dict[str, Any], result: dict[str, Any], src_param: str | None = None
    ) -> None:
        """写 Redis 热发送历史，并投递 payload:tx:queue 供归档 worker 落 MySQL。"""
        from module_payload.constants import infer_src_kind

        src_param = src_param or self.device_id
        entry = {
            'ts': result.get('ts'),
            'name': cmd.get('name') or cmd.get('order_id') or '',
            'hex': cmd.get('hex', ''),
            'success': result.get('success', True),
            'message': result.get('message', 'OK'),
        }
        key = rk.history_key(src_param)
        self._redis.lpush(key, dumps_json(entry))
        self._redis.ltrim(key, 0, HISTORY_MAX - 1)
        try:
            ts_str = result.get('ts') or ''
            try:
                ts_ms = int(datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S.%f').timestamp() * 1000)
            except Exception:
                ts_ms = int(time.time() * 1000)
            tx_ev = {
                'ts_ms': ts_ms,
                'src_kind': infer_src_kind(src_param),
                'src_param': src_param,
                'cmd_name': cmd.get('name') or '',
                'order_id': cmd.get('order_id') or '',
                'raw_hex': cmd.get('hex', '') or '',
                'success': 1 if result.get('success', True) else 0,
                'message': result.get('message', 'OK'),
                'operator': cmd.get('operator') or '',
            }
            self._redis.lpush(rk.tx_queue_key(), dumps_json(tx_ev))
        except Exception:
            pass

    def _heartbeat(self) -> None:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        self._redis.setex(rk.heartbeat_key(self.device_id), HEARTBEAT_TTL, now)

    def _write_status(self, state: str, message: str = '') -> None:
        payload = {
            'deviceId': self.device_id,
            'state': state,
            'message': message,
            'connected': state == 'running',
            'stats': {'rx': self._rx_count, 'tx': self._tx_count},
            'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
        }
        self._redis.set(rk.status_key(self.device_id), dumps_json(payload))

    def _write_telemetry(
        self,
        channel_device_id: str,
        table_type: str,
        fields: list[dict[str, Any]],
        name: str = '',
        raw_hex: str = '',
        source: str = 'can',
    ) -> None:
        from module_payload.constants import DATA_KIND_TM, PARSER_TM_CAN_YC, infer_src_kind

        tkey = table_type.upper()
        now = datetime.now()
        ts = now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        ts_ms = int(now.timestamp() * 1000)
        src_param = channel_device_id
        src_kind = infer_src_kind(src_param, fallback=source)
        payload = {
            'type': tkey,
            'name': name,
            'ts': ts,
            'dataId': ts_ms,
            'fields': fields,
            'dataKind': DATA_KIND_TM,
            'dataSub': tkey,
            'srcKind': src_kind,
            'srcParam': src_param,
            'parserId': PARSER_TM_CAN_YC,
        }
        dumped = dumps_json(payload)
        self._redis.set(rk.telemetry_latest_key(tkey), dumped)
        self._redis.set(rk.telemetry_latest_ts_key(tkey), ts)
        self._append_curve(tkey, fields, ts)
        try:
            from module_payload.service.payload_telemetry_archive_service import (
                PayloadTelemetryArchiveService,
                build_archive_event,
            )

            event = build_archive_event(
                data_sub=tkey,
                ts_ms=ts_ms,
                raw_hex=raw_hex,
                fields=fields,
                name=name,
                src_kind=src_kind,
                src_param=src_param,
                parser_id=PARSER_TM_CAN_YC,
            )
            PayloadTelemetryArchiveService.enqueue_sync(self._redis, event)
        except Exception:
            pass
        self._rx_count += 1

    def _append_curve(self, table_type: str, fields: list[dict[str, Any]], ts_str: str) -> None:
        """把本帧每个可数值化字段都写入按子类型共享的曲线 ZSet。"""
        try:
            ts_ms = int(datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S.%f').timestamp() * 1000)
        except Exception:
            ts_ms = int(time.time() * 1000)
        pipe = self._redis.pipeline(transaction=False)
        for row in fields:
            fid = row.get('id')
            if not fid:
                continue
            try:
                val = float(row.get('value', row.get('show', 0)))
            except (TypeError, ValueError):
                continue
            member = {f'{ts_ms}|{val}': ts_ms}
            lkey = rk.curve_latest_key(table_type, fid)
            pipe.zadd(lkey, member)
            pipe.zremrangebyrank(lkey, 0, -(CURVE_MAX_POINTS + 1))
        if fields:
            pipe.execute()