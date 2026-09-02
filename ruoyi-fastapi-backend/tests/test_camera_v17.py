"""相机 V1.7 协议：图像组装器与 pipeline 注册。"""

from __future__ import annotations

from module_payload.assemblers.camera_image_d6_v17 import (
    CameraImageD6V17Assembler,
    parse_response_frame_v17,
    parse_valid_len_field,
    resolve_wh_v17,
)
from module_payload.assemblers.camera_image_d6 import frame_id_encode
from module_payload.assemblers.camera_image_d6 import FRAME_HEADER, FRAME_TYPE, FRAME_SIZE, calc_checksum
from module_payload.constants import (
    ASSEMBLER_CAMERA_IMAGE_D6_V17,
    PARSER_TM_XL_CAMERA_V17,
)
from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, cfg_id_for_camera
from module_payload.parsers import list_parsers, resolve_parser
from module_payload.parsers.xl_camera_tm_v17 import XlCameraTmV17Ingest, CFG_TABLE_D8
from module_payload.assemblers import create_assembler, list_assemblers


def test_parse_valid_len_field() -> None:
    prefix = bytes(4)
    assert parse_valid_len_field(prefix + bytes([0x00, 0x00])) == 1
    assert parse_valid_len_field(prefix + bytes([0x00, 0xFF])) == 256


def test_resolve_wh_v17_square() -> None:
    assert resolve_wh_v17(160000, '400') == (400, 400)
    assert resolve_wh_v17(65536, '256×256') == (256, 256)


def test_v17_assembler_accepts_variable_chunk() -> None:
    asm = CameraImageD6V17Assembler(resolution='64')
    asm.set_resolution('64')
    n = 64
    total = n * n
    frames = total // 256
    for seq in range(frames):
        if seq == 0:
            fid = frame_id_encode(first=True)
        elif seq == frames - 1:
            fid = frame_id_encode(last=True)
        else:
            fid = frame_id_encode(mid=True)
        valid = 256 if seq < frames - 1 else total - seq * 256
        chunk = bytes([seq & 0xFF]) * valid
        raw = _fake_response(fid, seq, 1, valid, chunk)
        done = asm.accept_frame(raw)
        if seq < frames - 1:
            assert done is None
        else:
            assert done is not None
            assert done.meta.get('width') == n
            assert len(done.data) == total


def test_v17_assembler_accepts_8x8_single_frame() -> None:
    from module_payload.assemblers.camera_image_d6 import plan_d6_image_requests

    asm = CameraImageD6V17Assembler(resolution='8')
    n = 8
    total = n * n
    plan = plan_d6_image_requests(total)
    assert len(plan) == 1
    fid, seq = plan[0]
    asm.set_expected_final_seq(seq)
    chunk = bytes(range(total))
    done = asm.accept_frame(_fake_response(fid, seq, 1, total, chunk))
    assert done is not None
    assert done.meta.get('width') == n
    assert len(done.data) == total


def _fake_response(frame_id: int, seq: int, image_no: int, valid: int, chunk: bytes) -> bytes:
    from module_payload.assemblers.camera_image_d6 import FRAME_HEADER, FRAME_TYPE, FRAME_SIZE, calc_checksum

    l = (valid - 1) & 0xFFFF
    padded = chunk[:valid] + bytes(256 - valid)
    body = bytes(
        [
            FRAME_TYPE,
            frame_id & 0xFF,
            (l >> 8) & 0xFF,
            l & 0xFF,
            (seq >> 8) & 0xFF,
            seq & 0xFF,
            image_no & 0xFF,
        ]
    ) + padded
    return FRAME_HEADER + body + bytes([calc_checksum(body)])


def test_pipeline_registry_includes_v17() -> None:
    parser_ids = {p['id'] for p in list_parsers()}
    assert PARSER_TM_XL_CAMERA_V17 in parser_ids
    assert resolve_parser(PARSER_TM_XL_CAMERA_V17) is not None
    asm_ids = {a['id'] for a in list_assemblers()}
    assert ASSEMBLER_CAMERA_IMAGE_D6_V17 in asm_ids
    inst = create_assembler(ASSEMBLER_CAMERA_IMAGE_D6_V17)
    assert inst.ASSEMBLER_ID == ASSEMBLER_CAMERA_IMAGE_D6_V17


def test_camera_v17_telecontrol_smoke() -> None:
    TeleControlCfgManager.reload(cfg_id_for_camera('v17'))
    tc = TeleControlCfgManager.get(cfg_id_for_camera('v17'))
    orders = tc.list_orders()
    assert orders
    oid = orders[0].get('id')
    assert oid
    result = tc.assemble(oid, [])
    assert result.get('hex')


def test_v17_tm_parser_uses_d8v17_table_key() -> None:
    raw = bytes.fromhex(
        'EB 90 D8 00 00 2D 98 F4 00 00 01 FF FF FF FF 00 00 05 4E 00 06 04 01 00 10 '
        '00 00 13 24 E5 07 A7 01 2C 01 01 01 14 07 D3 0D AC 03 90 0A 6A 00 00 00 00 32 00 00 D6'
    )
    parsed = XlCameraTmV17Ingest.parse_bytes(raw)
    assert parsed.table_key == CFG_TABLE_D8 == 'D8V17'


def test_v16_v17_mux_caches_are_isolated() -> None:
    from module_payload.parsers.xl_camera_tm import XlCameraTmIngest, reset_xl_camera_tm_mgr
    from module_payload.parsers.xl_camera_tm_v17 import reset_xl_camera_tm_v17_mgr

    reset_xl_camera_tm_mgr()
    reset_xl_camera_tm_v17_mgr()
    assert XlCameraTmIngest._d9_mux_cache is not XlCameraTmV17Ingest._d9_mux_cache
    assert XlCameraTmIngest._tm_file_cache is not XlCameraTmV17Ingest._tm_file_cache
