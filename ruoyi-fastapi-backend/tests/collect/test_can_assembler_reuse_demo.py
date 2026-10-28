"""虚拟 CAN：同通道 already_open 切换协议族后，业务发送线帧与黄金一致。

覆盖：
- BIU → YJ216（附加回归）
- XL → BIU（对齐联调 bug：BIU 应为单帧 00000368，不能仍是 XL 三帧）
- BIU → XL（对称：应为 XL 三帧 000002FB）

标记 virtual_hw；需本机 gpcan DEMO。默认 run_test / pytest 无 DEMO 时 skip，
真正验证请：pytest tests/collect/test_can_assembler_reuse_demo.py -m virtual_hw
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gpcan import CanVendorType
from gpcan_compat import patch_virtual_hardware_unix_unlink
from virtual_hw import gpcan_demo_available

patch_virtual_hardware_unix_unlink()

pytestmark = pytest.mark.virtual_hw

_DATA = Path(__file__).resolve().parents[1] / 'data'
_GOLDEN = _DATA / 'can_assembler_reuse_k1501.json'
_DEMO_VENDOR = int(CanVendorType.CAN_VENDOR_DEMO)


def _demo_slot() -> tuple[int, int]:
    """避开常用卡号 0:0。"""
    return 220 + (os.getpid() % 30), 0


@pytest.fixture(scope='module')
def require_demo_can() -> None:
    if not gpcan_demo_available():
        pytest.skip('需要 gpcan 且支持 CanVendorType.CAN_VENDOR_DEMO 虚拟 CAN')


def _load_golden() -> dict:
    return json.loads(_GOLDEN.read_text(encoding='utf-8'))


def _case(golden: dict, case_id: str) -> dict:
    for c in golden['cases']:
        if c['id'] == case_id:
            return c
    raise KeyError(f'golden 缺少 case id={case_id!r}: {_GOLDEN}')


def _expected_frames(case: dict) -> list[dict]:
    return [
        {'id': int(fr['id']), 'data': [int(b) for b in fr['data']]}
        for fr in case['expected_frames']
    ]


def _make_collector(first_assembler_id: str, ch_base: dict, device_id: str, vendor: int, dev_index: int):
    from module_payload.collectors.can_collector import CanCollector

    with patch(
        'module_payload.collectors.base_collector.create_sync_redis',
        return_value=MagicMock(),
    ):
        coll = CanCollector(
            device_id,
            {
                'vendor': vendor,
                'dev_index': dev_index,
                'channels': [{**ch_base, 'assembler_id': first_assembler_id}],
            },
        )
        coll._push_io = MagicMock()
        coll._push_stream_io = MagicMock()
        coll._write_status = MagicMock()
        coll._write_channel_status = MagicMock()
        coll._ingest_protocol_msg = lambda *a, **k: None
        coll._get_session_cached = lambda *a, **k: {}
        coll._push_history = MagicMock()
        return coll


def _reuse_send_and_assert(
    *,
    first_family: str,
    reuse_family: str,
    payload_hex: str,
    expected: list[dict],
    label: str,
) -> None:
    """先按 first_family 打开 DEMO 通道，再 already_open 切到 reuse_family 发送并对拍。"""
    from module_payload import redis_keys as rk
    from module_payload.protocol.protocol_catalog import bus_assembler_id

    first_aid = bus_assembler_id(first_family)
    reuse_aid = bus_assembler_id(reuse_family)
    vendor = _DEMO_VENDOR
    dev_index, can_index = _demo_slot()
    device_id = rk.can_card_id(vendor, dev_index)
    ch_base = {
        'vendor': vendor,
        'dev_index': dev_index,
        'can_index': can_index,
        'baud_rate': 500,
        'cable_flag': 0,
        'node_addr_to': 0x0D,
    }

    coll = _make_collector(first_aid, ch_base, device_id, vendor, dev_index)
    assert coll.setup(), f'{first_family} 打开虚拟 CAN 失败'
    try:
        assert coll._channels[can_index]['cfg']['assembler_id'] == first_aid

        ok, err = coll._open_channel_client(
            can_index, {**ch_base, 'assembler_id': reuse_aid}
        )
        assert ok and not err, err or f'{reuse_family} 复用打开失败'
        assert coll._channels[can_index]['cfg']['assembler_id'] == reuse_aid

        cmd = {
            'can_index': can_index,
            'use_business': True,
            'hex': payload_hex,
            'name': label,
        }
        result = coll.execute_command(cmd)
        assert result.get('success') is True, result
        assert cmd.get('can_frames') == expected, (
            f'{first_family}->{reuse_family} 复用后线帧不符黄金: '
            f'got={cmd.get("can_frames")} expected={expected}'
        )
    finally:
        coll._close_channel(can_index)
        assert can_index not in coll._channels
        try:
            coll.teardown()
        except Exception:
            pass


def test_demo_can_biu_then_yj216_send_matches_golden(require_demo_can: None) -> None:
    """附加：BIU 开 → 同通道 YJ216 复用 → 发业务 HEX → 线帧对黄金 → 关闭。"""
    golden = _load_golden()
    case = _case(golden, 'biu_to_yj216')
    _reuse_send_and_assert(
        first_family=str(case['first']),
        reuse_family=str(case['reuse']),
        payload_hex=str(golden['payload_hex']),
        expected=_expected_frames(case),
        label='通信激光器驱动器禁止',
    )


def test_demo_can_xl_then_biu_send_matches_golden(require_demo_can: None) -> None:
    """对齐联调 bug：XL 开 → 同通道 BIU already_open（不关通道）→ 应为单帧 00000368。"""
    golden = _load_golden()
    case = _case(golden, 'xl_to_biu')
    _reuse_send_and_assert(
        first_family=str(case['first']),
        reuse_family=str(case['reuse']),
        payload_hex=str(golden['payload_hex']),
        expected=_expected_frames(case),
        label='通信激光器驱动器禁止',
    )


def test_demo_can_biu_then_xl_send_matches_golden(require_demo_can: None) -> None:
    """对称：BIU 开 → 同通道 XL already_open → 应为 XL 三帧 000002FB。"""
    golden = _load_golden()
    case = _case(golden, 'biu_to_xl')
    _reuse_send_and_assert(
        first_family=str(case['first']),
        reuse_family=str(case['reuse']),
        payload_hex=str(golden['payload_hex']),
        expected=_expected_frames(case),
        label='通信激光器驱动器禁止',
    )
