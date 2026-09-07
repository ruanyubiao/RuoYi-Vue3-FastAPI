# -*- coding: utf-8 -*-
"""历史文件回放回归：BIU CAN 实采 recv.txt（多种复合遥测类型）。

样本：``tests/data/biu_can_a_can_0_0_0_20260907_recv.txt``

文件中混有 8 字节硬件分片行与已拼好的复合帧行；fileplay 只认校验通过的完整复合帧，
并按表本地 key（FF/FD/…）过滤。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from module_payload.fileplay.detect import detect_file_kind, index_file
from module_payload.fileplay.parse_frame import parse_frame

_DATA = Path(__file__).resolve().parent / 'data'
_BIN = _DATA / 'biu_can_a_can_0_0_0_20260907_recv.txt'

# 本样本中完整复合帧计数（按 dataType）
_EXPECTED_COUNTS = {
    'BIU:FF': 2,
    'BIU:FD': 2,
    'BIU:FB': 1,
    'BIU:F9': 1,
    'BIU:F7': 1,
    'BIU:FE': 1,
    'BIU:FC': 1,
}


@pytest.fixture(scope='module')
def biu_recv() -> Path:
    assert _BIN.is_file(), f'缺少测试数据 {_BIN}'
    return _BIN


@pytest.fixture(scope='module')
def indexes(biu_recv: Path) -> dict:
    return {
        tt: index_file(biu_recv, tt, force_estimate=False) for tt in _EXPECTED_COUNTS
    }


def test_biu_can_recv_is_hex_text(biu_recv: Path) -> None:
    assert detect_file_kind(biu_recv) == 'hex'


@pytest.mark.parametrize('table_type,count', list(_EXPECTED_COUNTS.items()))
def test_biu_can_recv_index_counts(indexes: dict, table_type: str, count: int) -> None:
    idx = indexes[table_type]
    assert idx.frame_count_exact is True
    assert idx.frame_count == count
    assert len(idx.frames) == count
    # 复合帧头：dataLen(2) + 3A + dataType
    assert idx.frames[0].raw[2] == 0x3A
    dtype = table_type.split(':')[-1]
    assert f'{idx.frames[0].raw[3]:02X}' == dtype


@pytest.mark.parametrize('table_type', list(_EXPECTED_COUNTS))
def test_biu_can_recv_parse_real_fields(indexes: dict, table_type: str) -> None:
    """真实 TeleMetry 解析：表类型正确且字段行非空。"""
    idx = indexes[table_type]
    snap = parse_frame(idx, 1)
    assert snap['type'] == table_type
    rows = snap.get('rows') or []
    assert len(rows) >= 10
    assert any(r.get('id') for r in rows)
    assert snap.get('rawLen') == len(idx.frames[0].raw)


def test_biu_can_recv_ff_adjacent_frames_differ(indexes: dict) -> None:
    idx = indexes['BIU:FF']
    assert idx.frame_count >= 2
    assert idx.frames[0].raw != idx.frames[1].raw
    s1 = parse_frame(idx, 1)
    s2 = parse_frame(idx, 2)
    assert s1['type'] == s2['type'] == 'BIU:FF'
    assert (s1.get('rows') or []) and (s2.get('rows') or [])


def test_biu_can_recv_fe_fc_nonzero(indexes: dict) -> None:
    """FE/FC 为算轨异步包：特征码等关键字段非空/非全零。"""
    fe = parse_frame(indexes['BIU:FE'], 1)
    fc = parse_frame(indexes['BIU:FC'], 1)
    fe_by_id = {r['id']: r for r in (fe.get('rows') or [])}
    fc_by_id = {r['id']: r for r in (fc.get('rows') or [])}
    assert fe_by_id['JGB1001']['value'] not in (None, 0, '')
    assert fc_by_id['JGB1201']['value'] not in (None, 0, '')
    # 载荷区不可全零（跳过帧头 4 字节与末校验）
    assert any(b != 0 for b in indexes['BIU:FE'].frames[0].raw[4:-1])
    assert any(b != 0 for b in indexes['BIU:FC'].frames[0].raw[4:-1])


def test_biu_can_recv_timestamps_present(indexes: dict) -> None:
    """完整帧行带文件时间戳，回放帧 ts_ms > 0。"""
    for tt, idx in indexes.items():
        assert idx.frames[0].ts_ms > 0, tt
        snap = parse_frame(idx, 1)
        assert snap.get('tsMs', 0) > 0, tt
