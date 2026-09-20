"""整表曲线压缩包：打包、since_t 开区间、按帧裁剪。"""

from __future__ import annotations

from module_payload.constants import CURVE_MAX_POINTS
from module_payload.store.curve_blob import (
    drop_oldest_count,
    pack_frames,
    parse_prefix,
    points_from_blobs,
    unpack_member,
)


def test_pack_roundtrip_and_prefix() -> None:
    member, score = pack_frames(
        [1000, 1001],
        {'CAMF001': [1.5, 2.5], 'CAMF002': [None, 3.0]},
        seq=7,
    )
    assert score == 1001
    parsed = parse_prefix(member)
    assert parsed is not None
    last_ts, n_frames, seq, blob = parsed
    assert last_ts == 1001
    assert n_frames == 2
    assert seq == 7
    assert blob
    data = unpack_member(member)
    assert data is not None
    assert data['t'] == [1000, 1001]
    assert data['CAMF001'] == [1.5, 2.5]
    assert data['CAMF002'] == [None, 3.0]
    from module_payload.store.curve_blob import decode_payload, encode_payload

    encoded = encode_payload(
        [1000, 1001],
        {'CAMF001': [1.5, 2.5], 'CAMF002': [None, 3.0]},
    )
    assert encoded == blob
    assert decode_payload(encoded) == data


def test_since_t_open_interval_drops_left_edge() -> None:
    data = unpack_member(pack_frames([10, 20, 30], {'J1': [1.0, 2.0, 3.0]}, seq=1)[0])
    pts = points_from_blobs([data], 'J1', limit=50, since_t=20, newest=False)
    assert [p['t'] for p in pts] == [30]
    assert pts[0]['v'] == 3.0


def test_drop_oldest_by_prefix_frames() -> None:
    members = [
        b'1|20000|1|x',
        b'2|20000|2|x',
        b'3|20000|3|x',
    ]
    assert drop_oldest_count(members, CURVE_MAX_POINTS) == 1
    assert drop_oldest_count(members[:2], CURVE_MAX_POINTS) == 0
    assert drop_oldest_count([], CURVE_MAX_POINTS) == 0
