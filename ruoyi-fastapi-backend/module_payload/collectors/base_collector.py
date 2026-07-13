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
from module_payload.redis_store import CURVE_MAX_POINTS

HISTORY_MAX = 100
HEARTBEAT_TTL = 15
CMD_RESULT_TTL = 120


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

    def _push_history(self, cmd: dict[str, Any], result: dict[str, Any]) -> None:
        entry = {
            'ts': result.get('ts'),
            'name': cmd.get('name') or cmd.get('order_id') or '',
            'hex': cmd.get('hex', ''),
            'success': result.get('success', True),
            'message': result.get('message', 'OK'),
        }
        key = rk.history_key(self.device_id)
        self._redis.lpush(key, dumps_json(entry))
        self._redis.ltrim(key, 0, HISTORY_MAX - 1)

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

    def _write_telemetry(self, channel_device_id: str, table_type: str, fields: list[dict[str, Any]], name: str = '') -> None:
        tkey = table_type.upper()
        now = datetime.now()
        ts = now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        payload = {
            'type': tkey,
            'name': name,
            'ts': ts,
            'dataId': int(now.timestamp() * 1000),
            'fields': fields,
        }
        self._redis.set(rk.telemetry_key(channel_device_id, tkey), dumps_json(payload))
        self._redis.set(rk.telemetry_ts_key(channel_device_id, tkey), ts)
        self._append_curve(channel_device_id, tkey, fields, ts)
        self._rx_count += 1

    def _append_curve(self, channel_device_id: str, table_type: str, fields: list[dict[str, Any]], ts_str: str) -> None:
        """把本帧每个可数值化字段都写入曲线 ZSet（与前端是否订阅无关）。"""
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
            ckey = rk.curve_key(channel_device_id, table_type, fid)
            # ZSet member 需要唯一；member=ts|val，score=ts
            pipe.zadd(ckey, {f'{ts_ms}|{val}': ts_ms})
            pipe.zremrangebyrank(ckey, 0, -(CURVE_MAX_POINTS + 1))
        if fields:
            pipe.execute()