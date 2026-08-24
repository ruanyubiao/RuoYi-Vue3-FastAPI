"""
采集进程基类：Redis 通信、指令队列、心跳与状态上报。
"""

from __future__ import annotations

import json
import threading
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
    IO_LOG_HEX_MAX_BYTES,
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
        self._assemblers: dict[str, Any] = {}
        self._demux = None
        self._demux_fp: str | None = None
        # device_id -> ConnectionTransferLogger；source 变更时按设备切换
        self._xfer_loggers: dict[str, Any] = {}
        self._xfer_tags: dict[str, str] = {}
        self._session_cache: dict[str, dict[str, Any]] = {}
        self._session_cache_mono: dict[str, float] = {}
        self._assembled_mono: dict[str, float] = {}
        self._pipeline_lock = threading.RLock()
        self._rx_thread: threading.Thread | None = None

    def setup(self) -> bool:
        raise NotImplementedError

    def read_and_parse(self) -> None:
        raise NotImplementedError

    def execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def handle_control(self, msg: dict[str, Any]) -> None:
        """子类可覆盖：处理开/关通道等控制消息。"""
        op = msg.get('op')
        if op in ('session_changed', 'rebind', 'source_changed'):
            with self._pipeline_lock:
                self._invalidate_session_cache()
                self._sync_xfer_logger()
                self._reset_tm_parsers()
        elif op == 'reload_tm_cfg':
            with self._pipeline_lock:
                self._reset_tm_parsers()

    def _reset_tm_parsers(self) -> None:
        """配置热重载 / 会话变更：清空本进程内 TeleMetryCfgManager。"""
        try:
            from module_payload.parsers import camera_sc_link41ep as cam_ingest
            from module_payload.parsers import tm_can_yc_ingest as can_ingest
            from module_payload.parsers import xl_board_tm as xl_ingest
            from module_payload.parsers import xl_can_tm as xl_can_ingest

            can_ingest.reset_tm_mgr()
            xl_can_ingest.reset_tm_mgr()
            cam_ingest.reset_cam_tm_mgr()
            xl_ingest.reset_xl_board_tm_mgr()
        except Exception:
            pass

    def _reset_rx_framing(self) -> None:
        """丢弃未完成组帧 / 分流缓存，避免硬件缓冲清空后半截旧帧拼到新数据上。"""
        with self._pipeline_lock:
            asm = getattr(self, '_assembler', None)
            if asm is not None:
                reset = getattr(asm, 'reset', None)
                if callable(reset):
                    try:
                        reset()
                    except Exception:
                        pass
            for extra in (getattr(self, '_assemblers', None) or {}).values():
                reset = getattr(extra, 'reset', None)
                if callable(reset):
                    try:
                        reset()
                    except Exception:
                        pass
            demux = getattr(self, '_demux', None)
            if demux is not None:
                clear = getattr(demux, 'clear', None)
                if callable(clear):
                    try:
                        clear()
                    except Exception:
                        pass
            plugin = getattr(self, '_plugin', None)
            if plugin is not None:
                reset_rx = getattr(plugin, 'reset_rx', None)
                if callable(reset_rx):
                    try:
                        reset_rx()
                    except Exception:
                        pass

    def teardown(self) -> None:
        self._close_all_xfer_loggers()

    def stop(self) -> None:
        self._running = False

    def _xfer_kind(self) -> str:
        from module_payload.collectors.connection_transfer_logger import infer_xfer_kind

        return infer_xfer_kind(self.device_id)

    def _resolve_xfer_tag(self, device_id: str | None = None) -> str:
        """落盘文件名前缀：source + 设备 id（如 zk_serial_COM4）；home 仅用设备 id。"""
        from module_payload.collectors.connection_transfer_logger import (
            sanitize_tag,
            tag_from_device_id,
        )
        from module_payload.constants import infer_src_kind
        from module_payload.service.payload_session_service import PayloadSessionService

        did = device_id or self.device_id
        device_part = tag_from_device_id(did)
        source = ''
        try:
            session = PayloadSessionService.get_session_sync(
                self._redis, did, infer_src_kind(did)
            ) or {}
            source = (session.get('source') or '').strip()
        except Exception:
            source = ''
        if not source:
            source = str((self.config or {}).get('source') or '').strip()
        if source and source.lower() != 'home':
            return sanitize_tag(f'{source}_{device_part}')
        return device_part

    def _get_xfer_logger(self, device_id: str | None = None):
        from module_payload.collectors.connection_transfer_logger import ConnectionTransferLogger

        did = device_id or self.device_id
        tag = self._resolve_xfer_tag(did)
        old_tag = self._xfer_tags.get(did)
        logger = self._xfer_loggers.get(did)
        if logger is not None and old_tag == tag:
            return logger
        if logger is not None:
            try:
                logger.close(flush=True)
            except Exception:
                pass
        logger = ConnectionTransferLogger(tag, kind=self._xfer_kind())
        self._xfer_loggers[did] = logger
        self._xfer_tags[did] = tag
        return logger

    def _sync_xfer_logger(self, device_id: str | None = None) -> None:
        """会话/source 变更：关闭旧对象，按新 tag 懒建（无数据不落文件）。"""
        if device_id:
            ids = [device_id]
        else:
            ids = list({self.device_id, *self._xfer_loggers.keys(), *self._xfer_tags.keys()})
        for did in ids:
            try:
                self._get_xfer_logger(did)
            except Exception:
                pass

    def _close_all_xfer_loggers(self) -> None:
        for did, logger in list(self._xfer_loggers.items()):
            try:
                logger.close(flush=True)
            except Exception:
                pass
        self._xfer_loggers.clear()
        self._xfer_tags.clear()

    def _xfer_append_io(
        self,
        direction: str,
        data: bytes,
        *,
        device_id: str | None = None,
        frame_id: int | None = None,
    ) -> None:
        try:
            logger = self._get_xfer_logger(device_id)
            if str(direction).lower() == 'send':
                logger.append_send(data or b'', frame_id=frame_id)
            else:
                logger.append_recv(data or b'', frame_id=frame_id)
        except Exception:
            pass

    def _xfer_append_can_assembled(self, payload: bytes, device_id: str | None = None) -> None:
        try:
            logger = self._get_xfer_logger(device_id)
            logger.append_can_assembled(payload or b'')
        except Exception:
            pass

    def _invalidate_session_cache(self) -> None:
        self._session_cache.clear()
        self._session_cache_mono.clear()

    def _get_session_cached(self, src_param: str, src_kind: str) -> dict[str, Any]:
        from module_payload.service.payload_session_service import PayloadSessionService

        key = f'{src_kind}:{src_param}'
        now = time.monotonic()
        last = self._session_cache_mono.get(key, 0.0)
        if key in self._session_cache and now - last < 1.0:
            return self._session_cache[key]
        session = PayloadSessionService.get_session_sync(self._redis, src_param, src_kind) or {}
        self._session_cache[key] = session
        self._session_cache_mono[key] = now
        return session

    def _try_session_ingest(self, data: bytes, src_param: str, src_kind: str) -> None:
        """组装器还原完整载荷 → 写 assembled Redis；若已绑定解释器再解析写遥测。"""
        if not data:
            return
        with self._pipeline_lock:
            self._try_session_ingest_locked(data, src_param, src_kind)

    def _try_session_ingest_locked(self, data: bytes, src_param: str, src_kind: str) -> None:
        if not data:
            return
        try:
            from module_payload.assemblers import create_assembler, normalize_assembler_id
            from module_payload.demux import StreamDemux, routes_fingerprint
            from module_payload.parsers import resolve_parser
            from module_payload.service.payload_error_store import push_pipeline_error

            session = self._get_session_cached(src_param, src_kind)
            routes = session.get('routes') or []
            if routes:
                self._ingest_via_demux(
                    data,
                    src_param=src_param,
                    src_kind=src_kind,
                    session=session,
                    routes=routes,
                    create_assembler=create_assembler,
                    normalize_assembler_id=normalize_assembler_id,
                    StreamDemux=StreamDemux,
                    routes_fingerprint=routes_fingerprint,
                    resolve_parser=resolve_parser,
                    push_pipeline_error=push_pipeline_error,
                )
                return

            # 兼容：单 assemblerId
            self._demux = None
            self._demux_fp = None
            assembler_id = normalize_assembler_id(session.get('assemblerId'))
            if getattr(self, '_assembler_id', None) != assembler_id or getattr(self, '_assembler', None) is None:
                self._assembler = create_assembler(assembler_id)
                self._assembler_id = assembler_id

            payloads = self._assembler.feed(data)
            self._emit_assembler_errors(
                self._assembler,
                src_param=src_param,
                assembler_id=assembler_id,
                push_pipeline_error=push_pipeline_error,
            )
            if not payloads:
                return
            parser_id = (session.get('parserId') or '').strip()
            self._dispatch_payloads(
                payloads,
                src_param=src_param,
                src_kind=src_kind,
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
                    message=f'会话入库异常: {e}',
                    device_id=src_param,
                    data_len=len(data),
                )
            except Exception:
                pass

    def _ingest_via_demux(
        self,
        data: bytes,
        *,
        src_param: str,
        src_kind: str,
        session: dict[str, Any],
        routes: list,
        create_assembler: Any,
        normalize_assembler_id: Any,
        StreamDemux: Any,
        routes_fingerprint: Any,
        resolve_parser: Any,
        push_pipeline_error: Any,
    ) -> None:
        fp = routes_fingerprint(routes)
        if self._demux is None or self._demux_fp != fp:
            self._demux = StreamDemux(routes)
            self._demux_fp = fp
            # 路由变化时重置组装器缓存，避免旧状态串扰
            self._assemblers = {}
            self._assembler = None
            self._assembler_id = None

        demux = self._demux
        demux.write(data)
        hits = demux.drain()
        if not hits:
            return

        for hit in hits:
            assembler_id = normalize_assembler_id(hit.assembler_id)
            asm = self._assemblers.get(assembler_id)
            if asm is None:
                asm = create_assembler(assembler_id)
                self._assemblers[assembler_id] = asm

            # demux 已拆完整帧：优先 accept_frame，避免二次粘包处理
            accept = getattr(asm, 'accept_frame', None)
            if callable(accept):
                done = accept(hit.frame)
                payloads = [done] if done is not None else []
            else:
                payloads = asm.feed(hit.frame)

            self._emit_assembler_errors(
                asm,
                src_param=src_param,
                assembler_id=assembler_id,
                push_pipeline_error=push_pipeline_error,
            )
            if not payloads:
                continue

            parser_id = (hit.parser_id or '').strip()
            if not parser_id:
                parser_id = (session.get('parserId') or '').strip()
            self._dispatch_payloads(
                payloads,
                src_param=src_param,
                src_kind=src_kind,
                assembler_id=assembler_id,
                parser_id=parser_id,
                resolve_parser=resolve_parser,
                push_pipeline_error=push_pipeline_error,
            )

    def _emit_assembler_errors(
        self,
        assembler: Any,
        *,
        src_param: str,
        assembler_id: str,
        push_pipeline_error: Any,
    ) -> None:
        take_errors = getattr(assembler, 'take_errors', None)
        if not callable(take_errors):
            return
        err_stage = 'camera' if assembler_id == 'camera_image_d6' else 'assembler'
        for err in take_errors():
            push_pipeline_error(
                self._redis,
                stage=err_stage,
                message=err,
                device_id=src_param,
                assembler_id=assembler_id,
            )

    def _dispatch_payloads(
        self,
        payloads: list[Any],
        *,
        src_param: str,
        src_kind: str,
        assembler_id: str,
        parser_id: str,
        resolve_parser: Any,
        push_pipeline_error: Any,
    ) -> None:
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
            if not item or not getattr(item, 'data', None):
                continue
            self._store_assembled(src_param, assembler_id, item)
            if (item.meta or {}).get('kind') == 'image' or assembler_id == 'camera_image_d6':
                self._store_camera_image(src_param, item)
                continue
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

    def _store_assembled(self, device_id: str, assembler_id: str, item: Any) -> None:
        """组装完成写入 Redis：payload:{deviceId}:assembled:latest（限频，避免热路径打爆 Redis）"""
        try:
            now = time.monotonic()
            last = self._assembled_mono.get(device_id, 0.0)
            if now - last < 0.2:
                return
            self._assembled_mono[device_id] = now
            from datetime import datetime

            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            meta = dict(item.meta or {})
            meta.setdefault('assemblerId', assembler_id)
            is_image = meta.get('kind') == 'image'
            entry = {
                'deviceId': device_id,
                'assemblerId': assembler_id,
                'ts': ts,
                'len': len(item.data),
                'hex': '' if is_image else ' '.join(f'{b:02X}' for b in item.data[:64]),
                'meta': meta,
            }
            dumped = dumps_json(entry)
            self._redis.set(rk.assembled_latest_key(device_id), dumped)
            key = rk.assembled_log_key(device_id)
            self._redis.lpush(key, dumped)
            self._redis.ltrim(key, 0, 49)
        except Exception:
            pass

    def _store_camera_image(self, device_id: str, item: Any) -> None:
        """相机图像写入 image:meta / image:data（PNG base64）。"""
        try:
            import base64
            import io
            import time

            meta = dict(item.meta or {})
            width = int(meta.get('width') or 0)
            height = int(meta.get('height') or 0)
            pixels = item.data or b''
            if width <= 0 or height <= 0 or not pixels:
                return
            fmt = 'png'
            try:
                from PIL import Image

                img = Image.frombytes('L', (width, height), pixels[: width * height])
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                b64 = base64.b64encode(buf.getvalue()).decode('ascii')
            except Exception:
                fmt = 'raw'
                b64 = base64.b64encode(pixels[: width * height]).decode('ascii')
            out_meta = {
                'width': width,
                'height': height,
                'imageNo': meta.get('imageNo'),
                'frameCount': meta.get('frameCount'),
                'format': fmt,
                'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
                'assemblerId': meta.get('assemblerId') or 'camera_image_d6',
            }
            self._redis.set(f'{rk.PREFIX}:{device_id}:image:meta', dumps_json(out_meta))
            self._redis.set(f'{rk.PREFIX}:{device_id}:image:data', b64)
        except Exception:
            pass

    def _is_full_duplex(self) -> bool:
        from module_payload.collectors.duplex import coerce_full_duplex

        top = coerce_full_duplex(self.config.get('full_duplex', self.config.get('fullDuplex')))
        if top:
            return True
        for ch in self.config.get('channels') or []:
            if not isinstance(ch, dict):
                continue
            if coerce_full_duplex(ch.get('full_duplex', ch.get('fullDuplex'))):
                return True
        return False

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
        full_duplex = self._is_full_duplex()
        if full_duplex:
            self._rx_thread = threading.Thread(
                target=self._rx_loop,
                name=f'rx-{self.device_id}',
                daemon=True,
            )
            self._rx_thread.start()
        try:
            while self._running:
                try:
                    self._consume_control()
                    if not self._running:
                        break
                    self._consume_commands()
                    if not full_duplex:
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
            self._running = False
            rx = self._rx_thread
            if rx is not None and rx.is_alive():
                rx.join(timeout=5.0)
            self._rx_thread = None
            try:
                self.teardown()
            except Exception:
                pass
            try:
                self._write_status('stopped', '已停止')
            except Exception:
                pass

    def _rx_loop(self) -> None:
        interval = float(self.config.get('loop_interval_s', 0.01))
        while self._running:
            try:
                self.read_and_parse()
            except KeyboardInterrupt:
                self._running = False
                break
            except Exception:
                time.sleep(0.05)
                continue
            time.sleep(interval)

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

    def _io_log_targets(self, device_id: str) -> list[str]:
        """收发日志写入目标：设备 id；若会话来源非 home，再双写 source:{source}。"""
        targets = [device_id]
        source = ''
        try:
            from module_payload.constants import infer_src_kind
            from module_payload.service.payload_session_service import PayloadSessionService

            session = PayloadSessionService.get_session_sync(
                self._redis, device_id, infer_src_kind(device_id)
            ) or {}
            source = (session.get('source') or '').strip()
        except Exception:
            source = ''
        if not source:
            source = str((self.config or {}).get('source') or '').strip()
        if source and source != 'home':
            sid = rk.source_id(source)
            if sid not in targets:
                targets.append(sid)
        return targets

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
        串口等带功能来源时双写 ``payload:source:{source}:io``，单板页按来源聚合。
        """
        if not data and frame_id is None:
            return
        did = device_id or self.device_id
        try:
            payload = data or b''
            truncated = False
            hex_src = payload
            if len(payload) > IO_LOG_HEX_MAX_BYTES:
                hex_src = payload[:IO_LOG_HEX_MAX_BYTES]
                truncated = True
            hex_text = ' '.join(f'{b:02X}' for b in hex_src)
            if truncated:
                hex_text = f'{hex_text} ...(+{len(payload) - IO_LOG_HEX_MAX_BYTES}B)'
            base = {
                'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
                'dir': 'send' if str(direction).lower() == 'send' else 'recv',
                'hex': hex_text,
                'len': len(payload),
                'peer': peer or '',
            }
            if truncated:
                base['truncated'] = True
            if frame_id is not None:
                fid = int(frame_id) & 0x1FFFFFFF
                # 8 位十六进制，显示时按字节空格分隔：00 00 02 34
                base['frameIdHex'] = ' '.join(f'{b:02X}' for b in fid.to_bytes(4, 'big'))
            # SEND：按发送时是否 HEX 决定前端展示；RECV：由前端按当时勾选冻结
            if display_hex is not None:
                base['displayHex'] = bool(display_hex)
            for target in self._io_log_targets(did):
                seq = int(self._redis.incr(rk.io_log_seq_key(target)))
                entry = {**base, 'seq': seq}
                key = rk.io_log_key(target)
                self._redis.lpush(key, dumps_json(entry))
                self._redis.ltrim(key, 0, IO_LOG_MAX - 1)
            # 文件落盘旁路（失败不影响 Redis 预览）
            self._xfer_append_io(
                base['dir'],
                payload,
                device_id=did,
                frame_id=int(frame_id) if frame_id is not None else None,
            )
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
