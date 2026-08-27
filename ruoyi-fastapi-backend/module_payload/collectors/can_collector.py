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
from module_payload.store.error_store import push_pipeline_error
from module_payload.store.session_store import get_session_sync

def _assembler_to_protocol(assembler_id: str | None):
    """会话 assemblerId → gpcan `CanProtocolType`（透传为 NONE）。"""
    from gpcan import CanProtocolType

    aid = (assembler_id or '').strip()
    if aid == ASSEMBLER_CAN_XL:
        return CanProtocolType.XL
    if aid == ASSEMBLER_CAN_BIU:
        return CanProtocolType.BIU
    # 透传及其它：协议 NONE，便于裸 CAN 测试
    return CanProtocolType.NONE


class CanCollector(BaseCollector):
    """一张 USB-CAN 卡一个进程：多通道收发、会话组帧、定时遥测/对时。"""

    def __init__(self, device_id: str, config: dict[str, Any]) -> None:
        """初始化通道表与定时遥测/同步广播状态。"""
        super().__init__(device_id, config)
        self._channels: dict[int, dict[str, Any]] = {}  # can_index -> {client, cfg, channel_device_id}
        self._timed_tm = False  # 定时遥测请求是否开启
        self._timed_tm_family = 'biu'  # `biu` / `xl`
        self._timed_tm_tick = 0  # 遥测序号，驱动 data_code / sec_header
        self._timed_tm_next = 0.0  # 下次发送 monotonic
        self._timed_tm_prefer_can: int | None = None  # 优先走发起定时的那路
        self._timed_sync = False  # 定时时间同步广播
        self._timed_sync_family = 'biu'
        self._timed_sync_next = 0.0
        self._timed_sync_last_can: int | None = None  # 轮询广播的上一通道
        self._gnss_valid = True  # 对时帧 GNSS 有效标志
        self._start_utc: dict[str, str] = {'biu': '', 'xl': ''}  # 各协议族起始 UTC

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
        """打开指定通道的 gpcan 客户端；已开则只刷新 status。"""
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
        # 打开时预热会话缓存 / 可能的模块 import，避免首帧发送卡在 Redis GET
        try:
            self._get_session_cached(channel_device_id, SRC_KIND_CAN)
            self._sync_client_protocol(self._channels[can_index])
        except Exception:
            pass
        return True, ''

    def handle_control(self, msg: dict[str, Any]) -> None:
        """会话变更时同步协议类型；另处理开/关通道与线缆。"""
        op = msg.get('op')
        if op in ('session_changed', 'rebind', 'source_changed'):
            with self._pipeline_lock:
                # 会话缓存与遥测解析器重置；通道协议按新 assemblerId 对齐
                self._invalidate_session_cache()
                self._sync_xfer_logger()
                self._reset_tm_parsers()
                for ch in self._channels.values():
                    try:
                        self._sync_client_protocol(ch)
                    except Exception:
                        pass
            return
        if op == 'reload_tm_cfg':
            with self._pipeline_lock:
                # 配置热重载：清空进程内 TeleMetryCfgManager
                self._reset_tm_parsers()
            return
        can_index = int(msg.get('can_index', 0))
        if op == 'open_channel':
            self._open_channel_client(can_index, msg.get('config') or {})
        elif op == 'close_channel':
            self._close_channel(can_index)
        elif op == 'set_cable':
            self._set_channel_cable(can_index, msg)

    def _set_channel_cable(self, can_index: int, msg: dict[str, Any]) -> None:
        """热更新通道目标地址 / 线缆标志（不下发 CAN 帧）。"""
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
        """关闭通道硬件并刷盘；末通道时停定时器。"""
        ch = self._channels.pop(can_index, None)
        if not ch:
            return
        channel_device_id = ch.get('channel_device_id')
        if channel_device_id:
            logger = self._xfer_loggers.pop(channel_device_id, None)
            self._xfer_tags.pop(channel_device_id, None)
            if logger is not None:
                try:
                    logger.close(flush=True)
                except Exception:
                    pass
        client = ch['client']
        try:
            client.close_can()
            client.deinit_can()
        except Exception:
            pass
        self._write_channel_status(ch['channel_device_id'], 'closed', '已关闭', connected=False)
        if not self._channels:
            self._stop_all_timers()

    def _stop_all_timers(self) -> None:
        """关闭定时遥测与同步广播（通道全关时调用）。"""
        self._timed_tm = False
        self._timed_tm_next = 0.0
        self._timed_tm_prefer_can = None
        self._timed_sync = False
        self._timed_sync_next = 0.0
        self._timed_sync_last_can = None

    def _timed_tm_pick(self) -> tuple[int | None, dict[str, Any] | None]:
        """选定时遥测走哪路 CAN（优先发起通道）。"""
        from module_payload.collectors.can_timers import pick_timed_tm_can

        can_index = pick_timed_tm_can(list(self._channels.keys()), self._timed_tm_prefer_can)
        if can_index is None:
            return None, None
        return can_index, self._channels.get(can_index)

    def _timed_tm_can_info(self) -> dict[str, Any]:
        """给前端的定时遥测通道标签 / 设备 id。"""
        from module_payload.collectors.can_timers import can_port_label

        if not self._timed_tm:
            return {'timedTmCan': '', 'timedTmDeviceId': ''}
        can_index, ch = self._timed_tm_pick()
        if can_index is None or not ch:
            return {'timedTmCan': '', 'timedTmDeviceId': ''}
        cfg = ch.get('cfg') or {}
        cable = cfg.get('cable_flag')
        return {
            'timedTmCan': can_port_label(can_index, None if cable is None else int(cable)),
            'timedTmDeviceId': ch.get('channel_device_id') or '',
        }

    def _cfg_assembler_id(self, ch: dict[str, Any]) -> str | None:
        """通道打开配置里的 assemblerId；非法则视为未指定。"""
        from module_payload.assemblers import normalize_assembler_id

        cfg = ch.get('cfg') or {}
        raw = cfg.get('assembler_id')
        if raw is None or str(raw).strip() == '':
            return None
        aid = normalize_assembler_id(raw)
        if aid in (ASSEMBLER_CAN_BIU, ASSEMBLER_CAN_XL, ASSEMBLER_PASSTHROUGH):
            return aid
        return None

    def _sync_client_protocol(self, ch: dict[str, Any], *, allow_skip_redis: bool = True) -> str:
        """按组装器同步协议类型。不发送 CAN 帧。

        定时发送路径：通道打开时已按 cfg 设好协议，则跳过 Redis GET
        （Windows + Docker/WSL2 上该 GET 首次可达数秒）。
        """
        from gpcan import CanProtocolParam
        from module_payload.assemblers import normalize_assembler_id

        client = ch['client']
        cfg_aid = self._cfg_assembler_id(ch)
        if allow_skip_redis and cfg_aid:
            proto = _assembler_to_protocol(cfg_aid)
            if client.get_protocol() == proto:
                return cfg_aid

        channel_device_id = ch['channel_device_id']
        session = self._get_session_cached(channel_device_id, SRC_KIND_CAN)
        assembler_id = normalize_assembler_id(session.get('assemblerId') or cfg_aid or ASSEMBLER_CAN_BIU)
        if assembler_id not in (ASSEMBLER_CAN_BIU, ASSEMBLER_CAN_XL, ASSEMBLER_PASSTHROUGH):
            assembler_id = ASSEMBLER_CAN_BIU
        proto = _assembler_to_protocol(assembler_id)
        if client.get_protocol() != proto:
            client.set_protocol_param(CanProtocolParam(type=int(proto)))
        cfg = ch.get('cfg') or {}
        cfg['assembler_id'] = assembler_id
        ch['cfg'] = cfg
        return assembler_id

    def _timer_family(self, timer: dict[str, Any] | None = None) -> str:
        """定时指令的协议族：显式 `family`，否则跟当前定时遥测。"""
        fam = str((timer or {}).get('family') or '').lower()
        if fam == 'xl':
            return 'xl'
        if fam == 'biu':
            return 'biu'
        return 'xl' if self._timed_tm_family == 'xl' else 'biu'

    def _time_sync(self, family: str):
        """取 BIU/XL 各自的时间偏差对象。"""
        from module_payload.collectors.can_timers import time_sync_for_family

        return time_sync_for_family(family)

    def _handle_timer(self, ch: dict[str, Any], timer: dict[str, Any]) -> dict[str, Any]:
        """处理定时遥测/对时/GNSS 等控制指令（多数不下发 CAN）。"""
        kind = str(timer.get('kind') or '').strip()
        family = self._timer_family(timer)
        ts = self._time_sync(family)
        if kind == 'timed_tm':
            enable = bool(timer.get('enable'))
            self._timed_tm = enable
            self._timed_tm_family = family
            self._timed_tm_tick = 0
            self._timed_tm_next = time.monotonic() if enable else 0.0
            if enable:
                prefer = next((i for i, c in self._channels.items() if c is ch), None)
                self._timed_tm_prefer_can = prefer
            else:
                self._timed_tm_prefer_can = None
            out = {
                'success': True,
                'message': '定时遥测已打开' if enable else '定时遥测已关闭',
                'timedTm': enable,
            }
            out.update(self._timed_tm_can_info())
            return out
        if kind == 'timed_sync':
            enable = bool(timer.get('enable'))
            if 'gnssValid' in timer or 'gnss_valid' in timer:
                self._gnss_valid = bool(timer.get('gnssValid', timer.get('gnss_valid', True)))
            self._timed_sync = enable
            self._timed_sync_family = family
            self._timed_sync_next = time.monotonic() if enable else 0.0
            if not enable:
                self._timed_sync_last_can = None
            return {'success': True, 'message': '定时同步广播已打开' if enable else '定时同步广播已关闭'}
        if kind == 'set_gnss':
            self._gnss_valid = bool(timer.get('gnssValid', timer.get('gnss_valid', True)))
            return {'success': True, 'message': 'GNSS 有效标志已更新', 'gnssValid': self._gnss_valid}
        if kind == 'get_status':
            utc = self._start_utc.get(family) or ''
            out = {
                'success': True,
                'message': 'OK',
                'offsetMs': int(ts.offset_ms),
                'utc': utc,
                'timedTm': bool(self._timed_tm and self._timed_tm_family == family),
                'broadcast': bool(self._timed_sync and self._timed_sync_family == family),
                'gnssValid': bool(self._gnss_valid),
            }
            out.update(self._timed_tm_can_info())
            return out
        if kind == 'set_start':
            from module_payload.collectors.can_timers import utc_to_epoch_ms_floor_sec

            utc = str(timer.get('utc') or '').strip()
            payload_ms = utc_to_epoch_ms_floor_sec(utc)
            ts.set_payload_time(payload_ms)
            self._start_utc[family] = utc
            return {
                'success': True,
                'message': '已设起始时间偏差（不下发对时帧）',
                'offsetMs': int(ts.offset_ms),
                'utc': utc,
            }
        if kind == 'set_offset':
            ts.set_offset(int(timer.get('offsetMs') or timer.get('offset_ms') or 0))
            return {
                'success': True,
                'message': '系统时间偏差已设置',
                'offsetMs': int(ts.offset_ms),
                'utc': self._start_utc.get(family) or '',
            }
        if kind == 'reset_start':
            ts.set_offset(0)
            return {
                'success': True,
                'message': '系统时间偏差已重置',
                'offsetMs': int(ts.offset_ms),
                'utc': self._start_utc.get(family) or '',
            }
        return {'success': False, 'message': f'未知定时操作: {kind}'}

    def _tick_timers(self) -> None:
        """主循环末尾推进定时遥测与同步广播。"""
        if not self._channels:
            if self._timed_tm or self._timed_sync:
                self._stop_all_timers()
            return
        now = time.monotonic()
        try:
            self._tick_timed_tm(now)
        except Exception:
            pass
        try:
            self._tick_timed_sync(now)
        except Exception:
            pass

    def _tick_timed_tm(self, now: float) -> None:
        """到期则发一帧遥测请求（BIU 0.5s / XL 1s）。"""
        if not self._timed_tm:
            return
        can_index, ch = self._timed_tm_pick()
        if can_index is None or not ch:
            self._timed_tm = False
            self._timed_tm_next = 0.0
            self._timed_tm_prefer_can = None
            return
        interval = 0.5 if self._timed_tm_family == 'biu' else 1.0
        nxt = float(self._timed_tm_next or 0)
        if nxt and now < nxt:
            return
        from module_payload.collectors.timed_tm import next_biu_tm_data_code, next_xl_tm_sec_header

        tick = int(self._timed_tm_tick or 0)
        if self._timed_tm_family == 'xl':
            kwargs = {'sec_header': next_xl_tm_sec_header(tick)}
        else:
            kwargs = {'data_code': next_biu_tm_data_code(tick)}
        self._send_protocol_quiet(ch, 'build_telemetry_request', kwargs)
        self._timed_tm_tick = tick + 1
        self._timed_tm_next = time.monotonic() + interval

    def _tick_timed_sync(self, now: float) -> None:
        """到期则轮询各通道发时间同步广播。"""
        if not self._timed_sync:
            return
        from module_payload.collectors.can_timers import next_round_robin_can

        open_ids = sorted(self._channels.keys())
        if not open_ids:
            self._stop_all_timers()
            return
        nxt = float(self._timed_sync_next or 0)
        if nxt and now < nxt:
            return
        can_index = next_round_robin_can(open_ids, self._timed_sync_last_can)
        ch = self._channels.get(can_index) if can_index is not None else None
        if not ch:
            return
        ts = self._time_sync(self._timed_sync_family or 'biu')
        sys_ms = int(ts.get_system_time_ms())
        sec, ms = divmod(sys_ms, 1000)
        self._send_protocol_quiet(
            ch,
            'build_time_sync',
            {
                'sec': sec,
                'ms': ms,
                'apply_offset': True,
                'gnss_valid': bool(self._gnss_valid),
            },
        )
        self._timed_sync_last_can = can_index
        self._timed_sync_next = now + 1.0

    def _send_protocol_quiet(self, ch: dict[str, Any], method: str, kwargs: dict[str, Any]) -> None:
        """定时路径组包发送：失败静默，不写指令历史。"""
        from gpcan import CanRetCode

        self._sync_client_protocol(ch)
        client = ch['client']
        if not hasattr(client.builder, method):
            return
        built = getattr(client.builder, method)(**kwargs)
        if built is None or not getattr(built, 'frames', None):
            return
        ret = client.send_msg(built)
        if ret == int(CanRetCode.CAN_RET_CODE_OK):
            self._tx_count += 1

    def read_and_parse(self) -> None:
        """各通道 recv → IO 日志 + 会话组帧；再推进定时器。"""
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
        self._tick_timers()

    def _heartbeat(self) -> None:
        """卡级心跳外，给每个已开通道刷 running status。"""
        super()._heartbeat()
        for ch in self._channels.values():
            cid = ch.get('channel_device_id')
            if not cid:
                continue
            try:
                self._write_channel_status(cid, 'running', '已连接', connected=True)
            except Exception:
                pass

    def _ingest_can_frames(self, channel_device_id: str, frames: list[Any]) -> None:
        """硬件 CAN 帧 → 会话组装器 feed_frames → 解释器。"""
        if not frames:
            return
        try:
            from module_payload.assemblers import create_assembler, normalize_assembler_id
            from module_payload.parsers import resolve_parser

            session = get_session_sync(self._redis, channel_device_id, SRC_KIND_CAN) or {}
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
            for pl in payloads:
                if isinstance(pl, (bytes, bytearray)):
                    raw = bytes(pl)
                else:
                    raw = bytes(getattr(pl, 'data', None) or b'')
                if raw:
                    self._xfer_append_can_assembled(raw, channel_device_id)
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
                push_pipeline_error(
                    self._redis,
                    stage='session',
                    message=f'CAN 组帧入库异常: {e}',
                    device_id=channel_device_id,
                )
            except Exception:
                pass

    def execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        """协议组包 / 业务帧 / 原始 CAN 发送；timer 走 `_handle_timer`。"""
        from gpcan import CanRetCode

        can_index = int(command.get('can_index', self.config.get('can_index', 0)))
        ch = self._channels.get(can_index)
        if not ch:
            raise RuntimeError(f'CAN 通道 {can_index} 未打开')
        client = ch['client']
        hex_text = command.get('hex', '')
        broadcast = bool(command.get('broadcast') or command.get('all_channel'))
        if command.get('timer'):
            return self._handle_timer(ch, command.get('timer') or {})
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
            from module_payload.cfg.hex_text import hex_to_bytes

            raw = hex_to_bytes(hex_text)
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
            from module_payload.cfg.hex_text import hex_to_bytes

            data = hex_to_bytes(hex_text) if hex_text else b''
            if len(data) > 8:
                return {'success': False, 'message': 'CAN_RAW 数据区最多8字节'}
            ret = client.send(un_id, data, un_data_len=len(data))
        if ret != int(CanRetCode.CAN_RET_CODE_OK):
            return {'success': False, 'message': 'CAN 发送失败'}
        return {'success': True, 'message': 'OK'}

    def _consume_commands(self) -> None:
        """按通道分别弹 cmd 队列（卡进程不共用设备级队列）。"""
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
                if result.get('success') and not cmd.get('timer'):
                    self._push_history(cmd, result, src_param=channel_device_id)
                if not cmd.get('timer'):
                    self._tx_count += 1

    def teardown(self) -> None:
        """关闭全部 CAN 通道并刷盘。"""
        for can_index in list(self._channels.keys()):
            self._close_channel(can_index)
        super().teardown()
