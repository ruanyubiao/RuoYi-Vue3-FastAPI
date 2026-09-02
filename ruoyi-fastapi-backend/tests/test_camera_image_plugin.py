"""相机图像序号、插件控制面、D6 组帧与 Redis 元数据。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from module_payload.assemblers.base import AssembledPayload
from module_payload.assemblers.camera_image_d6 import (
    DATA_CHUNK_SIZE,
    FRAME_SIZE,
    CameraImageD6Assembler,
    build_request_frame,
    calc_checksum,
    classify_frame_id,
    frame_id_encode,
    frame_id_is_first,
    frame_id_is_last,
    frame_id_is_mid,
    frame_id_is_valid,
    parse_response_frame,
    resolve_wh,
)
from module_payload.collectors.plugins.base import SerialPluginContext
from module_payload.collectors.plugins.camera_image import CameraImageSerialPlugin
from module_payload.collectors.plugins.registry import (
    PLUGIN_ID_CAMERA_IMAGE,
    create_serial_plugin,
    is_camera_image_source,
    list_serial_plugins,
    resolve_plugin_id_for_source,
)
from module_payload.constants import ASSEMBLER_CAMERA_IMAGE_D6, ASSEMBLER_CAMERA_IMAGE_D6_V17
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


# ---- 帧标识按位判断 / 拉图请求规划 ----


def test_plan_d6_image_requests_80x80_last_frame() -> None:
    from module_payload.assemblers.camera_image_d6 import plan_d6_image_requests

    plan = plan_d6_image_requests(80 * 80)
    assert len(plan) == 25
    assert plan[0] == (frame_id_encode(first=True), 0)
    assert plan[-1] == (frame_id_encode(last=True), 24)
    assert frame_id_is_mid(plan[-2][0])
    assert plan[-2][1] == 23
    assert all(frame_id_is_mid(fid) for fid, seq in plan[1:-1])


def test_plan_d6_image_requests_400x400_is_625_frames() -> None:
    from module_payload.assemblers.camera_image_d6 import plan_d6_image_requests

    plan = plan_d6_image_requests(400 * 400)
    assert len(plan) == 625
    assert plan[0] == (frame_id_encode(first=True), 0)
    assert plan[-1] == (frame_id_encode(last=True), 624)


def test_resolve_wh_400_is_square() -> None:
    assert CameraImageSerialPlugin._resolve_wh('400') == (400, 400)


def test_plan_d6_image_requests_uses_ceil_for_partial_tail() -> None:
    from module_payload.assemblers.camera_image_d6 import plan_d6_image_requests

    plan = plan_d6_image_requests(256 * 25 + 1)
    assert len(plan) == 26
    assert plan[-1] == (frame_id_encode(last=True), 25)


def test_plan_d6_image_requests_8x8_is_single_first_last_frame() -> None:
    from module_payload.assemblers.camera_image_d6 import plan_d6_image_requests

    plan = plan_d6_image_requests(8 * 8)
    assert plan == [(frame_id_encode(first=True, last=True), 0)]
    assert frame_id_is_first(plan[0][0])
    assert frame_id_is_last(plan[0][0])


def test_plan_d6_image_requests_16x16_is_single_first_last_frame() -> None:
    from module_payload.assemblers.camera_image_d6 import plan_d6_image_requests

    plan = plan_d6_image_requests(16 * 16)
    assert len(plan) == 1
    assert plan[0] == (frame_id_encode(first=True, last=True), 0)


def test_acquire_image_once_sends_last_frame_for_80x80() -> None:
    from module_payload.assemblers.camera_image_d6 import build_request_frame, frame_id_is_last
    from module_payload.assemblers.camera_image_d6_v17 import CameraImageD6V17Assembler
    from module_payload.constants import ASSEMBLER_CAMERA_IMAGE_D6_V17

    sent: list[bytes] = []

    def write_serial(data: bytes) -> None:
        sent.append(bytes(data))

    p = _plugin()
    p._session_cfg = {'assemblerId': ASSEMBLER_CAMERA_IMAGE_D6_V17}
    p._assembler_id = ASSEMBLER_CAMERA_IMAGE_D6_V17
    p._assembler = CameraImageD6V17Assembler(resolution='80')
    p._enabled = True
    p._cfg['resolution'] = '80'
    p.handle_control({'op': 'camera_start', 'config': {'resolution': '80', 'once': True}})
    p._assembler.set_expected_final_seq(24)

    def fake_pull(ctx, frame_id, seq, image_no, **kwargs):
        sent.append(build_request_frame(frame_id, seq, image_no))
        if frame_id_is_last(frame_id):
            return AssembledPayload(
                data=bytes(80 * 80),
                meta={'width': 80, 'height': 80, 'imageNo': image_no},
            )
        return True

    p._pull_one_frame = fake_pull  # type: ignore[method-assign]
    p._finish_image = MagicMock()  # type: ignore[method-assign]
    p._acquire_image_once(_ctx(write_serial=write_serial))

    assert len(sent) == 25
    last_req = sent[-1]
    assert last_req[3] == frame_id_encode(last=True)
    assert last_req[6:8] == bytes([(24 >> 8) & 0xFF, 24 & 0xFF])


def test_assembler_ignores_premature_response_last_bit() -> None:
    """应答在规划最后一包之前置尾帧位时，不提前收束。"""
    asm = CameraImageD6Assembler(resolution='64×64')
    asm.set_resolution('64×64')
    last_seq = 64 * 64 // DATA_CHUNK_SIZE - 1
    asm.set_expected_final_seq(last_seq)
    for seq in range(last_seq - 1):
        fid = frame_id_encode(first=True) if seq == 0 else frame_id_encode(mid=True)
        assert asm.accept_frame(_d6_response(fid, seq, 1, bytes([seq & 0xFF]) * DATA_CHUNK_SIZE)) is None
    early_last = frame_id_encode(last=True) | frame_id_encode(mid=True)
    assert asm.accept_frame(_d6_response(early_last, last_seq - 1, 1)) is None
    done = asm.accept_frame(
        _d6_response(frame_id_encode(last=True), last_seq, 1, bytes([0xFF]) * DATA_CHUNK_SIZE)
    )
    assert done is not None
    assert done.meta['width'] == 64


def test_frame_id_bit_flags() -> None:
    fid_first = frame_id_encode(first=True)
    fid_mid = frame_id_encode(mid=True)
    fid_last = frame_id_encode(last=True)
    assert frame_id_is_first(fid_first)
    assert not frame_id_is_last(fid_first)
    assert not frame_id_is_mid(fid_first)
    assert frame_id_is_mid(fid_mid)
    assert frame_id_is_last(fid_last)
    assert classify_frame_id(fid_first) == 'first'
    assert classify_frame_id(fid_mid) == 'mid'
    assert classify_frame_id(fid_last) == 'last'
    # 首+尾同帧（bit2+bit0）
    combined = 0x05
    assert frame_id_is_first(combined)
    assert frame_id_is_last(combined)
    assert classify_frame_id(combined) == 'first'
    assert frame_id_is_valid(combined)


def test_assembler_starts_when_first_bit_set() -> None:
    """首帧位为 1 即可开始（不必整字节等于 0x04）。"""
    asm = CameraImageD6Assembler(resolution='400×400')
    # 0x06 = bit2+bit1，含首帧位、非尾帧
    assert asm.accept_frame(_d6_response(0x06, 0, 1)) is None
    assert not any('非首帧开始' in e for e in asm.last_errors)


# ---- 请求图像序号 / 应答为 0 时回退 ----


def test_resolve_wh_numeric_side_is_square() -> None:
    """v1.7 传 ``80`` 时不得回落到 400×400。"""
    resolve = CameraImageSerialPlugin._resolve_wh
    assert resolve('80', ASSEMBLER_CAMERA_IMAGE_D6) == (80, 80)
    assert resolve('80', ASSEMBLER_CAMERA_IMAGE_D6_V17) == (80, 80)
    assert resolve('80×80', ASSEMBLER_CAMERA_IMAGE_D6) == (80, 80)
    assert resolve('400×400', ASSEMBLER_CAMERA_IMAGE_D6) == (400, 400)


def test_bind_assembler_from_v17_source() -> None:
    p = CameraImageSerialPlugin()
    p._bind_assembler({'source': 'camera_image_v17'})
    assert p._assembler_id == ASSEMBLER_CAMERA_IMAGE_D6_V17


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
    push.assert_any_call('recv', b'\x01', to_file=False, throttle=False)
    push.assert_any_call('send', b'\x02', to_file=False, throttle=False)
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
    assert is_camera_image_source('camera_image') is True
    assert is_camera_image_source('camera_image_v17') is True
    assert is_camera_image_source('camera_ctrl') is False
    assert resolve_plugin_id_for_source('camera_image') == PLUGIN_ID_CAMERA_IMAGE
    assert resolve_plugin_id_for_source('camera_image_v17') == PLUGIN_ID_CAMERA_IMAGE
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
    raw = build_request_frame(frame_id_encode(first=True), 0, 7)
    assert raw[0:2] == b'\xEB\x90'
    assert raw[2] == 0xD6
    assert raw[8] == 7
    assert raw[9] == calc_checksum(raw[2:9])
    assert len(raw) == 10


def test_parse_response_roundtrip() -> None:
    chunk = bytes(range(256))
    raw = _d6_response(frame_id_encode(mid=True), 12, 7, chunk)
    assert len(raw) == FRAME_SIZE
    parsed = parse_response_frame(raw)
    assert parsed is not None
    frame_id, seq, image_no, data = parsed
    assert frame_id == frame_id_encode(mid=True)
    assert seq == 12
    assert image_no == 7
    assert data == chunk


def test_parse_response_rejects_bad_checksum_and_short() -> None:
    raw = bytearray(_d6_response(frame_id_encode(first=True), 0, 1))
    raw[-1] ^= 0xFF
    assert parse_response_frame(bytes(raw)) is None
    assert parse_response_frame(b'\xEB\x90') is None
    bad_hdr = bytes([0x00, 0x00]) + _d6_response(frame_id_encode(first=True), 0, 1)[2:]
    assert parse_response_frame(bad_hdr) is None


def test_assembler_meta_image_no_from_frames_even_if_zero() -> None:
    """组帧层忠实记录应答字段；0 的回退在插件存 Redis 时做。"""
    asm = CameraImageD6Assembler()
    asm.set_resolution('64×64')
    total = 64 * 64
    n_frames = total // DATA_CHUNK_SIZE
    for seq in range(n_frames):
        fid = (
            frame_id_encode(first=True)
            if seq == 0
            else (frame_id_encode(last=True) if seq == n_frames - 1 else frame_id_encode(mid=True))
        )
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
    assert asm.accept_frame(_d6_response(frame_id_encode(first=True), 0, 1)) is None
    assert asm.accept_frame(_d6_response(frame_id_encode(mid=True), 1, 2)) is None
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
