"""相机图像序号、插件控制面、D6 组帧与 Redis 元数据。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from module_payload.assemblers.base import AssembledPayload
from module_payload.assemblers.camera_image_d6 import (
    DATA_CHUNK_SIZE,
    FRAME_ID_FIRST,
    FRAME_ID_LAST,
    FRAME_ID_MID,
    FRAME_SIZE,
    CameraImageD6Assembler,
    build_request_frame,
    calc_checksum,
    parse_response_frame,
    resolve_wh,
)
from module_payload.collectors.plugins.base import SerialPluginContext
from module_payload.collectors.plugins.camera_image import CameraImageSerialPlugin
from module_payload.collectors.plugins.registry import (
    PLUGIN_ID_CAMERA_IMAGE,
    create_serial_plugin,
    list_serial_plugins,
    resolve_plugin_id_for_source,
)
from module_payload.constants import ASSEMBLER_CAMERA_IMAGE_D6
from module_payload.framing import FixedHeaderLenFrameBuffer


def _plugin(**cfg) -> CameraImageSerialPlugin:
    p = CameraImageSerialPlugin()
    if cfg:
        p._apply_cfg(cfg)
    return p


def _ctx(**kwargs) -> SerialPluginContext:
    return SerialPluginContext(
        device_id=kwargs.get('device_id', 'serial:COM4'),
        redis=kwargs.get('redis', MagicMock()),
        config=kwargs.get('config', {}),
        is_running=kwargs.get('is_running', lambda: True),
        read_serial=kwargs.get('read_serial', lambda n: b''),
        write_serial=kwargs.get('write_serial', lambda data: None),
        in_waiting=kwargs.get('in_waiting', lambda: 0),
        reset_input_buffer=kwargs.get('reset_input_buffer', lambda: None),
        push_io=kwargs.get('push_io', lambda *a, **k: None),
        write_status=kwargs.get('write_status', lambda *a, **k: None),
        poll_control=kwargs.get('poll_control', lambda: None),
    )


def _d6_response(frame_id: int, seq: int, image_no: int, chunk: bytes | None = None) -> bytes:
    data = chunk if chunk is not None else bytes(DATA_CHUNK_SIZE)
    if len(data) < DATA_CHUNK_SIZE:
        data = data + bytes(DATA_CHUNK_SIZE - len(data))
    data = data[:DATA_CHUNK_SIZE]
    body = bytes(
        [
            0xD6,
            frame_id & 0xFF,
            0x01,
            0x01,
            (seq >> 8) & 0xFF,
            seq & 0xFF,
            image_no & 0xFF,
        ]
    ) + data
    return bytes([0xEB, 0x90]) + body + bytes([calc_checksum(body)])


# ---- 请求图像序号 / 应答为 0 时回退 ----


def test_default_image_no_is_one() -> None:
    assert _plugin()._requested_image_no() == 1


def test_apply_cfg_accepts_snake_and_camel_image_no() -> None:
    p = _plugin()
    p._apply_cfg({'imageNo': 12})
    assert p._requested_image_no() == 12
    p._apply_cfg({'image_no': 4})
    assert p._requested_image_no() == 4
    p._apply_cfg({'resolution': '256×256'})
    assert p._cfg['resolution'] == '256×256'
    p._apply_cfg({})
    assert p._requested_image_no() == 4


def test_requested_image_no_clamps_1_to_64() -> None:
    p = _plugin()
    p._cfg['image_no'] = 0
    assert p._requested_image_no() == 1
    p._cfg['image_no'] = -3
    assert p._requested_image_no() == 1
    p._cfg['image_no'] = 99
    assert p._requested_image_no() == 64
    p._cfg['image_no'] = 64
    assert p._requested_image_no() == 64


def test_effective_image_no_falls_back_when_device_echoes_zero() -> None:
    p = _plugin(image_no=7)
    assert p._effective_image_no(0) == 7
    assert p._effective_image_no(None) == 7
    assert p._effective_image_no('') == 7
    assert p._effective_image_no('x') == 7
    assert p._effective_image_no(3) == 3
    assert p._effective_image_no(64) == 64
    assert p._effective_image_no(99) == 7
    assert p._effective_image_no(-1) == 7


def test_store_image_writes_requested_index_when_meta_is_zero() -> None:
    p = _plugin(image_no=5)
    ctx = _ctx()
    pixels = bytes(64 * 64)
    p._store_image(
        ctx,
        AssembledPayload(
            data=pixels,
            meta={
                'width': 64,
                'height': 64,
                'imageNo': 0,
                'frameCount': 16,
                'assemblerId': ASSEMBLER_CAMERA_IMAGE_D6,
            },
        ),
    )
    assert ctx.redis.set.call_count == 2
    meta_key, meta_raw = ctx.redis.set.call_args_list[0][0]
    assert meta_key.endswith(':image:meta')
    meta = json.loads(meta_raw)
    assert meta['imageNo'] == 5
    assert meta['width'] == 64
    assert meta['height'] == 64
    assert meta['phase'] == 'ready'


def test_store_image_keeps_valid_device_echo() -> None:
    p = _plugin(image_no=5)
    ctx = _ctx()
    p._store_image(
        ctx,
        AssembledPayload(
            data=bytes(64 * 64),
            meta={'width': 64, 'height': 64, 'imageNo': 8},
        ),
    )
    meta = json.loads(ctx.redis.set.call_args_list[0][0][1])
    assert meta['imageNo'] == 8


def test_store_image_skips_invalid_geometry() -> None:
    p = _plugin()
    ctx = _ctx()
    p._store_image(ctx, AssembledPayload(data=b'', meta={'width': 0, 'height': 64}))
    ctx.redis.set.assert_not_called()


# ---- 插件生命周期 ----


def test_camera_start_stop_control() -> None:
    p = _plugin()
    assert p.handle_control({'op': 'noop'}) is False
    ok = p.handle_control(
        {'op': 'camera_start', 'config': {'image_no': 9, 'resolution': '128×128', 'once': True}}
    )
    assert ok is True
    assert p._enabled is True
    assert p._once is True
    assert p._requested_image_no() == 9
    assert p._cfg['resolution'] == '128×128'
    assert p.handle_control({'op': 'camera_stop'}) is True
    assert p._enabled is False
    assert p._need_clear is True


def test_flush_pending_io_only_push_io() -> None:
    p = _plugin()
    p._pending_io = [('recv', b'\x01', 'ts'), ('send', b'\x02', 'ts')]
    push = MagicMock()
    p._flush_pending_io(_ctx(push_io=push))
    assert push.call_count == 2
    push.assert_any_call('recv', b'\x01')
    push.assert_any_call('send', b'\x02')
    assert p._pending_io == []


def test_tick_disabled_does_not_own_loop() -> None:
    p = _plugin()
    r = p.tick(_ctx())
    assert r.owns_loop is False


def test_filter_rx_consumes_all() -> None:
    r = _plugin().filter_rx(_ctx(), b'\x01\x02')
    assert r.consume is True
    assert r.passthrough == b''


def test_reset_rx_clears_frame_buffer_and_assembler() -> None:
    p = _plugin()
    p._rx_frames.write(b'\xEB\x90\x00')
    p._assembler._image_no = 3
    p.reset_rx()
    assert p._rx_frames.pending == 0
    assert p._assembler._image_no is None


def test_on_attach_applies_config_but_stays_idle() -> None:
    p = _plugin()
    p._enabled = True
    p.on_attach(_ctx(config={'image_no': 11, 'resolution': '64×64'}))
    assert p._enabled is False
    assert p._requested_image_no() == 11


def test_on_detach_marks_need_clear() -> None:
    p = _plugin()
    p._enabled = True
    p.on_detach()
    assert p._enabled is False
    assert p._need_clear is True


def test_registry_source_and_factory() -> None:
    assert resolve_plugin_id_for_source('camera_image') == PLUGIN_ID_CAMERA_IMAGE
    assert resolve_plugin_id_for_source('camera_ctrl') is None
    assert resolve_plugin_id_for_source('') is None
    plugin = create_serial_plugin(PLUGIN_ID_CAMERA_IMAGE)
    assert isinstance(plugin, CameraImageSerialPlugin)
    assert create_serial_plugin('nope') is None
    assert create_serial_plugin(None) is None
    ids = {x['id'] for x in list_serial_plugins()}
    assert PLUGIN_ID_CAMERA_IMAGE in ids


# ---- D6 协议 / 组装器 ----


def test_build_request_puts_image_no_at_byte_8() -> None:
    raw = build_request_frame(FRAME_ID_FIRST, 0, 7)
    assert raw[0:2] == b'\xEB\x90'
    assert raw[2] == 0xD6
    assert raw[8] == 7
    assert raw[9] == calc_checksum(raw[2:9])
    assert len(raw) == 10


def test_parse_response_roundtrip() -> None:
    chunk = bytes(range(256))
    raw = _d6_response(FRAME_ID_MID, 12, 7, chunk)
    assert len(raw) == FRAME_SIZE
    parsed = parse_response_frame(raw)
    assert parsed is not None
    frame_id, seq, image_no, data = parsed
    assert frame_id == FRAME_ID_MID
    assert seq == 12
    assert image_no == 7
    assert data == chunk


def test_parse_response_rejects_bad_checksum_and_short() -> None:
    raw = bytearray(_d6_response(FRAME_ID_FIRST, 0, 1))
    raw[-1] ^= 0xFF
    assert parse_response_frame(bytes(raw)) is None
    assert parse_response_frame(b'\xEB\x90') is None
    bad_hdr = bytes([0x00, 0x00]) + _d6_response(FRAME_ID_FIRST, 0, 1)[2:]
    assert parse_response_frame(bad_hdr) is None


def test_assembler_meta_image_no_from_frames_even_if_zero() -> None:
    """组帧层忠实记录应答字段；0 的回退在插件存 Redis 时做。"""
    asm = CameraImageD6Assembler()
    asm.set_resolution('64×64')
    total = 64 * 64
    n_frames = total // DATA_CHUNK_SIZE
    for seq in range(n_frames):
        fid = FRAME_ID_FIRST if seq == 0 else (FRAME_ID_LAST if seq == n_frames - 1 else FRAME_ID_MID)
        done = asm.accept_frame(_d6_response(fid, seq, 0, bytes([seq & 0xFF]) * DATA_CHUNK_SIZE))
        if seq < n_frames - 1:
            assert done is None
        else:
            assert done is not None
            assert done.meta['imageNo'] == 0
            assert done.meta['width'] == 64
            assert done.meta['height'] == 64
            assert len(done.data) == total


def test_assembler_drops_on_image_no_change() -> None:
    asm = CameraImageD6Assembler()
    assert asm.accept_frame(_d6_response(FRAME_ID_FIRST, 0, 1)) is None
    assert asm.accept_frame(_d6_response(FRAME_ID_MID, 1, 2)) is None
    assert any('图像序号变化' in e for e in asm.take_errors())


def test_resolve_wh_uses_hint_when_pixel_count_matches() -> None:
    assert resolve_wh(256 * 256, '256×256') == (256, 256)
    assert resolve_wh(256 * 256, '400×400') == (256, 256)
    assert resolve_wh(100, None) == (0, 0)


def test_fixed_header_buffer_clear() -> None:
    buf = FixedHeaderLenFrameBuffer(b'\xEB\x90', FRAME_SIZE)
    buf.write(b'\xEB\x90\x00\x01')
    assert buf.pending == 4
    buf.clear()
    assert buf.pending == 0
