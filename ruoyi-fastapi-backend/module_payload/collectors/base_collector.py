"""
采集进程基类：Redis 通信、指令队列、心跳与状态上报。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collectors import redis_cmd_helper as redis_cmd
from module_payload.collectors.collector_redis import CollectorRedis
from module_payload.collectors.redis_sync import create_sync_redis, loads_json
from module_payload.assemblers import CAMERA_IMAGE_ASSEMBLER_IDS
from module_payload.constants import (
    ASSEMBLED_PREVIEW_HEX_MAX,
    ASSEMBLED_STORE_MIN_INTERVAL_S,
    ASSEMBLER_CAMERA_IMAGE_D6,
    COLLECTOR_LOOP_INTERVAL_S,
    IO_LOG_MAX,
    IO_PREVIEW_COALESCE_S,
    SRC_KIND_SERIAL,
)
from module_payload.store.error_store import push_pipeline_error
from module_payload.store.session_store import get_session_sync


def preview_io_coalesce_kind(direction: str, data: bytes | None) -> str | None:
    """预览日志合并键：send 返回 None（不拦截）；recv 按帧头分类。

    ``EB D9`` 与 ``EB 90 D8`` 是不同类型；``EB 90 D6`` 图像应答又是一类。
    """
    if str(direction).lower() == 'send':
        return None
    payload = bytes(data or b'')
    if len(payload) >= 2 and payload[0] == 0xEB and payload[1] == 0xD9:
        return 'EB D9'
    if len(payload) >= 3 and payload[0] == 0xEB and payload[1] == 0x90:
        return f'EB 90 {payload[2]:02X}'
    if len(payload) >= 2 and payload[0] == 0x55 and payload[1] == 0xAA:
        return '55 AA'
    n = min(3, len(payload))
    if n <= 0:
        return 'recv'
    return ' '.join(f'{b:02X}' for b in payload[:n])


class BaseCollector:
    """采集进程基类：Redis 指令/控制队列、心跳、会话组帧入库与收发日志。"""

    def __init__(self, device_id: str, config: dict[str, Any]) -> None:
        """初始化 Redis 连接与组帧 / 落盘 / 会话缓存。"""
        self.device_id = device_id  # 本进程绑定的设备 id（``serial:`` / ``can:`` / ``net:``）
        self.config = config  # 打开连接时写入的采集配置
        self._running = False  # 采集主循环开关
        # 写入进缓冲由刷写线程 pipeline 刷出；读同名立刻执行。热路径勿再开连接
        self._redis = CollectorRedis(create_sync_redis())
        self._rx_count = 0  # 收包计数
        self._tx_count = 0  # 发包计数
        self._assembler = None  # 当前单路组装器
        self._assembler_id: str | None = None  # 与 `_assembler` 对应的 assemblerId
        self._assemblers: dict[str, Any] = {}  # demux 多路：assemblerId -> 组装器
        self._demux = None  # 按会话 routes 分流
        self._demux_fp: str | None = None  # routes 指纹，变化时重建 demux
        # device_id -> ConnectionTransferLogger；source 变更时按设备切换
        self._xfer_loggers: dict[str, Any] = {}
        self._xfer_tags: dict[str, str] = {}  # device_id -> 当前落盘 tag
        self._session_cache: dict[str, dict[str, Any]] = {}  # `{src_kind}:{src_param}` -> 会话
        self._session_cache_mono: dict[str, float] = {}  # 会话缓存写入时刻（monotonic）
        self._assembled_mono: dict[str, float] = {}  # assembled Redis 限频时刻
        self._pipeline_lock = threading.RLock()  # 组帧 / 会话热路径互斥
        self._rx_thread: threading.Thread | None = None  # 全双工独立收流线程
        self._io_log_seq_local: dict[str, int] = {}  # 预览日志本地序号水位
        self._preview_io_lock = threading.Lock()  # 预览 1s 合并（RX / 发送线程）
        self._preview_io_hold: dict[str, dict[str, Any]] = {}  # device_id → last_write + 待写最新一条
        # 调试页 stream：内存环缓，请求/退出才刷 Redis
        self._stream_io_lock = threading.Lock()
        self._stream_io_bufs: dict[str, deque] = {}
        self._stream_io_seq: dict[str, int] = {}
        self._stream_io_flushed_seq: dict[str, int] = {}

    def setup(self) -> bool:
        """子类打开硬件；成功返回 True，失败应已写 status。"""
        raise NotImplementedError

    def read_and_parse(self) -> None:
        """子类读一截数据并交给会话入库。"""
        raise NotImplementedError

    def execute_command(self, command: dict[str, Any]) -> dict[str, Any]:
        """子类执行一条发送指令，返回 `{success, message, ...}`。"""
        raise NotImplementedError

    def handle_control(self, msg: dict[str, Any]) -> None:
        """子类可覆盖：处理开/关通道等控制消息。"""
        op = msg.get('op')
        if op in ('session_changed', 'rebind', 'source_changed'):
            with self._pipeline_lock:
                # 会话/来源变更：清缓存、切落盘、重置遥测解析器
                self._invalidate_session_cache()
                self._sync_xfer_logger()
                self._reset_tm_parsers()
        elif op == 'reload_tm_cfg':
            with self._pipeline_lock:
                # 配置热重载：清空进程内 TeleMetryCfgManager
                self._reset_tm_parsers()

    def _reset_tm_parsers(self) -> None:
        """配置热重载 / 会话变更：清空本进程内 TeleMetryCfgManager。"""
        try:
            from module_payload.parsers import biu_can_tm as can_ingest
            from module_payload.parsers import xl_camera_tm as cam_ingest
            from module_payload.parsers import xl_camera_tm_v17 as cam_v17_ingest
            from module_payload.parsers import xl_board_tm as xl_ingest
            from module_payload.parsers import xl_can_tm as xl_can_ingest
            from module_payload.parsers import xl_cpazx_tm as cpazx_ingest

            can_ingest.reset_tm_mgr()
            xl_can_ingest.reset_tm_mgr()
            cam_ingest.reset_xl_camera_tm_mgr()
            cam_v17_ingest.reset_xl_camera_tm_v17_mgr()
            xl_ingest.reset_xl_board_tm_mgr()
            cpazx_ingest.reset_xl_cpazx_tm_mgr()
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
        """刷预览合并缓存与调试流到 Redis（断连则跳过），再关闭落盘 logger。"""
        try:
            self._flush_preview_io_all()
        except Exception:
            pass
        try:
            self._flush_stream_io_to_redis()
        except Exception:
            pass
        self._close_all_xfer_loggers()

    def close_redis(self) -> None:
        """进程收尾：排空写缓冲、裁一次、关连接。"""
        try:
            self._redis.close()
        except Exception:
            pass

    def stop(self) -> None:
        """请求主循环退出（不立刻关硬件）。"""
        self._running = False

    def _xfer_kind(self) -> str:
        """按 device_id 推断落盘类型：`can` / `other`。"""
        from module_payload.collectors.connection_transfer_logger import infer_xfer_kind

        return infer_xfer_kind(self.device_id)

    def _resolve_xfer_tag(self, device_id: str | None = None) -> str:
        """落盘文件名前缀：source + 设备 id（如 zk_serial_COM4）；home 仅用设备 id。"""
        from module_payload.collectors.connection_transfer_logger import (
            sanitize_tag,
            tag_from_device_id,
        )
        from module_payload.constants import infer_src_kind

        did = device_id or self.device_id
        device_part = tag_from_device_id(did)
        source = ''
        try:
            session = get_session_sync(self._redis, did, infer_src_kind(did)) or {}
            source = (session.get('source') or '').strip()
        except Exception:
            source = ''
        if not source:
            source = str((self.config or {}).get('source') or '').strip()
        if source and source.lower() != 'home':
            return sanitize_tag(f'{source}_{device_part}')
        return device_part

    def _get_xfer_logger(self, device_id: str | None = None):
        """按设备取落盘 logger；tag 变化时关旧开新。"""
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
        """刷盘并关闭全部连接级落盘文件。"""
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
        """原始收/发写入连接级落盘（失败静默）。"""
        try:
            logger = self._get_xfer_logger(device_id)
            if str(direction).lower() == 'send':
                logger.append_send(data or b'', frame_id=frame_id)
            else:
                logger.append_recv(data or b'', frame_id=frame_id)
        except Exception:
            pass

    def _xfer_append_eng(self, data: bytes, device_id: str | None = None) -> None:
        """表格 4 组帧完成后写入 *_eng.bin（失败静默）。"""
        try:
            logger = self._get_xfer_logger(device_id)
            append_eng = getattr(logger, 'append_eng', None)
            if callable(append_eng):
                append_eng(data or b'')
        except Exception:
            pass

    def _xfer_append_can_assembled(self, payload: bytes, device_id: str | None = None) -> None:
        """CAN 组包完成后写入 recv 侧 assembled 行。"""
        try:
            logger = self._get_xfer_logger(device_id)
            logger.append_can_assembled(payload or b'')
        except Exception:
            pass

    def _invalidate_session_cache(self) -> None:
        """会话/绑定变更：丢弃 1 秒会话缓存，下次重新 GET。"""
        self._session_cache.clear()
        self._session_cache_mono.clear()

    def _get_session_cached(self, src_param: str, src_kind: str) -> dict[str, Any]:
        """读会话：同 key 1 秒内复用，避免热路径每帧 Redis GET。"""
        key = f'{src_kind}:{src_param}'
        now = time.monotonic()
        last = self._session_cache_mono.get(key, 0.0)
        # 会话缓存 1 秒，避免热路径每帧打 Redis
        if key in self._session_cache and now - last < 1.0:
            return self._session_cache[key]
        session = get_session_sync(self._redis, src_param, src_kind) or {}
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
        """已持 `_pipeline_lock`：按会话 routes 或单 assembler 组帧入库。"""
        if not data:
            return
        try:
            from module_payload.assemblers import create_assembler, normalize_assembler_id
            from module_payload.demux import StreamDemux, routes_fingerprint
            from module_payload.parsers import resolve_parser

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
        """多路由分流：demux 拆完整帧 → 对应组装器 → 解释器。"""
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
        """取出组装器错误并写入 pipeline 错误队列。"""
        take_errors = getattr(assembler, 'take_errors', None)
        if not callable(take_errors):
            return
        err_stage = 'camera' if assembler_id in CAMERA_IMAGE_ASSEMBLER_IDS else 'assembler'
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
        """组装结果写 Redis assembled；有 parserId 再解释写遥测。

        解释器与文件回放同源（如 XlBoardTmIngest）：此处调 ingest_bytes_sync，
        回放调 parse_bytes；字段 cfg 相同，落库键不同（tm vs fileplay）。
        """
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
            # 表格4组帧结果落 *_eng.bin（每包都写，不受 Redis 限频）；不入 MySQL
            if assembler_id == 'eng_tm_subpkt':
                self._xfer_append_eng(item.data, device_id=src_param)
            if (item.meta or {}).get('kind') == 'image' or assembler_id in CAMERA_IMAGE_ASSEMBLER_IDS:
                self._store_camera_image(src_param, item)
                continue
            if src_kind == SRC_KIND_SERIAL:
                self._preview_recv_io(item.data, ingest)
            if ingest is None:
                continue
            ingest_kw = {
                'src_param': src_param,
                'src_kind': src_kind,
                'parser_id': parser_id,
                'quiet': True,
            }
            try:
                ingest.ingest_bytes_sync(
                    self._redis,
                    item.data,
                    assembler_id=assembler_id,
                    **ingest_kw,
                )
            except TypeError:
                ingest.ingest_bytes_sync(self._redis, item.data, **ingest_kw)

    def _preview_recv_io(self, data: bytes, ingest: Any) -> None:
        """串口 Redis 预览：有解释器则写其拆出的完整帧，否则写组装载荷。

        一块数据里若拆出多帧，传输信息只显示最后一帧；同类 recv 再按 1s 合并最新一条。
        ``recv.bin`` / 调试 stream 仍是原始字节流，不受此抽样影响。
        ``io_preview_frames`` 与 ingest 内部可能各拆一次，语义保持不变。

        文件落盘仍是原始 chunk（``read_and_parse`` 里 ``_xfer_append_io``），
        此处 ``to_file=False``，避免把解析帧再写进 recv.bin。
        """
        if not data:
            return
        if ingest is not None:
            preview = getattr(ingest, 'io_preview_frames', None)
            if callable(preview):
                frames = preview(data) or []
                if frames:
                    self._push_io('recv', frames[-1], to_file=False)
                return
        self._push_io('recv', data, to_file=False)

    def _store_assembled(self, device_id: str, assembler_id: str, item: Any) -> None:
        """组装完成写入 Redis：payload:{deviceId}:assembled:latest（限频，避免热路径打爆 Redis）"""
        try:
            now = time.monotonic()
            last = self._assembled_mono.get(device_id, 0.0)
            if now - last < ASSEMBLED_STORE_MIN_INTERVAL_S:
                return
            self._assembled_mono[device_id] = now
            from module_payload.pipeline import assembled_entry, write_assembled_sync

            meta = dict(item.meta or {})
            is_image = meta.get('kind') == 'image'
            entry = assembled_entry(
                device_id,
                assembler_id,
                item.data,
                meta,
                hex_max=ASSEMBLED_PREVIEW_HEX_MAX,
                is_image=is_image,
            )
            write_assembled_sync(self._redis, device_id, entry)
        except Exception:
            pass

    def _store_camera_image(self, device_id: str, item: Any) -> None:
        """相机图像存 PNG 文件，``image:meta`` 只留相对路径。"""
        try:
            import io
            import time

            from module_payload.store.image_store import build_camera_rel_path, save_image

            meta = dict(item.meta or {})
            width = int(meta.get('width') or 0)
            height = int(meta.get('height') or 0)
            pixels = item.data or b''
            if width <= 0 or height <= 0 or not pixels:
                return
            try:
                from PIL import Image

                img = Image.frombytes('L', (width, height), pixels[: width * height])
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                blob = buf.getvalue()
            except Exception:
                blob = pixels[: width * height]
            rel_path = build_camera_rel_path(device_id)
            save_image(rel_path, blob)
            out_meta = {
                'width': width,
                'height': height,
                'imageNo': meta.get('imageNo'),
                'frameCount': meta.get('frameCount'),
                'format': 'png',
                'path': rel_path,
                'phase': 'ready',
                'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
                'assemblerId': meta.get('assemblerId') or ASSEMBLER_CAMERA_IMAGE_D6,
            }
            self._redis.write_batch(redis_cmd.image_meta(device_id, out_meta))
        except Exception:
            pass

    def _is_full_duplex(self) -> bool:
        """顶层或任一通道 `fullDuplex` 为真则全双工。"""
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
        """采集主循环：setup → 控制/指令/收流/心跳 → teardown。"""
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
            # 全双工：收流独立线程，发送不堵 RX
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
                        # 半双工：收发同线程，先处理指令再读
                        self.read_and_parse()
                    self._heartbeat()
                except KeyboardInterrupt:
                    # Ctrl+C 可能传到子进程；安静退出，勿刷 Redis 堆栈
                    self._running = False
                    break
                except Exception:
                    # 单轮异常不得退出采集进程，否则前端会轮询成「已断开」
                    time.sleep(0.05)
                time.sleep(float(self.config.get('loop_interval_s', COLLECTOR_LOOP_INTERVAL_S)))
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
            # 最后关连接：把缓冲里的状态/日志排空后再退出
            self.close_redis()

    def _rx_loop(self) -> None:
        """全双工收流线程：只跑 `read_and_parse`。"""
        interval = float(self.config.get('loop_interval_s', COLLECTOR_LOOP_INTERVAL_S))
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
        """弹出 Redis 控制队列：`stop` / 会话变更等。"""
        key = rk.ctrl_queue_key(self.device_id)
        for _ in range(8):
            raw = self._redis.lpop(key)
            if not raw:
                break
            msg = loads_json(raw)
            if not msg:
                continue
            op = msg.get('op')
            if op == 'stop':
                try:
                    self._flush_stream_io_to_redis()
                except Exception:
                    pass
                self._running = False
                return
            if op == 'flush_io_stream':
                did = str(msg.get('device_id') or '') or str(self.device_id or '')
                if did:
                    self._flush_stream_io_to_redis(device_id=did, req_id=msg.get('req_id'))
                continue
            if op == 'clear_io_stream':
                did = str(msg.get('device_id') or '') or str(self.device_id or '')
                if did:
                    self._clear_stream_io(device_id=did, req_id=msg.get('req_id'))
                continue
            self.handle_control(msg)

    def _consume_commands(self) -> None:
        """弹出指令队列，执行后写 cmd_result 与发送历史。"""
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
            self._redis.write_batch(redis_cmd.cmd_result(self.device_id, cmd_id, result))
            if result.get('success'):
                self._push_history(cmd, result)
            self._tx_count += 1

    def _io_log_targets(self, device_id: str) -> list[str]:
        """收发日志写入目标：设备 id；若会话来源非 home，再双写 source:{source}。"""
        targets = [device_id]
        source = ''
        try:
            from module_payload.constants import infer_src_kind

            session = get_session_sync(self._redis, device_id, infer_src_kind(device_id)) or {}
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
        *,
        to_file: bool = True,
        ts: str | None = None,
    ) -> None:
        """原始收发日志，供控制页接收区轮询。

        CAN 可将 frame_id 与 data 分开存储，避免 ID 与载荷粘在一起。
        串口等带功能来源时双写 ``payload:source:{source}:io``，单板页按来源聚合。
        ``to_file=False`` 只写 Redis 预览（解析帧），不重复落盘。

        预览 Redis：同类 recv 距上次写入 1s 内只缓存最新一条；send 立即写，且会先刷出缓存的 recv。
        调试页 stream（``_push_stream_io``）不走这里，不拦截。
        """
        if not data and frame_id is None:
            return
        did = device_id or self.device_id
        payload = data or b''
        dir_name = 'send' if str(direction).lower() == 'send' else 'recv'
        if to_file:
            try:
                self._xfer_append_io(
                    dir_name,
                    payload,
                    device_id=did,
                    frame_id=int(frame_id) if frame_id is not None else None,
                )
            except Exception:
                pass
        try:
            self._ensure_preview_io_coalesce()
            args = {
                'did': did,
                'dir_name': dir_name,
                'payload': payload,
                'peer': peer or '',
                'display_hex': display_hex,
                'frame_id': frame_id,
                'ts': ts,
            }
            with self._preview_io_lock:
                self._push_preview_io_locked(preview_io_coalesce_kind(dir_name, payload), args)
        except Exception:
            pass

    def _preview_io_now(self) -> float:
        """预览合并用时钟；测试可替换。"""
        return time.monotonic()

    def _ensure_preview_io_coalesce(self) -> None:
        """测试 ``__new__`` 未走 ``__init__`` 时补齐合并状态。"""
        if getattr(self, '_preview_io_lock', None) is None:
            self._preview_io_lock = threading.Lock()
        if getattr(self, '_preview_io_hold', None) is None:
            self._preview_io_hold = {}

    def _push_preview_io_locked(self, kind: str | None, args: dict[str, Any]) -> None:
        """已持锁：send / 换类型先刷缓存；同类 recv 距上次写入 1s 内只留最新。"""
        did = args['did']
        now = self._preview_io_now()
        hold = self._preview_io_hold.get(did)
        if kind is None:
            self._emit_preview_pending_locked(did)
            self._emit_preview_io_locked(args)
            self._preview_io_hold.pop(did, None)
            return
        if hold and hold.get('kind') != kind:
            self._emit_preview_pending_locked(did)
            hold = None
        if hold is None:
            self._emit_preview_io_locked(args)
            self._preview_io_hold[did] = {'kind': kind, 'last_write': now, 'pending': None}
            return
        if now - float(hold.get('last_write') or 0.0) >= IO_PREVIEW_COALESCE_S:
            # 只写当前这条（比缓存更新）；若再把 pending 一并写出，每秒 2 包就会变成 2Hz
            self._emit_preview_io_locked(args)
            hold['kind'] = kind
            hold['last_write'] = now
            hold['pending'] = None
            return
        hold['pending'] = args

    def _emit_preview_pending_locked(self, did: str) -> None:
        """已持锁：把该设备缓存的最新 recv 写出，并刷新限流起点。"""
        hold = self._preview_io_hold.get(did)
        if not hold:
            return
        pending = hold.get('pending')
        hold['pending'] = None
        if pending:
            self._emit_preview_io_locked(pending)
            hold['last_write'] = self._preview_io_now()

    def _flush_preview_io_due(self) -> None:
        """距上次写入满 1s：写出缓存的最新 recv。"""
        self._ensure_preview_io_coalesce()
        now = self._preview_io_now()
        with self._preview_io_lock:
            for did, hold in list(self._preview_io_hold.items()):
                if not hold.get('pending'):
                    continue
                if now - float(hold.get('last_write') or 0.0) < IO_PREVIEW_COALESCE_S:
                    continue
                self._emit_preview_pending_locked(did)

    def _flush_preview_io_all(self) -> None:
        """进程收尾：未到期的缓存也写出，避免丢最后一条。"""
        self._ensure_preview_io_coalesce()
        with self._preview_io_lock:
            for did in list(self._preview_io_hold):
                self._emit_preview_pending_locked(did)
            self._preview_io_hold.clear()

    def _emit_preview_io_locked(self, args: dict[str, Any]) -> None:
        """已持锁：真正 LPUSH 预览日志并分配序号。"""
        payload: bytes = args['payload']
        ts_text = str(args.get('ts') or '').strip() or datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        base = {
            'ts': ts_text,
            'dir': args['dir_name'],
            'hex': ' '.join(f'{b:02X}' for b in payload),
            'len': len(payload),
            'peer': args.get('peer') or '',
        }
        frame_id = args.get('frame_id')
        if frame_id is not None:
            fid = int(frame_id) & 0x1FFFFFFF
            base['frameIdHex'] = ' '.join(f'{b:02X}' for b in fid.to_bytes(4, 'big'))
        display_hex = args.get('display_hex')
        if display_hex is not None:
            base['displayHex'] = bool(display_hex)
        for target in self._io_log_targets(args['did']):
            entry = {**base, 'seq': self._next_io_seq(target)}
            self._redis.write_batch(redis_cmd.io_log(target, [entry]))

    def _next_io_seq(self, target: str) -> int:
        """预览日志序号：只在首次读一次 Redis，之后本地自增。

        每包都 ``INCR`` 会让采集线程按包数做同轮询往返（整图 1250 帧就是 1250 次），
        采图会被拖慢；序号写回走缓冲，与日志同一条 pipeline。
        """
        local = getattr(self, '_io_log_seq_local', None)
        if local is None:
            local = {}
            self._io_log_seq_local = local
        seq = local.get(target)
        if seq is None:
            try:
                seq = int(self._redis.get(rk.io_log_seq_key(target)) or 0)
            except Exception:
                seq = 0
        seq = int(seq) + 1
        local[target] = seq
        self._redis.write_batch(redis_cmd.io_log_seq(target, seq))
        return seq

    def _ensure_stream_io(self) -> None:
        """测试用 ``__new__`` 未走 ``__init__`` 时补齐环缓。"""
        if getattr(self, '_stream_io_bufs', None) is None:
            self._stream_io_lock = threading.Lock()
            self._stream_io_bufs = {}
            self._stream_io_seq = {}
            self._stream_io_flushed_seq = {}

    def _push_stream_io(
        self,
        direction: str,
        data: bytes,
        peer: str = '',
        device_id: str | None = None,
        display_hex: bool | None = None,
        frame_id: int | None = None,
    ) -> None:
        """调试页全量流：只进内存环缓（最多 IO_LOG_MAX），不写 Redis。"""
        if not data and frame_id is None:
            return
        did = device_id or self.device_id
        payload = data or b''
        dir_name = 'send' if str(direction).lower() == 'send' else 'recv'
        try:
            self._ensure_stream_io()
            entry: dict[str, Any] = {
                'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
                'dir': dir_name,
                'data': payload,
                'len': len(payload),
                'peer': peer or '',
            }
            if frame_id is not None:
                fid = int(frame_id) & 0x1FFFFFFF
                entry['frameIdHex'] = ' '.join(f'{b:02X}' for b in fid.to_bytes(4, 'big'))
            if display_hex is not None:
                entry['displayHex'] = bool(display_hex)
            with self._stream_io_lock:
                seq = int(self._stream_io_seq.get(did, 0)) + 1
                self._stream_io_seq[did] = seq
                entry['seq'] = seq
                buf = self._stream_io_bufs.get(did)
                if buf is None:
                    buf = deque(maxlen=IO_LOG_MAX)
                    self._stream_io_bufs[did] = buf
                buf.append(entry)
        except Exception:
            pass

    def _stream_entry_to_redis(self, entry: dict[str, Any]) -> dict[str, Any]:
        """内存条目转 Redis JSON（此时才做 HEX）。"""
        payload = entry.get('data') or b''
        out: dict[str, Any] = {
            'ts': entry.get('ts') or '',
            'dir': entry.get('dir') or 'recv',
            'hex': ' '.join(f'{b:02X}' for b in payload),
            'len': int(entry.get('len') or 0),
            'peer': entry.get('peer') or '',
            'seq': int(entry.get('seq') or 0),
        }
        if entry.get('frameIdHex'):
            out['frameIdHex'] = entry['frameIdHex']
        if 'displayHex' in entry:
            out['displayHex'] = bool(entry['displayHex'])
        return out

    def _flush_one_stream_io(self, did: str) -> bool:
        """把该设备未刷出的环缓增量写入 Redis（调试页请求时才落）。

        返回 True 表示无 pending 或全部写成功；Redis 异常返回 False，且不推进
        ``_stream_io_flushed_seq``，下次请求重发。
        """
        self._ensure_stream_io()
        with self._stream_io_lock:
            buf = self._stream_io_bufs.get(did)
            if not buf:
                return True
            flushed = int(self._stream_io_flushed_seq.get(did, 0))
            pending = [e for e in buf if int(e.get('seq') or 0) > flushed]
            if not pending:
                return True
            snap = list(pending)
        try:
            entries = [self._stream_entry_to_redis(e) for e in snap]
            last_seq = int(snap[-1]['seq'])
            # 入队即推进水位：写失败由封装自己重试，重发会让调试页出现重复行
            self._redis.write_batch(redis_cmd.io_stream(did, entries, last_seq=last_seq))
            with self._stream_io_lock:
                prev = int(self._stream_io_flushed_seq.get(did, 0))
                if last_seq > prev:
                    self._stream_io_flushed_seq[did] = last_seq
            # 调试页要拿到全量，只有确认已落 Redis 才 ack
            return self._redis.flush()
        except Exception:
            return False

    def _ack_stream_io(self, device_id: str | None, req_id: Any) -> None:
        """应答主进程：刷/清已结束。Redis 断了就跳过。"""
        if not req_id:
            return
        ack_did = str(device_id or self.device_id)
        try:
            self._redis.write_batch(redis_cmd.io_stream_ack(ack_did, str(req_id)))
            self._redis.flush()
        except Exception:
            pass

    def _flush_stream_io_to_redis(
        self, device_id: str | None = None, req_id: str | None = None
    ) -> None:
        """增量刷 stream 到 Redis；无请求时刷全部设备缓冲。仅全部成功才 ack。"""
        self._ensure_stream_io()
        if device_id:
            dids = [str(device_id)]
        else:
            with self._stream_io_lock:
                dids = list(self._stream_io_bufs.keys()) or [self.device_id]
        ok = True
        for did in dids:
            if not self._flush_one_stream_io(did):
                ok = False
        if ok:
            self._ack_stream_io(device_id, req_id)

    def _clear_stream_io(self, device_id: str | None = None, req_id: str | None = None) -> None:
        """清空内存环缓（及该设备 Redis stream）。调试页清理时由 ctrl 触发。"""
        self._ensure_stream_io()
        if device_id:
            dids = [str(device_id)]
        else:
            with self._stream_io_lock:
                dids = list(self._stream_io_bufs.keys()) or [self.device_id]
        with self._stream_io_lock:
            for did in dids:
                self._stream_io_bufs.pop(did, None)
                self._stream_io_seq[did] = 0
                self._stream_io_flushed_seq.pop(did, None)
        try:
            keys: list[str] = []
            for did in dids:
                keys.append(rk.io_stream_key(did))
                keys.append(rk.io_stream_seq_key(did))
            self._redis.write_batch(redis_cmd.delete(keys))
        except Exception:
            pass
        self._ack_stream_io(device_id, req_id)

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
        self._redis.write_batch(redis_cmd.history(src_param, entry))
        try:
            from module_payload.cfg.hex_text import hex_to_bytes

            raw_hex = cmd.get('hex') or ''
            frame_id = cmd.get('frame_id')
            if (str(raw_hex).strip() or frame_id is not None) and result.get('success', True):
                display_hex = cmd.get('display_hex')
                if display_hex is None:
                    display_hex = True
                peer = str(result.get('peer') or '')
                payload = hex_to_bytes(raw_hex) if str(raw_hex).strip() else b''
                self._push_io(
                    'send',
                    payload,
                    peer=peer,
                    device_id=src_param,
                    display_hex=bool(display_hex),
                    frame_id=int(frame_id) if frame_id is not None else None,
                )
                self._push_stream_io(
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
            self._redis.write_batch(redis_cmd.tx_queue(tx_ev))
        except Exception:
            pass

    def _heartbeat(self) -> None:
        """刷新 Redis 心跳 TTL，并刷出到期的预览合并缓存。"""
        try:
            self._flush_preview_io_due()
        except Exception:
            pass
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        self._redis.write_batch(redis_cmd.heartbeat(self.device_id, now))

    def _write_status(self, state: str, message: str = '') -> None:
        """写设备 status；`stopped` 时勿覆盖新进程的 key。"""
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
                self._redis.write_batch(redis_cmd.delete([key]))
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
        self._redis.write_batch(redis_cmd.status(self.device_id, payload))

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
                self._redis.write_batch(redis_cmd.delete([key]))
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
        self._redis.write_batch(redis_cmd.status(channel_device_id, payload))

    # 遥测热写统一走 parsers.BiuCanTmIngest（_try_session_ingest）；勿在采集侧再写一套 latest/curve/archive。
