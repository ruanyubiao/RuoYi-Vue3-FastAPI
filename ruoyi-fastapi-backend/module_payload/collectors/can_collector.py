"""
CAN 采集进程：一张卡一个进程，多通道；gpcan 收发 + TeleMetryParser 就地解析。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from module_payload import redis_keys as rk
from module_payload.cfg.payload_config_loader import TELE_METRY_CFG_FILE
from module_payload.collectors.base_collector import BaseCollector
from module_payload.collectors.redis_sync import dumps_json, loads_json

# DEMO 模式样例遥测帧（TeleMetryCmd.py）
_DEMO_FRAMES = {
    'FF': '00 BF 3A FF 33 00 00 00 00 00 00 00 00 00 45 00 DC 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 09 08 00 00 00 00 00 00 00 00 00 00 6E 4C 71 A2',
    'FD': '00 C4 3A FD AA 00 00 00 00 00 00 00 00 00 00 00 00 00 00 10 0B 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 FF FE 7F FE',
    'FB': '00 7B 3A FB 01 00 00 00 91 03 AF FC 14 F5 A1 FE 93 D5 92 01 A9 3F 1B FF DA 28 48 FF DF 7D 81 FF AB 2B C9',
}


class CanCollector(BaseCollector):
    def __init__(self, device_id: str, config: dict[str, Any]) -> None:
        super().__init__(device_id, config)
        self._tm_mgr = None
        self._channels: dict[int, dict[str, Any]] = {}
        self._demo_idx = 0
        self._last_demo_ts = 0.0

    def setup(self) -> bool:
        """先开 CAN 硬件并上报通道 status，再加载遥测配置（避免配置初始化拖过打开等待）。"""
        channels = self.config.get('channels') or []
        if not channels and self.config.get('can_index') is not None:
            channels = [self.config]
        last_error = ''
        for ch in channels:
            can_index = int(ch['can_index'])
            vendor = int(ch.get('vendor', self.config.get('vendor', 0)))
            dev_index = int(ch.get('dev_index', self.config.get('dev_index', 0)))
            channel_device_id = rk.can_channel_id(vendor, dev_index, can_index)
            self._redis.set(
                rk.status_key(channel_device_id),
                dumps_json(
                    {
                        'deviceId': channel_device_id,
                        'state': 'opening',
                        'connected': False,
                        'message': '正在打开 CAN 通道…',
                    }
                ),
            )
            ok, err = self._open_channel_client(can_index, ch)
            if not ok:
                last_error = err
        if not self._channels:
            self._write_status('error', last_error or 'CAN 通道打开失败，请检查设备是否接入')
            return False

        from TeleMetryParser import TeleMetryCfgManager

        self._tm_mgr = TeleMetryCfgManager.instance()
        if not self._tm_mgr.init(str(TELE_METRY_CFG_FILE)):
            self._tm_mgr = None
            # 硬件已打开：保持通道 running，仅告警；解析会失败直到配置可用
            self._write_status('running', 'CAN 已连接，但遥测配置初始化失败')
        return True

    def _open_channel_client(self, can_index: int, ch_cfg: dict[str, Any]) -> tuple[bool, str]:
        if can_index in self._channels:
            return True, ''
        from gpcan import AssembleType, CanCardParam, CanClient, CanMsgParam, CanRetCode, CanSendParam, create_assemble

        vendor = int(ch_cfg.get('vendor', self.config.get('vendor', 0)))
        dev_index = int(ch_cfg.get('dev_index', self.config.get('dev_index', 0)))
        channel_device_id = rk.can_channel_id(vendor, dev_index, can_index)
        try:
            client = CanClient(
                vendor,
                CanCardParam(
                    n_can_index=can_index,
                    n_baud_rate=int(ch_cfg.get('baud_rate', 500)),
                    n_dev_type=int(ch_cfg.get('dev_type', -1)),
                    n_dev_index=dev_index,
                    n_can_timeout_read_ms=int(ch_cfg.get('read_timeout_ms', 10)),
                    n_can_send_sleep_ms=int(ch_cfg.get('send_sleep_ms', -1)),
                ),
                CanMsgParam(
                    n_can_node_type=int(ch_cfg.get('node_type', 0)),
                    n_node_addr_to=int(ch_cfg.get('node_addr_to', 0x0D)),
                    n_cable_flag=int(ch_cfg.get('cable_flag', 0)),
                ),
                CanSendParam(),
                create_assemble(AssembleType.COMPLEX),
            )
            if client.init_can() != int(CanRetCode.CAN_RET_CODE_OK):
                err = f'CAN{can_index} 初始化失败，请检查 USB-CAN 设备是否接入'
                self._redis.set(
                    rk.status_key(channel_device_id),
                    dumps_json({'deviceId': channel_device_id, 'state': 'error', 'connected': False, 'message': err}),
                )
                return False, err
            if client.open_can() != int(CanRetCode.CAN_RET_CODE_OK):
                try:
                    client.deinit_can()
                except Exception:
                    pass
                err = f'CAN{can_index} 打开失败，请检查设备占用或驱动'
                self._redis.set(
                    rk.status_key(channel_device_id),
                    dumps_json({'deviceId': channel_device_id, 'state': 'error', 'connected': False, 'message': err}),
                )
                return False, err
        except Exception as e:
            err = f'CAN{can_index} 打开异常: {e}'
            self._redis.set(
                rk.status_key(channel_device_id),
                dumps_json({'deviceId': channel_device_id, 'state': 'error', 'connected': False, 'message': err}),
            )
            return False, err
        self._channels[can_index] = {
            'client': client,
            'cfg': ch_cfg,
            'channel_device_id': channel_device_id,
        }
        self._redis.set(
            rk.status_key(channel_device_id),
            dumps_json({'deviceId': channel_device_id, 'state': 'running', 'connected': True, 'message': '已连接'}),
        )
        return True, ''

    def handle_control(self, msg: dict[str, Any]) -> None:
        op = msg.get('op')
        can_index = int(msg.get('can_index', 0))
        if op == 'open_channel':
            self._open_channel_client(can_index, msg.get('config') or {})
        elif op == 'close_channel':
            self._close_channel(can_index)

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
        self._redis.delete(rk.status_key(ch['channel_device_id']))

    def read_and_parse(self) -> None:
        vendor = int(self.config.get('vendor', 0))
        if vendor == 0:
            self._inject_demo_telemetry()
        for can_index, ch in self._channels.items():
            client = ch['client']
            channel_device_id = ch['channel_device_id']
            for obj in client.recv_msg(64):
                data = bytes(obj.str_data) if obj.str_data else b''
                if len(data) < 4:
                    continue
                self._parse_and_store(channel_device_id, data)

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
        self._parse_and_store(channel_device_id, frame)

    def _parse_and_store(self, channel_device_id: str, data: bytes) -> None:
        if len(data) < 5:
            return
        from module_payload.constants import PARSER_TM_CAN_YC
        from module_payload.service.payload_session_service import PayloadSessionService

        parser_id = PayloadSessionService.get_parser_id_sync(self._redis, channel_device_id, 'can')
        if not parser_id:
            # 未绑定解释器：不解析、不写业务 Redis / 归档
            return
        if parser_id != PARSER_TM_CAN_YC:
            return
        if not self._tm_mgr:
            return
        table_key = f'{data[3]:02X}'
        payload_hex = ' '.join(f'{b:02X}' for b in data[4:])
        lines = self._tm_mgr.parse_hex(table_key, payload_hex, include_datetime=False)
        if not lines:
            return
        cfg = self._tm_mgr.get_table_cfg_by_key(table_key)
        fields = []
        for ln in lines:
            num = getattr(ln, 'val', None)
            raw = num.value() if num is not None and hasattr(num, 'value') else None
            fields.append(
                {
                    'id': getattr(ln, 'id', ''),
                    'name': getattr(ln, 'name', ''),
                    'value': raw,
                    'show': getattr(ln, 'show', ''),
                    'hex': getattr(ln, 'hex', ''),
                    'unit': getattr(ln, 'unit', ''),
                }
            )
        self._write_telemetry(
            channel_device_id,
            table_key,
            fields,
            cfg.name if cfg else table_key,
            raw_hex=' '.join(f'{b:02X}' for b in data),
            source='can',
        )

    def execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        from gpcan import CanMsgReq, CanRetCode

        can_index = int(command.get('can_index', self.config.get('can_index', 0)))
        ch = self._channels.get(can_index)
        if not ch:
            raise RuntimeError(f'CAN 通道 {can_index} 未打开')
        client = ch['client']
        hex_text = command.get('hex', '')
        broadcast = bool(command.get('broadcast') or command.get('all_channel'))
        if command.get('use_business', False):
            raw = bytes.fromhex(hex_text.replace(' ', ''))
            ret = client.send_msg(CanMsgReq(raw, is_broadcast=broadcast))
        else:
            # 原始发送：直接下发 un_id + data（不走业务组包/分帧）
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

        from module_payload.collectors.base_collector import CMD_RESULT_TTL

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
