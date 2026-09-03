"""内联收发数据：v1.6 / v1.7 图像组帧与跨版本拒收（64×64）。

十六进制对已固化在 ``camera_image_capture_data``，不读外部 txt。
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from camera_image_capture_data import (
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    V16_IMAGE_PNG_B64,
    V16_PAIRS,
    V17_IMAGE_PNG_B64,
    V17_PAIRS,
)
from module_payload import redis_keys as rk
from module_payload.assemblers.base import AssembledPayload
from module_payload.assemblers.camera_image_d6 import (
    FRAME_HEADER,
    FRAME_SIZE,
    CameraImageD6Assembler,
    calc_checksum,
    frame_id_is_first,
    frame_id_is_last,
    parse_response_frame,
    plan_d6_image_requests,
)
from module_payload.assemblers.camera_image_d6_v17 import (
    CameraImageD6V17Assembler,
    parse_response_frame_v17,
)
from module_payload.collectors.plugins.base import SerialPluginContext
from module_payload.collectors.plugins.camera_image import CameraImageSerialPlugin
from module_payload.constants import ASSEMBLER_CAMERA_IMAGE_D6, ASSEMBLER_CAMERA_IMAGE_D6_V17
from module_payload.framing import FixedHeaderLenFrameBuffer
from module_payload.service.payload_camera_service import PayloadCameraService

_IMAGE_SIDE = IMAGE_WIDTH
_IMAGE_PIXELS = IMAGE_WIDTH * IMAGE_HEIGHT
_FRAME_COUNT = 16  # 4096 / 256
_TEST_PORT = 'COM64'


def _hex_to_bytes(text: str) -> bytes:
    return bytes(int(x, 16) for x in text.split())


def _events_from_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, bytes]]:
    return [(kind, _hex_to_bytes(hex_text)) for kind, hex_text in pairs]


def _sends_recvs(events: list[tuple[str, bytes]]) -> tuple[list[bytes], list[bytes]]:
    sends = [b for k, b in events if k == 'Send']
    recvs = [b for k, b in events if k == 'Recv']
    return sends, recvs


def _seq(frame: bytes) -> int:
    return (frame[6] << 8) | frame[7]


def _assemble_image(
    events: list[tuple[str, bytes]],
    assembler: CameraImageD6Assembler | CameraImageD6V17Assembler,
    resolution: str,
) -> AssembledPayload:
    _, recvs = _sends_recvs(events)
    assembler.set_resolution(resolution)
    assembler.set_expected_final_seq(len(recvs) - 1)
    done = None
    for raw in recvs:
        done = assembler.accept_frame(raw)
        assert assembler.take_errors() == []
    assert done is not None
    assert len(done.data) == _IMAGE_PIXELS
    return done


def _plugin_ctx(redis: Any, device_id: str) -> SerialPluginContext:
    return SerialPluginContext(
        device_id=device_id,
        redis=redis,
        config={},
        is_running=lambda: True,
        read_serial=lambda n: b'',
        write_serial=lambda data: None,
        in_waiting=lambda: 0,
        reset_input_buffer=lambda: None,
        push_io=lambda *a, **k: None,
        write_status=lambda *a, **k: None,
        poll_control=lambda: None,
    )


def _store_then_get_image_api(item: AssembledPayload, assembler_id: str) -> dict[str, Any]:
    """走插件写 Redis 图像缓存，再经 ``PayloadCameraService.get_image`` 读回。"""
    device_id = rk.serial_id(_TEST_PORT)
    store: dict[str, Any] = {}
    sync_redis = MagicMock()
    sync_redis.set.side_effect = lambda key, value: store.__setitem__(key, value)

    plugin = CameraImageSerialPlugin()
    plugin._assembler_id = assembler_id
    plugin._store_image(_plugin_ctx(sync_redis, device_id), item)

    assert f'{rk.PREFIX}:{device_id}:image:data' in store
    assert f'{rk.PREFIX}:{device_id}:image:meta' in store

    aredis = AsyncMock()

    async def _aget(key: str):
        return store.get(key)

    aredis.get = _aget
    return asyncio.run(PayloadCameraService.get_image(aredis, _TEST_PORT))


@pytest.fixture(scope='module')
def v16_events() -> list[tuple[str, bytes]]:
    events = _events_from_pairs(V16_PAIRS)
    assert events, 'V16_PAIRS 为空'
    return events


@pytest.fixture(scope='module')
def v17_events() -> list[tuple[str, bytes]]:
    events = _events_from_pairs(V17_PAIRS)
    assert events, 'V17_PAIRS 为空'
    return events


# ---- 用尽全部内联收发：v1.6（64×64） ----


def test_v16_capture_uses_every_send_and_recv(v16_events: list[tuple[str, bytes]]) -> None:
    sends, recvs = _sends_recvs(v16_events)
    assert len(sends) == len(recvs) == _FRAME_COUNT
    assert len(v16_events) == len(sends) + len(recvs)
    assert len(V16_PAIRS) == len(v16_events)


def test_v16_capture_all_pairs_checksum_and_seq(v16_events: list[tuple[str, bytes]]) -> None:
    sends, recvs = _sends_recvs(v16_events)
    for i, (req, resp) in enumerate(zip(sends, recvs, strict=True)):
        assert len(req) == 10, f'send[{i}] len={len(req)}'
        assert len(resp) == FRAME_SIZE, f'recv[{i}] len={len(resp)}'
        assert calc_checksum(req[2:9]) == req[9], f'send[{i}] checksum'
        assert calc_checksum(resp[2:265]) == resp[265], f'recv[{i}] checksum'
        assert _seq(req) == _seq(resp) == i, f'pair[{i}] seq mismatch'
        assert req[8] == resp[8] == 1, f'pair[{i}] image_no'
        assert resp[4:6] == bytes([0x01, 0x01]), f'recv[{i}] 非 v1.6 长度域占位'


def test_v16_capture_all_recv_accepted_by_v16_rejected_by_v17(
    v16_events: list[tuple[str, bytes]],
) -> None:
    _, recvs = _sends_recvs(v16_events)
    assert frame_id_is_first(recvs[0][3])
    assert frame_id_is_last(recvs[-1][3])

    for i, raw in enumerate(recvs):
        parsed = parse_response_frame(raw)
        assert parsed is not None, f'v16 应解析 recv[{i}]'
        assert parse_response_frame_v17(raw) is None, f'v17 应拒收 v16 recv[{i}]'

        v17 = CameraImageD6V17Assembler(resolution='64')
        assert v17.accept_frame(raw) is None
        errs = v17.take_errors()
        assert errs and any('校验' in e or '格式' in e or '长度' in e for e in errs)


def test_v16_capture_assembles_full_64x64_image(v16_events: list[tuple[str, bytes]]) -> None:
    sends, recvs = _sends_recvs(v16_events)
    plan = plan_d6_image_requests(_IMAGE_PIXELS)
    assert len(plan) == len(recvs) == _FRAME_COUNT
    assert [seq for _fid, seq in plan] == list(range(_FRAME_COUNT))

    for i, (req, (_fid, seq)) in enumerate(zip(sends, plan, strict=True)):
        assert _seq(req) == seq == i
        assert req[8] == 1
        assert req[0:3] == bytes([0xEB, 0x90, 0xD6])

    asm = CameraImageD6Assembler(resolution='64×64')
    asm.set_expected_final_seq(plan[-1][1])
    done = None
    for raw in recvs:
        done = asm.accept_frame(raw)
        assert asm.take_errors() == []
    assert done is not None
    assert done.meta.get('width') == _IMAGE_SIDE
    assert done.meta.get('height') == _IMAGE_SIDE
    assert done.meta.get('imageNo') == 1
    assert done.meta.get('frameCount') == _FRAME_COUNT
    assert len(done.data) == _IMAGE_PIXELS


def test_v16_capture_rx_stream_reframes_all(v16_events: list[tuple[str, bytes]]) -> None:
    _, recvs = _sends_recvs(v16_events)
    buf = FixedHeaderLenFrameBuffer(FRAME_HEADER, FRAME_SIZE)
    buf.write(b''.join(recvs))
    assert buf.read_frames() == recvs
    assert buf.pending == 0


# ---- 用尽全部内联收发：v1.7（64×64） ----


def test_v17_capture_uses_every_send_and_recv(v17_events: list[tuple[str, bytes]]) -> None:
    sends, recvs = _sends_recvs(v17_events)
    assert len(sends) == len(recvs) == _FRAME_COUNT
    assert len(v17_events) == len(sends) + len(recvs)
    assert len(V17_PAIRS) == len(v17_events)


def test_v17_capture_all_pairs_and_length_field(v17_events: list[tuple[str, bytes]]) -> None:
    sends, recvs = _sends_recvs(v17_events)
    for i, (req, resp) in enumerate(zip(sends, recvs, strict=True)):
        assert len(req) == 10, f'send[{i}]'
        assert len(resp) == FRAME_SIZE, f'recv[{i}]'
        assert calc_checksum(req[2:9]) == req[9]
        assert calc_checksum(resp[2:265]) == resp[265]
        assert _seq(req) == _seq(resp) == i
        assert req[8] == resp[8] == 1
        # L=0x00FF → 有效 256
        assert resp[4:6] == bytes([0x00, 0xFF]), f'recv[{i}] 非 v1.7 满包长度域'
        parsed = parse_response_frame_v17(resp)
        assert parsed is not None
        _fid, seq, _ino, chunk = parsed
        assert seq == i
        assert len(chunk) == 256


def test_v17_capture_assembles_full_64x64_image(v17_events: list[tuple[str, bytes]]) -> None:
    sends, recvs = _sends_recvs(v17_events)
    plan = plan_d6_image_requests(_IMAGE_PIXELS)
    assert len(plan) == len(recvs) == _FRAME_COUNT
    assert [seq for _fid, seq in plan] == list(range(_FRAME_COUNT))

    for i, (req, (_fid, seq)) in enumerate(zip(sends, plan, strict=True)):
        assert _seq(req) == seq == i
        assert req[8] == 1
        assert req[0:3] == bytes([0xEB, 0x90, 0xD6])

    asm = CameraImageD6V17Assembler(resolution='64')
    asm.set_expected_final_seq(plan[-1][1])
    done = None
    for raw in recvs:
        done = asm.accept_frame(raw)
        assert asm.take_errors() == []
    assert done is not None
    assert done.meta.get('width') == _IMAGE_SIDE
    assert done.meta.get('height') == _IMAGE_SIDE
    assert done.meta.get('imageNo') == 1
    assert done.meta.get('frameCount') == _FRAME_COUNT
    assert len(done.data) == _IMAGE_PIXELS
    assert frame_id_is_first(recvs[0][3])
    assert frame_id_is_last(recvs[-1][3])


def test_v17_capture_rx_stream_reframes_all(v17_events: list[tuple[str, bytes]]) -> None:
    _, recvs = _sends_recvs(v17_events)
    buf = FixedHeaderLenFrameBuffer(FRAME_HEADER, FRAME_SIZE)
    buf.write(b''.join(recvs))
    assert buf.read_frames() == recvs
    assert buf.pending == 0


# ---- API 读图 vs 预存黄金 PNG ----


def test_v16_get_image_api_matches_golden_png(v16_events: list[tuple[str, bytes]]) -> None:
    """拼图 → 插件写缓存 → get_image API，须等于预存 V16_IMAGE_PNG_B64。"""
    done = _assemble_image(
        v16_events,
        CameraImageD6Assembler(resolution='64×64'),
        '64×64',
    )
    out = _store_then_get_image_api(done, ASSEMBLER_CAMERA_IMAGE_D6)
    assert out['image']['format'] == 'png'
    assert out['image']['data'] == V16_IMAGE_PNG_B64
    assert out['image']['meta']['width'] == IMAGE_WIDTH
    assert out['image']['meta']['height'] == IMAGE_HEIGHT
    assert out['image']['meta']['phase'] == 'ready'
    # 解码 API PNG，像素应与黄金 PNG 一致
    api_pix = Image.open(io.BytesIO(base64.b64decode(out['image']['data']))).tobytes()
    gold_pix = Image.open(io.BytesIO(base64.b64decode(V16_IMAGE_PNG_B64))).tobytes()
    assert api_pix == gold_pix == done.data


def test_v17_get_image_api_matches_golden_png(v17_events: list[tuple[str, bytes]]) -> None:
    """拼图 → 插件写缓存 → get_image API，须等于预存 V17_IMAGE_PNG_B64。"""
    done = _assemble_image(
        v17_events,
        CameraImageD6V17Assembler(resolution='64'),
        '64',
    )
    out = _store_then_get_image_api(done, ASSEMBLER_CAMERA_IMAGE_D6_V17)
    assert out['image']['format'] == 'png'
    assert out['image']['data'] == V17_IMAGE_PNG_B64
    assert out['image']['meta']['width'] == IMAGE_WIDTH
    assert out['image']['meta']['height'] == IMAGE_HEIGHT
    assert out['image']['meta']['phase'] == 'ready'
    api_pix = Image.open(io.BytesIO(base64.b64decode(out['image']['data']))).tobytes()
    gold_pix = Image.open(io.BytesIO(base64.b64decode(V17_IMAGE_PNG_B64))).tobytes()
    assert api_pix == gold_pix == done.data


# ---- 页面协议与相机版本不对应 ----


def test_v16_camera_rejected_by_v17_page_assembler(v16_events: list[tuple[str, bytes]]) -> None:
    """v1.6 相机应答（长度域 01 01）不能被 v1.7 页面组装器收下。"""
    _, recvs = _sends_recvs(v16_events)
    first = recvs[0]
    v16 = CameraImageD6Assembler(resolution='64×64')
    assert v16.accept_frame(first) is None
    assert v16.take_errors() == []

    bad = CameraImageD6V17Assembler(resolution='64')
    assert bad.accept_frame(first) is None
    assert bad.take_errors()


def test_session_refresh_both_directions_keeps_page_assembler_aligned() -> None:
    """同口 already_open：v16↔v17 会话切换须换组装器（页面/相机协议对齐）。"""

    def _ctx(redis: MagicMock, config: dict) -> SerialPluginContext:
        return SerialPluginContext(
            device_id='serial:COM4',
            redis=redis,
            config=config,
            is_running=lambda: True,
            read_serial=lambda n: b'',
            write_serial=lambda data: None,
            in_waiting=lambda: 0,
            reset_input_buffer=lambda: None,
            push_io=lambda *a, **k: None,
            write_status=lambda *a, **k: None,
            poll_control=lambda: None,
        )

    p = CameraImageSerialPlugin()
    redis = MagicMock()
    redis.get.return_value = None
    p.on_attach(_ctx(redis, {'source': 'camera_image', 'assemblerId': ASSEMBLER_CAMERA_IMAGE_D6}))
    assert p._assembler_id == ASSEMBLER_CAMERA_IMAGE_D6

    redis.get.return_value = json.dumps(
        {'source': 'camera_image_v17', 'assemblerId': ASSEMBLER_CAMERA_IMAGE_D6_V17}
    )
    p.on_session_refresh(_ctx(redis, {'source': 'camera_image'}))
    assert p._assembler_id == ASSEMBLER_CAMERA_IMAGE_D6_V17

    redis.get.return_value = json.dumps(
        {'source': 'camera_image', 'assemblerId': ASSEMBLER_CAMERA_IMAGE_D6}
    )
    p.on_session_refresh(_ctx(redis, {'source': 'camera_image_v17'}))
    assert p._assembler_id == ASSEMBLER_CAMERA_IMAGE_D6


def test_serial_collector_session_changed_refreshes_same_image_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    """camera_image 与 camera_image_v17 同插件 id：session_changed 须 on_session_refresh。"""
    from module_payload.collectors.serial_collector import SerialCollector
    from module_payload.constants import SRC_KIND_SERIAL

    coll = SerialCollector.__new__(SerialCollector)
    coll.device_id = 'serial:COM9'
    coll.config = {'source': 'camera_image'}
    coll._cached_source = 'camera_image'
    coll._plugin_id = 'camera_image'
    coll._pipeline_lock = __import__('threading').RLock()
    coll._redis = MagicMock()

    plugin = MagicMock()
    plugin.on_session_refresh = MagicMock()
    coll._plugin = plugin

    monkeypatch.setattr(
        'module_payload.collectors.serial_collector.get_session_sync',
        lambda *_a, **_k: {'source': 'camera_image_v17', 'assemblerId': ASSEMBLER_CAMERA_IMAGE_D6_V17},
    )
    monkeypatch.setattr(coll, '_invalidate_session_cache', lambda: None)
    monkeypatch.setattr(coll, '_sync_xfer_logger', lambda: None)
    monkeypatch.setattr(coll, '_reset_tm_parsers', lambda: None)
    monkeypatch.setattr(
        coll,
        '_plugin_ctx',
        lambda: SerialPluginContext(
            device_id=coll.device_id,
            redis=coll._redis,
            config=coll.config,
            is_running=lambda: True,
            read_serial=lambda n: b'',
            write_serial=lambda data: None,
            in_waiting=lambda: 0,
            reset_input_buffer=lambda: None,
            push_io=lambda *a, **k: None,
            write_status=lambda *a, **k: None,
            poll_control=lambda: None,
        ),
    )

    coll.handle_control({'op': 'session_changed'})
    plugin.on_session_refresh.assert_called_once()
    assert coll._cached_source == 'camera_image_v17'
    assert SRC_KIND_SERIAL == 'serial'
