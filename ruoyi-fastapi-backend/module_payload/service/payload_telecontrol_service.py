"""遥控指令下发与控制操作服务层。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from redis import asyncio as aioredis

from module_payload import redis_keys as rk
from module_payload.cfg.telecontrol_assembler import assemble_order, is_broadcast_hex
from module_payload.collectors.process_manager import CollectorProcessManager
from module_payload.entity.vo.payload_telecontrol_vo import ControlOpModel, TelecontrolAssembleModel, TelecontrolSendModel
from module_payload.redis_store import clear_history, get_history, push_command, wait_command_result
from module_payload.collectors.can_timers import parse_timer_op
from exceptions.exception import ServiceException


class PayloadTelecontrolService:
    """遥控下发：组帧后 LPUSH Redis 命令队列，等待采集进程回写结果。"""

    @staticmethod
    def _normalize_hex_tokens(text: str) -> list[int] | None:
        """按空白拆 HEX token；奇数位前补 0；非法返回 None。"""
        if not text or not str(text).strip():
            return []
        tokens = str(text).strip().split()
        out: list[int] = []
        for tok in tokens:
            if not tok:
                continue
            if not all(c in '0123456789abcdefABCDEF' for c in tok):
                return None
            if len(tok) % 2 == 1:
                tok = tok[:-1] + '0' + tok[-1]
            for i in range(0, len(tok), 2):
                out.append(int(tok[i : i + 2], 16))
        return out

    @classmethod
    async def send_can_raw(cls, redis: aioredis.Redis, device_id: str, frame_id_hex: str, data_hex: str) -> dict[str, Any]:
        """原始 CAN 帧入 Redis 命令队列并等执行结果（不走业务组帧）。"""
        fid = (frame_id_hex or '').strip().replace(' ', '')
        if len(fid) != 8 or any(c not in '0123456789abcdefABCDEF' for c in fid):
            raise ServiceException(message='帧ID(HEX)必须是连续8个十六进制字符(不能有空格)')

        data_bytes = cls._normalize_hex_tokens(data_hex)
        if data_bytes is None:
            raise ServiceException(message='数据(HEX)只能输入十六进制字符')
        if len(data_bytes) > 8:
            raise ServiceException(message='数据(HEX)最多8个字节')
        # 小于8字节：按实际大小发送（不补0）

        frame_id = int(fid, 16)
        data_hex_norm = ' '.join(f'{b:02X}' for b in data_bytes)
        cmd_id = str(uuid.uuid4())
        cmd = {
            'cmd_id': cmd_id,
            # 原始发送：避免把帧ID与数据拼成一段字节再解析，直接传 frame_id + data_hex
            'frame_id': frame_id,
            'hex': data_hex_norm,
            'order_id': None,
            'name': 'CAN_RAW',
            'broadcast': False,
            'all_channel': False,
            'use_business': False,
        }
        await push_command(redis, device_id, cmd)
        result = await wait_command_result(redis, device_id, cmd_id, timeout_s=12.0)
        if not result:
            return {'cmdId': cmd_id, 'success': False, 'message': '等待执行结果超时'}
        ok = bool(result.get('success', False))
        return {
            'cmdId': cmd_id,
            'success': ok,
            'message': '发送成功' if ok else (result.get('message') or '发送失败'),
        }

    @classmethod
    def get_order(cls, order_id: str, reload: bool = False, family: str | None = 'biu') -> dict[str, Any]:
        """按 family 取遥控配置中的指令定义。"""
        from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, cfg_id_for_family

        tc = TeleControlCfgManager.get(cfg_id_for_family(family), reload=reload)
        return tc.get_order(order_id)

    @classmethod
    def assemble(cls, body: TelecontrolAssembleModel) -> dict[str, Any]:
        """按 components 或 order_id 组 HEX；values 为控件原值（formula 计算前）。"""
        from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, cfg_id_for_family

        cfg_id = cfg_id_for_family(getattr(body, 'family', None) or 'biu')
        components = body.components or []
        # 显式 components 优先；否则按 order_id 查配置
        if components:
            return TeleControlCfgManager.assemble_order_dict(
                cfg_id,
                {'component': components},
                body.values,
            )
        if body.order_id:
            return TeleControlCfgManager.assemble(cfg_id, body.order_id, body.values)
        return assemble_order([], body.values or [])

    @classmethod
    async def send(cls, redis: aioredis.Redis, body: TelecontrolSendModel) -> dict[str, Any]:
        """组帧后入 Redis 命令队列，阻塞等待采集进程执行结果。"""
        from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, cfg_id_for_family

        hex_text = body.hex or ''
        broadcast = body.broadcast
        cfg_id = cfg_id_for_family(getattr(body, 'family', None) or 'biu')
        if body.order_id and body.components is not None:
            assembled = TeleControlCfgManager.assemble_order_dict(
                cfg_id,
                {'component': body.components},
                body.values or [],
            )
            hex_text = assembled['hex']
            broadcast = broadcast or assembled.get('allChannel', False)
        elif body.order_id and not hex_text:
            assembled = TeleControlCfgManager.assemble(cfg_id, body.order_id, body.values or [])
            hex_text = assembled['hex']
            broadcast = broadcast or assembled.get('allChannel', False)
        if not hex_text:
            raise ServiceException(message='指令 HEX 不能为空')
        if is_broadcast_hex(hex_text):
            broadcast = True
        cmd_id = str(uuid.uuid4())
        cmd = {
            'cmd_id': cmd_id,
            'hex': hex_text,
            'order_id': body.order_id,
            'name': body.name,
            'broadcast': broadcast,
            'all_channel': broadcast,
            'use_business': True,
        }
        if body.remote_host:
            cmd['remote_host'] = body.remote_host
        if body.remote_port:
            cmd['remote_port'] = body.remote_port
        if body.display_hex is not None:
            cmd['display_hex'] = bool(body.display_hex)
        await push_command(redis, body.device_id, cmd)
        result = await wait_command_result(redis, body.device_id, cmd_id, timeout_s=12.0)
        if not result:
            return {'cmdId': cmd_id, 'success': False, 'message': '等待执行结果超时'}
        ok = bool(result.get('success', False))
        return {
            'cmdId': cmd_id,
            'success': ok,
            'message': '发送成功' if ok else (result.get('message') or '发送失败'),
        }

    @classmethod
    async def get_send_history(cls, redis: aioredis.Redis, device_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """读该设备 Redis 发送历史 List。"""
        return await get_history(redis, device_id, limit)

    @classmethod
    async def clear_send_history(cls, redis: aioredis.Redis, device_id: str) -> None:
        """清空该设备 Redis 发送历史。"""
        await clear_history(redis, device_id)

    @classmethod
    async def control_op(cls, redis: aioredis.Redis, body: ControlOpModel) -> dict[str, Any]:
        """控制操作。op 统一为 ``{family}.{domain}.{action}``，如 ``biu.timedYc.enable``。"""
        op = (body.op or '').strip()
        device_id = body.device_id
        params = body.params or {}
        if not device_id:
            channels = CollectorProcessManager.instance().list_opened()
            for entry in channels:
                if entry['type'] == 'can' and entry.get('channels'):
                    parts = entry['deviceId'].split(':')
                    device_id = rk.can_channel_id(int(parts[1]), int(parts[2]), entry['channels'][0])
                    break
        if not device_id:
            raise ServiceException(message='请先打开 CAN 通道')

        timer = parse_timer_op(op, params)
        if timer:
            cmd_id = str(uuid.uuid4())
            cmd = {'cmd_id': cmd_id, 'name': op, 'timer': timer, 'use_business': False}
            await push_command(redis, device_id, cmd)
            result = await wait_command_result(redis, device_id, cmd_id, timeout_s=12.0)
            if not result:
                return {'cmdId': cmd_id, 'success': False, 'message': '等待执行结果超时'}
            ok = bool(result.get('success', False))
            out = {
                'cmdId': cmd_id,
                'success': ok,
                'message': result.get('message') or ('发送成功' if ok else '发送失败'),
            }
            if result.get('offsetMs') is not None:
                out['offsetMs'] = int(result.get('offsetMs'))
            elif timer.get('kind') in ('set_start', 'set_offset', 'reset_start', 'get_status'):
                out['offsetMs'] = 0
            if result.get('utc') is not None:
                out['utc'] = result.get('utc')
            for key in ('timedTm', 'broadcast', 'gnssValid', 'timedTmCan', 'timedTmDeviceId'):
                if key in result:
                    out[key] = result.get(key)
            return out

        # 协议构建类操作：下发到采集进程 builder（Demo 时间同步 / 系统指令等）
        if op.endswith('.protocolBuild') or op in (
            'biu.timeSync.setPayload',
            'biu.timeSync.broadcastTick',
            'xl.timeSync.setPayload',
            'xl.timeSync.broadcastTick',
            'biu.system.reset',
            'xl.system.cmd',
            'biu.tm.request',
            'xl.tm.request',
        ):
            cmd_id = str(uuid.uuid4())
            cmd = {
                'cmd_id': cmd_id,
                'name': op,
                'protocol_build': params.get('protocolBuild')
                or {
                    'method': params.get('method'),
                    'kwargs': params.get('kwargs') or {},
                },
                'use_business': False,
            }
            await push_command(redis, device_id, cmd)
            result = await wait_command_result(redis, device_id, cmd_id, timeout_s=12.0)
            if not result:
                return {'cmdId': cmd_id, 'success': False, 'message': '等待执行结果超时'}
            ok = bool(result.get('success', False))
            return {
                'cmdId': cmd_id,
                'success': ok,
                'message': '发送成功' if ok else (result.get('message') or '发送失败'),
            }

        # HEX 业务载荷（经 use_business 再组 CAN 协议帧）
        hex_ops = {
            'biu.timedYc.enable': lambda p: (
                '0A 80 00 01 00 01 01 AA AA' if p.get('enable') else '0A 80 00 01 00 01 00 AA AA'
            ),
            'biu.timedYc.param': lambda p: (
                f'0A 81 00 04 00 04 {int(str(p.get("dataCode", "F9")).upper().replace("H", ""), 16):02X} '
                f'{(int(p.get("intervalMs", 1000)) >> 8) & 0xFF:02X} {int(p.get("intervalMs", 1000)) & 0xFF:02X} AA AA'
            ),
            'biu.ppsTime.enable': lambda p: (
                '0A 82 00 01 00 01 01 AA AA' if p.get('enable') else '0A 82 00 01 00 01 00 AA AA'
            ),
            'biu.ppsTime.start': lambda p: '0A 83 00 08 00 08 00 00 00 00 00 00 00 00 AA AA',
            'biu.ppsTime.offset': lambda p: (
                f'0A 84 00 04 00 04 {(int(p.get("offsetMs", 0)) >> 8) & 0xFF:02X} '
                f'{int(p.get("offsetMs", 0)) & 0xFF:02X} AA AA'
            ),
            'biu.rate.start': lambda p: '0A 85 00 02 00 02 01 00 AA AA',
            'biu.rate.stop': lambda p: '0A 85 00 02 00 02 00 00 AA AA',
        }
        if op in hex_ops:
            hex_text = hex_ops[op](params)
        elif op in ('biu.customSend', 'xl.customSend', 'customSend'):
            hex_text = params.get('hex', '')
            if params.get('appendChecksum'):
                from module_payload.cfg.telecontrol_assembler import calc_checksum, hex_to_bytes

                raw = hex_to_bytes(hex_text)
                hex_text = ' '.join(f'{b:02X}' for b in raw) + f' {calc_checksum(raw):02X}'
        else:
            raise ServiceException(message=f'未知控制操作: {op}')

        send_body = TelecontrolSendModel(deviceId=device_id, hex=hex_text, name=op)
        return await cls.send(redis, send_body)

    @classmethod
    async def run_sequence(
        cls,
        redis: aioredis.Redis,
        device_id: str,
        commands: list[dict[str, Any]],
        default_interval: int = 2000,
    ) -> dict[str, Any]:
        """按间隔依次 send；任一条失败即停。每条都会写 Redis 命令队列。"""
        results = []
        fallback = int(default_interval) if int(default_interval) >= 0 else 2000
        for idx, item in enumerate(commands):
            hex_text = item.get('hex', '')
            if not hex_text:
                results.append({'success': False, 'message': 'HEX 为空'})
                break
            body = TelecontrolSendModel(
                deviceId=device_id,
                hex=hex_text,
                name=item.get('name'),
                broadcast=is_broadcast_hex(hex_text),
            )
            result = await cls.send(redis, body)
            results.append(result)
            if not result.get('success'):
                break
            try:
                interval = int(item.get('interval', -1))
            except (TypeError, ValueError):
                interval = -1
            if interval < 0:
                interval = fallback
            if idx < len(commands) - 1:
                await asyncio.sleep(interval / 1000.0)
        return {'total': len(results), 'results': results}
