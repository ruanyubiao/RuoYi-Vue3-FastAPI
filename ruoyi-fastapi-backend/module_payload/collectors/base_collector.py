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
from module_payload.constants import (
    CMD_RESULT_TTL,
    HEARTBEAT_TTL,
    HISTORY_MAX,
    IO_LOG_MAX,
)


class BaseCollector:
    """采集进程基类。"""

    def __init__(self, device_id: str, config: dict[str, Any]) -> None:
        self.device_id = device_id
        self.config = config
        self._running = False
        self._redis = create_sync_redis()
        self._rx_count = 0
        self._tx_count = 0
        self._assembler = None
        self._assembler_id: str | None = None

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

    def _try_session_ingest(self, data: bytes, src_param: str, src_kind: str) -> None:
        """组装器还原完整载荷 → 写 assembled Redis；若已绑定解释器再解析写遥测。"""
        if not data:
            return
        try:
            from module_payload.assemblers import create_assembler, normalize_assembler_id
            from module_payload.parsers import resolve_parser
            from module_payload.service.payload_error_store import push_pipeline_error
            from module_payload.service.payload_session_service import PayloadSessionService

            session = PayloadSessionService.get_session_sync(self._redis, src_param, src_kind) or {}
            assembler_id = normalize_assembler_id(session.get('assemblerId'))
            if getattr(self, '_assembler_id', None) != assembler_id or getattr(self, '_assembler', None) is None:
                self._assembler = create_assembler(assembler_id)
                self._assembler_id = assembler_id

            payloads = self._assembler.feed(data)
            take_errors = getattr(self._assembler, 'take_errors', None)
            if callable(take_errors):
                for err in take_errors():
                    push_pipeline_error(
                        self._redis,
                        stage='assembler',
                        message=err,
                        device_id=src_param,
                        assembler_id=assembler_id,
                    )
            if not payloads:
                return

            parser_id = (session.get('parserId') or '').strip()
            ingest = None
            if parser_id:
                ingest = resolve_parser(parser_id)
                if ingest is None or not hasattr(ingest, 'ingest_bytes_sync'):
                    push_pipeline_error(
                        self._redis,
                        stage='parser',
                        message=f'未注册或不可用的解释器: {parser_id}',
                        device_id=src_param,
                        assembler_id=assembler_id,
                        parser_id=parser_id,
                    )
                    ingest = None

            for item in payloads:
                if not item.data:
                    continue
                self._store_assembled(src_param, assembler_id, item)
                if ingest is None:
                    continue
                ingest.ingest_bytes_sync(
                    self._redis,
                    item.data,
                    src_param=src_param,
                    src_kind=src_kind,
                    parser_id=parser_id,
                    quiet=True,
                )
        except Exception as e:
            try:
                from module_payload.service.payload_error_store import push_pipeline_error

                push_pipeline_error(
                    self._redis,
                    stage='session',
                    message=f'会话入库异常: {e}',
                    device_id=src_param,
                    data_len=len(data),
                )
            except Exception:
                pass

    def _store_assembled(self, device_id: str, assembler_id: str, item: Any) -> None:
        """组装完成写入 Redis：payload:{deviceId}:assembled:latest"""
        try:
            from datetime import datetime

            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            meta = dict(item.meta or {})
            meta.setdefault('assemblerId', assembler_id)
            entry = {
                'deviceId': device_id,
                'assemblerId': assembler_id,
                'ts': ts,
                'len': len(item.data),
                'hex': ' '.join(f'{b:02X}' for b in item.data),
                'meta': meta,
            }
            dumped = dumps_json(entry)
            self._redis.set(rk.assembled_latest_key(device_id), dumped)
            key = rk.assembled_log_key(device_id)
            self._redis.lpush(key, dumped)
            self._redis.ltrim(key, 0, 49)
        except Exception:
            pass

    def run(self) -> None:
        try:
            ready = self.setup()
        except KeyboardInterrupt:
            return
        except Exception as e:
            self._write_status('error', f'设备初始化异常: {e}')
            return
        if not ready:
            # setup 失败时应已写入具体 error，勿覆盖
            return
        self._running = True
        self._write_status('running', '采集中')
        try:
            while self._running:
                try:
                    self._consume_control()
                    if not self._running:
                        break
                    self._consume_commands()
                    self.read_and_parse()
                    self._heartbeat()
                except KeyboardInterrupt:
                    # Ctrl+C 可能传到子进程；安静退出，勿刷 Redis 堆栈
                    self._running = False
                    break
                except Exception:
                    # 单轮异常不得退出采集进程，否则前端会轮询成「已断开」
                    time.sleep(0.05)
                time.sleep(float(self.config.get('loop_interval_s', 0.01)))
        except KeyboardInterrupt:
            self._running = False
        finally:
            try:
                self.teardown()
            except Exception:
                pass
            try:
                self._write_status('stopped', '已停止')
            except Exception:
                pass

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

    def _push_io(
        self,
        direction: str,
        data: bytes,
        peer: str = '',
        device_id: str | None = None,
        display_hex: bool | None = None,
        frame_id: int | None = None,
    ) -> None:
        """原始收发日志，供控制页接收区轮询。

        CAN 可将 frame_id 与 data 分开存储，避免 ID 与载荷粘在一起。
        """
        if not data and frame_id is None:
            return
        did = device_id or self.device_id
        try:
            seq = int(self._redis.incr(rk.io_log_seq_key(did)))
            payload = data or b''
            entry = {
                'seq': seq,
                'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
                'dir': 'send' if str(direction).lower() == 'send' else 'recv',
                'hex': ' '.join(f'{b:02X}' for b in payload),
                'len': len(payload),
                'peer': peer or '',
            }
            if frame_id is not None:
                fid = int(frame_id) & 0x1FFFFFFF
                # 8 位十六进制，显示时按字节空格分隔：00 00 02 34
                entry['frameIdHex'] = ' '.join(f'{b:02X}' for b in fid.to_bytes(4, 'big'))
            # SEND：按发送时是否 HEX 决定前端展示；RECV：由前端按当时勾选冻结
            if display_hex is not None:
                entry['displayHex'] = bool(display_hex)
            key = rk.io_log_key(did)
            self._redis.lpush(key, dumps_json(entry))
            self._redis.ltrim(key, 0, IO_LOG_MAX - 1)
        except Exception:
            pass

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
            raw_hex = (cmd.get('hex') or '').replace(' ', '')
            frame_id = cmd.get('frame_id')
            if (raw_hex or frame_id is not None) and result.get('success', True):
                display_hex = cmd.get('display_hex')
                if display_hex is None:
                    display_hex = True
                peer = str(result.get('peer') or '')
                payload = bytes.fromhex(raw_hex) if raw_hex else b''
                self._push_io(
                    'send',
                    payload,
                    peer=peer,
                    device_id=src_param,
                    display_hex=bool(display_hex),
                    frame_id=int(frame_id) if frame_id is not None else None,
                )
        except Exception:
            pass
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
        import os

        key = rk.status_key(self.device_id)
        # 旧进程收尾写 stopped 时，若 key 已被新进程占用则勿覆盖
        if state == 'stopped':
            try:
                raw = self._redis.get(key)
                if raw:
                    cur = loads_json(raw) or {}
                    owner = cur.get('pid')
                    if owner is not None and int(owner) != os.getpid():
                        return
                self._redis.delete(key)
            except Exception:
                pass
            return
        payload = {
            'deviceId': self.device_id,
            'state': state,
            'message': message,
            'connected': state == 'running',
            'stats': {'rx': self._rx_count, 'tx': self._tx_count},
            'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'pid': os.getpid(),
        }
        self._redis.set(key, dumps_json(payload))

    def _write_channel_status(
        self, channel_device_id: str, state: str, message: str = '', connected: bool | None = None
    ) -> None:
        """写 CAN 通道 status（带 pid，避免旧进程收尾踩踏新进程）。"""
        import os

        key = rk.status_key(channel_device_id)
        if state in ('stopped', 'closed'):
            try:
                raw = self._redis.get(key)
                if raw:
                    cur = loads_json(raw) or {}
                    owner = cur.get('pid')
                    if owner is not None and int(owner) != os.getpid():
                        return
                self._redis.delete(key)
            except Exception:
                pass
            return
        payload = {
            'deviceId': channel_device_id,
            'state': state,
            'message': message,
            'connected': bool(connected) if connected is not None else (state == 'running'),
            'stats': {'rx': self._rx_count, 'tx': self._tx_count},
            'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'pid': os.getpid(),
        }
        self._redis.set(key, dumps_json(payload))

    # 遥测热写统一走 parsers.TmCanYcIngest（_try_session_ingest）；勿在采集侧再写一套 latest/curve/archive。
