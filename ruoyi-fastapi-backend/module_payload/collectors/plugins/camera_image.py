"""相机图像串口插件：主动拉图。

职责：串口收发 + FixedHeaderLenFrameBuffer 拆完整帧 → 交给 CameraImageD6Assembler 拼图 → Redis。
组装器不碰串口/粘包。filter_rx 吞掉 RX，不走会话 ingest。
"""

from __future__ import annotations

import base64
import time
from datetime import datetime
from typing import Any

from module_payload import redis_keys as rk
from module_payload.assemblers.base import AssembledPayload
from module_payload.assemblers.camera_image_d6 import (
    DATA_CHUNK_SIZE,
    FRAME_HEADER,
    FRAME_ID_FIRST,
    FRAME_ID_LAST,
    FRAME_ID_MID,
    FRAME_SIZE,
    RESOLUTION_MAP,
    CameraImageD6Assembler,
    build_request_frame,
)
from module_payload.collectors.plugins.base import (
    FilterResult,
    SerialPluginContext,
    TickResult,
)
from module_payload.collectors.redis_sync import dumps_json
from module_payload.constants import ASSEMBLER_CAMERA_IMAGE_D6
from module_payload.framing import FixedHeaderLenFrameBuffer
from module_payload.service.payload_error_store import push_pipeline_error

PLUGIN_ID_CAMERA_IMAGE = 'camera_image'
FRAME_FAIL_RETRY = 5
FRAME_TIMEOUT_S = 3.0
CTRL_POLL_INTERVAL_S = 0.1
INTER_IMAGE_SLEEP_S = 0.05
FAIL_SLEEP_S = 0.2
IO_LOG_HEAD_FRAMES = 4
IO_LOG_EVERY_N = 16


class CameraImageSerialPlugin:
    plugin_id = PLUGIN_ID_CAMERA_IMAGE

    def __init__(self) -> None:
        self._enabled = False
        self._once = False
        self._need_clear = False
        self._cfg: dict[str, Any] = {
            'resolution': '400×400',
            'image_no': 1,
        }
        self._io_seq = 0
        self._last_ctrl_poll = 0.0
        self._frame_idx = 0
        self._pending_io: list[tuple[str, bytes, str]] = []
        self._rx_frames = FixedHeaderLenFrameBuffer(FRAME_HEADER, FRAME_SIZE)
        self._assembler = CameraImageD6Assembler()

    def on_attach(self, ctx: SerialPluginContext) -> None:
        cfg = ctx.config or {}
        if cfg.get('resolution'):
            self._cfg['resolution'] = cfg['resolution']
        if cfg.get('image_no') is not None:
            self._cfg['image_no'] = int(cfg['image_no'])
        self._enabled = False
        self._once = False
        self._need_clear = False
        self._io_seq = 0
        self._frame_idx = 0
        self._last_ctrl_poll = 0.0
        self._pending_io = []
        self._rx_frames.clear()
        self._assembler.reset()

    def on_detach(self) -> None:
        self._enabled = False
        self._once = False
        self._need_clear = True
        self._pending_io = []
        self._rx_frames.clear()
        self._assembler.reset()

    def handle_control(self, msg: dict[str, Any]) -> bool:
        op = msg.get('op')
        if op == 'camera_start':
            cfg = msg.get('config') or {}
            if cfg.get('resolution'):
                self._cfg['resolution'] = cfg['resolution']
            if cfg.get('image_no') is not None:
                self._cfg['image_no'] = int(cfg['image_no'])
            self._once = bool(cfg.get('once', False))
            self._need_clear = False
            self._enabled = True
            self._io_seq = 0
            self._frame_idx = 0
            self._pending_io = []
            self._rx_frames.clear()
            self._assembler.reset()
            return True
        if op == 'camera_stop':
            self._enabled = False
            self._once = False
            self._need_clear = True
            self._rx_frames.clear()
            self._assembler.reset()
            return True
        return False

    def tick(self, ctx: SerialPluginContext) -> TickResult:
        if self._need_clear:
            self._need_clear = False
            self._clear_image_cache(ctx)
            self._pending_io = []
            ctx.write_status('running', '图像采集已停止')
        if not self._enabled:
            return TickResult(owns_loop=False)
        self._acquire_image_once(ctx)
        return TickResult(owns_loop=True)

    def filter_rx(self, ctx: SerialPluginContext, data: bytes) -> FilterResult:
        return FilterResult(passthrough=b'', consume=True)

    @staticmethod
    def _clear_image_cache(ctx: SerialPluginContext) -> None:
        try:
            ctx.reset_input_buffer()
        except Exception:
            pass
        try:
            ctx.redis.delete(
                f'{rk.PREFIX}:{ctx.device_id}:image:meta',
                f'{rk.PREFIX}:{ctx.device_id}:image:data',
            )
        except Exception:
            pass

    def _maybe_poll_control(self, ctx: SerialPluginContext) -> None:
        now = time.monotonic()
        if now - self._last_ctrl_poll < CTRL_POLL_INTERVAL_S:
            return
        self._last_ctrl_poll = now
        if callable(ctx.poll_control):
            ctx.poll_control()

    def _note_io(self, direction: str, data: bytes) -> None:
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        self._pending_io.append((direction, data, ts))

    def _flush_pending_io(self, ctx: SerialPluginContext) -> None:
        """批量落盘改为走 push_io，以便双写 source:{source}:io。"""
        pending = self._pending_io
        self._pending_io = []
        if not pending:
            return
        for direction, data, _ts in pending:
            try:
                ctx.push_io(direction, data)
            except Exception:
                pass

    def _recv_response(self, ctx: SerialPluginContext, timeout_s: float = FRAME_TIMEOUT_S) -> bytes | None:
        """阻塞读串口 → FixedHeaderLenFrameBuffer 吐出一帧完整应答。"""
        frames = self._rx_frames
        frames.clear()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline and ctx.is_running() and self._enabled:
            pending = frames.pending
            if pending >= 2:
                need = max(1, FRAME_SIZE - pending)
            else:
                need = FRAME_SIZE
            chunk = ctx.read_serial(need)
            if chunk:
                frames.write(chunk)
                frame = frames.read_frame()
                if frame is not None:
                    return frame
            elif not ctx.is_running() or not self._enabled:
                return None
        return None

    def _pull_one_frame(
        self,
        ctx: SerialPluginContext,
        frame_id: int,
        seq: int,
        image_no: int,
        *,
        log_force: bool = False,
        clear_rx: bool = False,
    ) -> AssembledPayload | bool | None:
        """请求并喂给组装器。

        返回:
          AssembledPayload — 整图完成
          True — 本帧已拼入，整图未完成
          None — 重试耗尽
        """
        for attempt in range(FRAME_FAIL_RETRY):
            if not self._enabled or not ctx.is_running():
                return None
            if clear_rx or attempt > 0:
                try:
                    ctx.reset_input_buffer()
                except Exception:
                    pass
                self._rx_frames.clear()
            req = build_request_frame(frame_id, seq, image_no)
            ctx.write_serial(req)
            self._frame_idx += 1
            do_log = (
                log_force
                or self._frame_idx <= IO_LOG_HEAD_FRAMES
                or (self._frame_idx % IO_LOG_EVERY_N) == 0
            )
            if do_log:
                self._note_io('send', req)
            resp = self._recv_response(ctx)
            if resp is None:
                continue
            if do_log:
                self._note_io('recv', resp)

            done = self._assembler.accept_frame(resp)
            errs = self._assembler.take_errors()
            if done is not None:
                return done
            if errs:
                # 校验/格式错误可重试；序号等硬错误放弃本帧请求
                soft = all(('校验' in e or '格式' in e) for e in errs)
                if soft:
                    continue
                for e in errs:
                    push_pipeline_error(
                        ctx.redis,
                        stage='camera',
                        message=e,
                        device_id=ctx.device_id,
                        assembler_id=ASSEMBLER_CAMERA_IMAGE_D6,
                    )
                return None
            return True
        return None

    def _set_image_phase(self, ctx: SerialPluginContext, phase: str, message: str, extra: dict[str, Any] | None = None) -> None:
        payload = {
            'phase': phase,
            'message': message,
            'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        if extra:
            payload.update(extra)
        try:
            ctx.redis.set(f'{rk.PREFIX}:{ctx.device_id}:image:meta', dumps_json(payload))
        except Exception:
            pass

    def _fail(self, ctx: SerialPluginContext, message: str) -> None:
        if not self._enabled:
            return
        self._flush_pending_io(ctx)
        self._assembler.reset()
        # 串口仍开着，设备 state 保持 running，避免前端误判断连
        ctx.write_status('running', message)
        push_pipeline_error(
            ctx.redis,
            stage='camera',
            message=message,
            device_id=ctx.device_id,
            assembler_id=ASSEMBLER_CAMERA_IMAGE_D6,
        )
        if self._once:
            self._set_image_phase(ctx, 'failed', message)
            self._enabled = False
            self._once = False
            return
        time.sleep(FAIL_SLEEP_S)

    def _store_image(self, ctx: SerialPluginContext, item: AssembledPayload) -> None:
        meta = dict(item.meta or {})
        width = int(meta.get('width') or 0)
        height = int(meta.get('height') or 0)
        pixels = item.data or b''
        if width <= 0 or height <= 0 or not pixels:
            return
        need = width * height
        try:
            from PIL import Image
            import io

            img = Image.frombytes('L', (width, height), pixels[:need])
            buf = io.BytesIO()
            img.save(buf, format='PNG', compress_level=1)
            b64 = base64.b64encode(buf.getvalue()).decode('ascii')
            fmt = 'png'
        except Exception:
            b64 = base64.b64encode(pixels[:need]).decode('ascii')
            fmt = 'raw'

        out_meta = {
            'width': width,
            'height': height,
            'imageNo': meta.get('imageNo'),
            'frameCount': meta.get('frameCount'),
            'format': fmt,
            'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
            'assemblerId': meta.get('assemblerId') or ASSEMBLER_CAMERA_IMAGE_D6,
            'pluginId': PLUGIN_ID_CAMERA_IMAGE,
            'phase': 'ready',
            'message': f'图像就绪 {width}x{height}',
        }
        ctx.redis.set(f'{rk.PREFIX}:{ctx.device_id}:image:meta', dumps_json(out_meta))
        ctx.redis.set(f'{rk.PREFIX}:{ctx.device_id}:image:data', b64)
        ctx.write_status('running', f'图像就绪 {width}x{height}')

    def _acquire_image_once(self, ctx: SerialPluginContext) -> None:
        res_key = self._cfg.get('resolution', '400×400')
        width, height = RESOLUTION_MAP.get(res_key, (400, 400))
        image_no = max(1, min(64, int(self._cfg.get('image_no', 1))))
        total_pixels = width * height
        total_frames = total_pixels // DATA_CHUNK_SIZE
        mid_count = max(0, total_frames - 2)

        self._io_seq = 0
        self._frame_idx = 0
        self._pending_io = []
        self._last_ctrl_poll = 0.0
        self._assembler.reset()
        self._assembler.set_resolution(res_key)
        t_acquire0 = time.perf_counter()
        ctx.write_status('running', f'正在采集图像 {width}x{height} no={image_no}')
        self._set_image_phase(ctx, 'acquiring', f'正在采集图像 {width}x{height} no={image_no}')

        result = self._pull_one_frame(
            ctx, FRAME_ID_FIRST, 0, image_no, log_force=True, clear_rx=True
        )
        if not self._enabled:
            self._clear_image_cache(ctx)
            self._pending_io = []
            return
        if result is None:
            self._fail(ctx, '图像采集失败(首帧)')
            return
        if isinstance(result, AssembledPayload):
            self._finish_image(ctx, result, t_acquire0)
            return

        for i in range(mid_count):
            if not self._enabled:
                self._clear_image_cache(ctx)
                self._pending_io = []
                return
            if (i & 0x1F) == 0:
                self._maybe_poll_control(ctx)
                if not self._enabled:
                    self._clear_image_cache(ctx)
                    self._pending_io = []
                    return
            result = self._pull_one_frame(ctx, FRAME_ID_MID, i + 1, image_no)
            if not self._enabled:
                self._clear_image_cache(ctx)
                self._pending_io = []
                return
            if result is None:
                self._fail(ctx, f'图像采集失败(中间帧{i + 1})')
                return
            if isinstance(result, AssembledPayload):
                self._finish_image(ctx, result, t_acquire0)
                return

        last_seq = mid_count + 1
        if not self._enabled:
            self._clear_image_cache(ctx)
            self._pending_io = []
            return
        result = self._pull_one_frame(
            ctx, FRAME_ID_LAST, last_seq, image_no, log_force=True
        )
        if not self._enabled:
            self._clear_image_cache(ctx)
            self._pending_io = []
            return
        if not isinstance(result, AssembledPayload):
            self._fail(ctx, '图像采集失败(尾帧)')
            return
        self._finish_image(ctx, result, t_acquire0)

    def _finish_image(
        self,
        ctx: SerialPluginContext,
        item: AssembledPayload,
        t0: float,
    ) -> None:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        n_frames = max(1, self._frame_idx)
        avg_ms = elapsed_ms / n_frames
        meta = item.meta or {}
        w = meta.get('width')
        h = meta.get('height')
        summary = (
            f'图像采集完成 {w}x{h} frames={n_frames} '
            f'total={elapsed_ms:.1f}ms avg={avg_ms:.2f}ms/frame '
            f'(IO日志前{IO_LOG_HEAD_FRAMES}帧连续+每{IO_LOG_EVERY_N}帧抽样)'
        ).encode('utf-8', errors='replace')
        self._note_io('recv', summary)
        self._flush_pending_io(ctx)
        if not self._enabled:
            self._clear_image_cache(ctx)
            return
        self._store_image(ctx, item)
        if self._once:
            # 单次模式：整图就绪后停止，不进入下一轮（不由 stop 清图）
            self._enabled = False
            self._once = False
            ctx.write_status('running', '单次图像采集完成')
            return
        time.sleep(INTER_IMAGE_SLEEP_S)
