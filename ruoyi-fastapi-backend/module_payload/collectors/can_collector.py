"""
CAN 采集进程：一张卡一个进程，多通道；gpcan CanProtocolClient 收发。

组帧走会话组装器（CAN-BIU / CAN-XL）；业务发送走 client.builder + send_msg。
"""

from __future__ import annotations

import time
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collectors.base_collector import BaseCollector
from module_payload.collectors.redis_sync import dumps_json, loads_json
from module_payload.constants import (
    ASSEMBLER_CAN_BIU,
    ASSEMBLER_CAN_XL,
    ASSEMBLER_PASSTHROUGH,
    SRC_KIND_CAN,
)

# DEMO 模式样例遥测帧（TeleMetryCmd.py）
_DEMO_FRAMES = {
    'FF': '00 BF 3A FF 33 00 00 00 00 00 00 00 00 00 45 00 DC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 09 08 00 00 00 00 00 00 00 00 00 00 6E 4C 71 A2',
    'FD': '00 C4 3A FD AA 00 00 00 00 00 00 00 00 00 00 00 00 00 00 10 0B 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 FF FE 7F FE',
    'FB': '00 7B 3A FB 01 00 00 00 91 03 AF FC 14 F5 A1 FE 93 D5 92 01 A9 3F 1B FF DA 28 48 FF DF 7D 81 FF AB 2B C9',
}


def _assembler_to_protocol(assembler_id: str | None):
    from gpcan import CanProtocolType

    aid = (assembler_id or '').strip()
    if aid == ASSEMBLER_CAN_XL:
        return CanProtocolType.XL
    if aid == ASSEMBLER_CAN_BIU:
        return CanProtocolType.BIU
    # 透传及其它：协议 NONE，便于裸 CAN 测试
    return CanProtocolType.NONE


class CanCollector(BaseCollector):
    def __init__(self, device_id: str, config: dict[str, Any]) -> None:
        super().__init__(device_id, config)
        self._channels: dict[int, dict[str, Any]] = {}
        self._demo_idx = 0
        self._last_demo_ts = 0.0

    def setup(self) -> bool:
        """打开 CAN 硬件并上报通道 status。"""
        channels = self.config.get('channels') or []
        if not channels and self.config.get('can_index') is not None:
            channels = [self.config]
        last_error = ''
        for ch in channels:
            can_index = int(ch['can_index'])
            vendor = int(ch.get('vendor', self.config.get('vendor', 0)))
            dev_index = int(ch.get('dev_index', self.config.get('dev_index', 0)))
            channel_device_id = rk.can_channel_id(vendor, dev_index, can_index)
            self._write_channel_status(channel_device_id, 'opening', '正在打开 CAN 通道…', connected=False)
            ok, err = self._open_channel_client(can_index, ch)
            if not ok:
                last_error = err
        if not self._channels:
            self._write_status('error', last_error or 'CAN 通道打开失败，请检查设备是否接入')
            return False
        return True

    def _open_channel_client(self, can_index: int, ch_cfg: dict[str, Any]) -> tuple[bool, str]:
        if can_index in self._channels:
            ch = self._channels[can_index]
            self._write_channel_status(ch['channel_device_id'], 'running', '已连接', connected=True)
            return True, ''
        from gpcan import (
            CanCableParam,
            CanCardParam,
            CanProtocolClient,
            CanProtocolParam,
            CanRetCode,
            CanSendParam,
        )

        vendor = int(ch_cfg.get('vendor', self.config.get('vendor', 0)))
        dev_index = int(ch_cfg.get('dev_index', self.config.get('dev_index', 0)))
        channel_device_id = rk.can_channel_id(vendor, dev_index, can_index)
        proto = _assembler_to_protocol(ch_cfg.get('assembler_id') or ASSEMBLER_CAN_BIU)
        # 首页不指定线缆 → cable_param=None；遥控 A/B 传入 0/1
        raw_cable = ch_cfg.get('cable_flag', None)
        cable_param = None
        if raw_cable is not None:
            cable_param = CanCableParam(
                n_node_addr_to=int(ch_cfg.get('node_addr_to', 0x0D)),
                n_cable_flag=int(raw_cable),
            )
        try:
            client = CanProtocolClient(
                vendor,
                CanCardParam(
                    n_can_index=can_index,
                    n_baud_rate=int(ch_cfg.get('baud_rate', 500)),
                    n_dev_type=int(ch_cfg.get('dev_type', -1)),
                    n_dev_index=dev_index,
                    n_can_timeout_read_ms=int(ch_cfg.get('read_timeout_ms', 10)),
                    n_can_send_sleep_ms=int(ch_cfg.get('send_sleep_ms', -1)),
                ),
                cable_param,
                CanProtocolParam(type=int(proto)),
                CanSendParam(),
            )
            if client.init_can() != int(CanRetCode.CAN_RET_CODE_OK):
                err = f'CAN{can_index} 初始化失败，请检查 USB-CAN 设备是否接入'
                self._write_channel_status(channel_device_id, 'error', err, connected=False)
                return False, err
            if client.open_can() != int(CanRetCode.CAN_RET_CODE_OK):
                try:
                    client.deinit_can()
                except Exception:
                    pass
                err = f'CAN{can_index} 打开失败，请检查设备占用或驱动'
                self._write_channel_status(channel_device_id, 'error', err, connected=False)
                return False, err
        except Exception as e:
            err = f'CAN{can_index} 打开异常: {e}'
            self._write_channel_status(channel_device_id, 'error', err, connected=False)
            return False, err
        self._channels[can_index] = {
            'client': client,
            'cfg': ch_cfg,
            'channel_device_id': channel_device_id,
        }
        self._write_channel_status(channel_device_id, 'running', '已连接', connected=True)
        return True, ''

    def handle_control(self, msg: dict[str, Any]) -> None:
        op = msg.get('op')
        can_index = int(msg.get('can_index', 0))
        if op == 'open_channel':
            self._open_channel_client(can_index, msg.get('config') or {})
        elif op == 'close_channel':
            self._close_channel(can_index)
        elif op == 'set_cable':
            self._set_channel_cable(can_index, msg)

    def _set_channel_cable(self, can_index: int, msg: dict[str, Any]) -> None:
        ch = self._channels.get(can_index)
        if not ch:
            return
        from gpcan import CanCableParam

        client = ch['client']
        cur = client.get_cable_param()
        node = msg.get('node_addr_to')
        cable = msg.get('cable_flag')
        client.set_cable_param(
            CanCableParam(
                n_node_addr_to=int(node) if node is not None else int(cur.n_node_addr_to),
                n_cable_flag=int(cable) if cable is not None else int(cur.n_cable_flag),
            )
        )
        cfg = ch.get('cfg') or {}
        if node is not None:
            cfg['node_addr_to'] = int(node)
        if cable is not None:
            cfg['cable_flag'] = int(cable)
        ch['cfg'] = cfg

    def _close_channel(self, can_index: int) -> None:
        ch = self._channels.pop(can_index, None)
        if not ch:
            return
        client = ch['client']
        try:
            client.close_can()
            client.deinit_can()
        except Exception:
            pass
        self._write_channel_status(ch['channel_device_id'], 'closed', '已关闭', connected=False)

    def _sync_client_protocol(self, ch: dict[str, Any]) -> str:
        """按会话组装器同步 CanProtocolClient 协议类型（影响业务发送组包）。"""
        from gpcan import CanProtocolParam
        from module_payload.assemblers import normalize_assembler_id
        from module_payload.service.payload_session_service import PayloadSessionService

        channel_device_id = ch['channel_device_id']
        session = PayloadSessionService.get_session_sync(self._redis, channel_device_id, SRC_KIND_CAN) or {}
        assembler_id = normalize_assembler_id(session.get('assemblerId') or ASSEMBLER_CAN_BIU)
        if assembler_id not in (ASSEMBLER_CAN_BIU, ASSEMBLER_CAN_XL, ASSEMBLER_PASSTHROUGH):
            assembler_id = ASSEMBLER_CAN_BIU
        proto = _assembler_to_protocol(assembler_id)
        client = ch['client']
        if client.get_protocol() != proto:
            client.set_protocol_param(CanProtocolParam(type=int(proto)))
        return assembler_id

    def read_and_parse(self) -> None:
        vendor = int(self.config.get('vendor', 0))
        if vendor == 0:
            self._inject_demo_telemetry()
        for can_index, ch in list(self._channels.items()):
            client = ch['client']
            channel_device_id = ch['channel_device_id']
            try:
                frames = client.recv(64)
            except Exception:
                continue
            if not frames:
                continue
            for obj in frames:
                try:
                    data = bytes(obj.str_data) if obj.str_data else b''
                    un_id = int(getattr(obj, 'un_id', 0) or 0) & 0x1FFFFFFF
                    self._push_io('recv', data, device_id=channel_device_id, frame_id=un_id)
                    self._rx_count += 1
                except Exception:
                    continue
            try:
                self._ingest_can_frames(channel_device_id, frames)
            except Exception:
                continue

    def _heartbeat(self) -> None:
        super()._heartbeat()
        for ch in self._channels.values():
            cid = ch.get('channel_device_id')
            if not cid:
                continue
            try:
                self._write_channel_status(cid, 'running', '已连接', connected=True)
            except Exception:
                pass

    def _inject_demo_telemetry(self) -> None:
        now = time.time()
        if now - self._last_demo_ts < 1.0 or not self._channels:
            return
        self._last_demo_ts = now
        keys = list(_DEMO_FRAMES.keys())
        key = keys[self._demo_idx % len(keys)]
        self._demo_idx += 1
        frame = bytes.fromhex(_DEMO_FRAMES[key].replace(' ', ''))
        channel_device_id = next(iter(self._channels.values()))['channel_device_id']
        self._push_io('recv', frame, device_id=channel_device_id)
        self._rx_count += 1
        # demo 已是业务载荷，走 feed(bytes) 路径
        self._try_session_ingest(frame, channel_device_id, SRC_KIND_CAN)

    def _ingest_can_frames(self, channel_device_id: str, frames: list[Any]) -> None:
        """硬件 CAN 帧 → 会话组装器 feed_frames → 解释器。"""
        if not frames:
            return
        try:
            from module_payload.assemblers import create_assembler, normalize_assembler_id
            from module_payload.parsers import resolve_parser
            from module_payload.service.payload_error_store import push_pipeline_error
            from module_payload.service.payload_session_service import PayloadSessionService

            session = PayloadSessionService.get_session_sync(self._redis, channel_device_id, SRC_KIND_CAN) or {}
            assembler_id = normalize_assembler_id(session.get('assemblerId') or ASSEMBLER_CAN_BIU)
            if assembler_id not in (ASSEMBLER_CAN_BIU, ASSEMBLER_CAN_XL, ASSEMBLER_PASSTHROUGH):
                assembler_id = ASSEMBLER_CAN_BIU

            if getattr(self, '_assembler_id', None) != assembler_id or getattr(self, '_assembler', None) is None:
                self._assembler = create_assembler(assembler_id)
                self._assembler_id = assembler_id

            feed_frames = getattr(self._assembler, 'feed_frames', None)
            if callable(feed_frames):
                payloads = feed_frames(frames)
            else:
                # 透传：每帧 data 区视为一条完整载荷
                payloads = []
                for obj in frames:
                    data = bytes(obj.str_data) if getattr(obj, 'str_data', None) else b''
                    if data:
                        payloads.extend(self._assembler.feed(data))

            self._emit_assembler_errors(
                self._assembler,
                src_param=channel_device_id,
                assembler_id=assembler_id,
                push_pipeline_error=push_pipeline_error,
            )
            if not payloads:
                return
            parser_id = (session.get('parserId') or '').strip()
            self._dispatch_payloads(
                payloads,
                src_param=channel_device_id,
                src_kind=SRC_KIND_CAN,
                assembler_id=assembler_id,
                parser_id=parser_id,
                resolve_parser=resolve_parser,
                push_pipeline_error=push_pipeline_error,
            )
        except Exception as e:
            try:
                from module_payload.service.payload_error_store import push_pipeline_error

                push_pipeline_error(
                    self._redis,
                    stage='session',
                    message=f'CAN 组帧入库异常: {e}',
                    device_id=channel_device_id,
                )
            except Exception:
                pass

    def execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        from gpcan import CanRetCode

        can_index = int(command.get('can_index', self.config.get('can_index', 0)))
        ch = self._channels.get(can_index)
        if not ch:
            raise RuntimeError(f'CAN 通道 {can_index} 未打开')
        client = ch['client']
        hex_text = command.get('hex', '')
        broadcast = bool(command.get('broadcast') or command.get('all_channel'))
        if command.get('protocol_build'):
            self._sync_client_protocol(ch)
            pb = command.get('protocol_build') or {}
            method = (pb.get('method') or '').strip()
            kwargs = dict(pb.get('kwargs') or {})
            if isinstance(kwargs.get('data'), list):
                kwargs['data'] = bytes(int(x) & 0xFF for x in kwargs['data'])
            if not method or not hasattr(client.builder, method):
                return {'success': False, 'message': f'未知协议组包方法: {method}'}
            built = getattr(client.builder, method)(**kwargs)
            if built is None or not getattr(built, 'frames', None):
                return {'success': False, 'message': '协议组包失败（无帧）'}
            ret = client.send_msg(built)
        elif command.get('use_business', False):
            self._sync_client_protocol(ch)
            from gpcan import CanProtocolType

            if client.get_protocol() == CanProtocolType.NONE:
                return {
                    'success': False,
                    'message': '透传(协议 NONE) 不支持业务组包发送，请切换 CAN-BIU/CAN-XL 或使用原始帧发送',
                }
            raw = bytes.fromhex(hex_text.replace(' ', ''))
            if broadcast:
                built = client.builder.build_broadcast(raw)
            else:
                built = client.builder.build_telecommand(raw)
            if built is None or not getattr(built, 'frames', None):
                return {'success': False, 'message': '业务组包失败（无帧）'}
            ret = client.send_msg(built)
        else:
            frame_id = command.get('frame_id')
            if frame_id is None:
                return {'success': False, 'message': 'CAN_RAW 缺少 frame_id'}
            un_id = int(frame_id)
            data = bytes.fromhex(hex_text.replace(' ', '')) if hex_text else b''
            if len(data) > 8:
                return {'success': False, 'message': 'CAN_RAW 数据区最多8字节'}
            ret = client.send(un_id, data, un_data_len=len(data))
        if ret != int(CanRetCode.CAN_RET_CODE_OK):
            return {'success': False, 'message': 'CAN 发送失败'}
        return {'success': True, 'message': 'OK'}

    def _consume_commands(self) -> None:
        import uuid
        from datetime import datetime

        from module_payload.constants import CMD_RESULT_TTL

        for can_index, ch in self._channels.items():
            channel_device_id = ch['channel_device_id']
            key = rk.cmd_queue_key(channel_device_id)
            for _ in range(8):
                raw = self._redis.lpop(key)
                if not raw:
                    break
                cmd = loads_json(raw)
                if not cmd:
                    continue
                cmd['can_index'] = can_index
                cmd_id = cmd.get('cmd_id') or str(uuid.uuid4())
                try:
                    result = self.execute_command(cmd)
                    result.setdefault('success', True)
                except Exception as e:
                    result = {'success': False, 'message': str(e)}
                result['cmd_id'] = cmd_id
                result['ts'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                self._redis.setex(rk.cmd_result_key(channel_device_id, cmd_id), CMD_RESULT_TTL, dumps_json(result))
                if result.get('success'):
                    self._push_history(cmd, result, src_param=channel_device_id)
                self._tx_count += 1

    def teardown(self) -> None:
        for can_index in list(self._channels.keys()):
            self._close_channel(can_index)
