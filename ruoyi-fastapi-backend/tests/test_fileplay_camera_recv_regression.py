# -*- coding: utf-8 -*-
"""历史文件回放回归：相机 v1.6 控制串口 COM4 实采（含 D8 慢遥 + D9 快遥）。

样本：``tests/data/camera_ctrl_serial_COM4_20260814_170250_078_recv.bin``

说明：
- D8：可对整文件精确索引（帧数多但拆帧快）。
- D9：整文件 ``extract_d9_frames`` 与 EB90 占用区间做笛卡尔重叠检查，体量大会极慢；
  故 D9 / 混合用例取文件前部含两类帧的切片写入临时 ``*_recv.bin`` 再回放。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from module_payload.fileplay.detect import detect_file_kind, index_file
from module_payload.fileplay.parse_frame import parse_frame
from module_payload.parsers.xl_camera_tm import XlCameraTmIngest, reset_xl_camera_tm_mgr

_DATA = Path(__file__).resolve().parent / 'data'
_BIN = _DATA / 'camera_ctrl_serial_COM4_20260814_170250_078_recv.bin'

# 前 80KB：实测同时含 D8 与 D9，体量适合常驻回归
_MIX_SLICE = slice(0, 80_000)


@pytest.fixture(scope='module')
def com4_bin() -> Path:
    assert _BIN.is_file(), f'缺少测试数据 {_BIN}'
    return _BIN


@pytest.fixture(scope='module')
def com4_raw(com4_bin: Path) -> bytes:
    return com4_bin.read_bytes()


@pytest.fixture(scope='module')
def d8_index(com4_bin: Path):
    return index_file(com4_bin, 'XL:D8', force_estimate=False)


@pytest.fixture
def mix_recv_path(com4_raw: bytes, tmp_path: Path) -> Path:
    """含 D8+D9 的短切片，供 D9 索引与混合断言。"""
    path = tmp_path / 'cam_v16_com4_mix_recv.bin'
    path.write_bytes(com4_raw[_MIX_SLICE])
    return path


# ---------------------------------------------------------------------------
# 文件级 / D8
# ---------------------------------------------------------------------------


def test_com4_bin_is_v16_camera_ctrl_serial(com4_bin: Path, com4_raw: bytes) -> None:
    """样本为二进制，且同时能抽出 D8 与 D9（v1.6 控制口混流）。"""
    assert detect_file_kind(com4_bin) == 'bin'
    d8 = XlCameraTmIngest.extract_d8_frames(com4_raw)
    # 整文件不做 D9 全量拆帧（过慢）；用切片证明流中含 D9
    d9 = XlCameraTmIngest.extract_d9_frames(com4_raw[_MIX_SLICE])
    assert len(d8) >= 40
    assert len(d9) >= 20
    assert d8[0][:3] == bytes([0xEB, 0x90, 0xD8])
    assert d9[0][:2] == bytes([0xEB, 0xD9])


def test_com4_d8_fileplay_index_and_parse(d8_index) -> None:
    """整文件 XL:D8：精确索引 + 真实解析，表键为 v1.6 的 D8。"""
    assert d8_index.frame_count_exact is True
    assert d8_index.frame_count >= 40
    assert len(d8_index.frames) == d8_index.frame_count
    assert d8_index.frames[0].raw[:3] == bytes([0xEB, 0x90, 0xD8])

    snap = parse_frame(d8_index, 1)
    assert snap['type'] == 'XL:D8'
    rows = snap.get('rows') or []
    assert len(rows) >= 10
    assert any(str(r.get('id') or '').startswith('CAM') for r in rows)

    reset_xl_camera_tm_mgr()
    direct = XlCameraTmIngest.parse_bytes(d8_index.frames[0].raw)
    assert direct.table_key == 'D8'
    assert direct.table_key != 'D8V17'
    assert len(direct.fields or []) == len(rows)


def test_com4_d8_replay_adjacent_frames_differ(d8_index) -> None:
    """D8 回放相邻帧内容不同且均可解析。"""
    assert d8_index.frame_count >= 2
    s1 = parse_frame(d8_index, 1)
    s2 = parse_frame(d8_index, 2)
    assert s1['type'] == s2['type'] == 'XL:D8'
    assert d8_index.frames[0].raw != d8_index.frames[1].raw
    assert (s1.get('rows') or []) and (s2.get('rows') or [])


def test_com4_d8_extract_matches_index(com4_raw: bytes, d8_index) -> None:
    """extract_d8_frames 与 fileplay 索引帧数、首/末帧一致。"""
    frames = XlCameraTmIngest.extract_d8_frames(com4_raw)
    assert len(frames) == d8_index.frame_count
    assert frames[0] == d8_index.frames[0].raw
    assert frames[-1] == d8_index.frames[-1].raw


# ---------------------------------------------------------------------------
# D9（切片）
# ---------------------------------------------------------------------------


def test_com4_d9_fileplay_index_and_parse(mix_recv_path: Path) -> None:
    """切片 XL:D9：索引 + 回放解析为 v1.6 快遥表。"""
    idx = index_file(mix_recv_path, 'XL:D9', force_estimate=False)
    assert idx.frame_count_exact is True
    assert idx.frame_count >= 20
    assert idx.frames[0].raw[:2] == bytes([0xEB, 0xD9])
    assert len(idx.frames[0].raw) == 20

    # 单帧即可出表；再取第 8 帧覆盖「向前拼包」路径
    s1 = parse_frame(idx, 1)
    assert s1['type'] == 'XL:D9'
    rows1 = s1.get('rows') or []
    assert len(rows1) >= 10

    fi = min(8, idx.frame_count)
    s8 = parse_frame(idx, fi)
    assert s8['type'] == 'XL:D9'
    assert len(s8.get('rows') or []) >= 10

    reset_xl_camera_tm_mgr()
    direct = XlCameraTmIngest.parse_bytes(idx.frames[0].raw)
    assert direct.table_key == 'D9'
    assert direct.table_key != 'D9V17'


def test_com4_d9_extract_matches_index(mix_recv_path: Path) -> None:
    """切片上 extract_d9_frames 与索引一致。"""
    raw = mix_recv_path.read_bytes()
    frames = XlCameraTmIngest.extract_d9_frames(raw)
    idx = index_file(mix_recv_path, 'XL:D9', force_estimate=False)
    assert len(frames) == idx.frame_count
    assert frames[0] == idx.frames[0].raw


def test_com4_d9_replay_adjacent_frames_differ(mix_recv_path: Path) -> None:
    """D9 相邻帧 raw 不同。"""
    idx = index_file(mix_recv_path, 'XL:D9', force_estimate=False)
    assert idx.frame_count >= 2
    assert idx.frames[0].raw != idx.frames[1].raw
    s1 = parse_frame(idx, 1)
    s2 = parse_frame(idx, 2)
    assert s1['type'] == s2['type'] == 'XL:D9'
    assert (s1.get('rows') or []) and (s2.get('rows') or [])


# ---------------------------------------------------------------------------
# 混合切片：同一文件两种表
# ---------------------------------------------------------------------------


def test_com4_mix_slice_has_both_d8_and_d9(mix_recv_path: Path) -> None:
    """同一控制口切片可分别按 XL:D8 / XL:D9 回放。"""
    idx8 = index_file(mix_recv_path, 'XL:D8', force_estimate=False)
    idx9 = index_file(mix_recv_path, 'XL:D9', force_estimate=False)
    assert idx8.frame_count >= 5
    assert idx9.frame_count >= 20

    s8 = parse_frame(idx8, 1)
    s9 = parse_frame(idx9, 1)
    assert s8['type'] == 'XL:D8'
    assert s9['type'] == 'XL:D9'
    assert s8['type'] != s9['type']
    assert (s8.get('rows') or []) and (s9.get('rows') or [])
