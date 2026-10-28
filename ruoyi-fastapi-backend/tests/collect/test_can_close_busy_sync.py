"""P0-1：关 CAN 后 busy_can / registry 投影立刻清。

不靠 ensure_hardware_idle。busy 语义对齐 HIL ipc_api.busy_can：从 list_opened
registry 看目标通道是否仍带 assembler 配置。

说明：process_manager.close_can_channel 已同步摘通道/config（单测绿）；
HIL「网页关后短轮询」主断言仍归自动化，产品合入后跟。
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock

from module_payload.collectors.process_manager import CollectorProcessManager, ProcessEntry


def _mgr() -> CollectorProcessManager:
    m = CollectorProcessManager.__new__(CollectorProcessManager)
    m._registry = {}
    m._lifecycle_lock = threading.RLock()
    m._shutting_down = False
    m._redis = None
    return m


def _busy_can(
    opened: list[dict[str, Any]],
    vendor: int,
    dev_index: int,
    channels: list[int],
) -> dict[int, str]:
    """与 HIL busy_can 同源：registry 中仍打开的目标通道 → {ch: 描述}。"""
    out: dict[int, str] = {}
    for r in opened or []:
        if r.get("type") != "can" or not r.get("alive", True):
            continue
        cfg = r.get("config") or {}
        matched = int(cfg.get("vendor", -1)) == vendor and int(cfg.get("dev_index", -1)) == dev_index
        if not matched:
            parts = str(r.get("deviceId") or "").split(":")
            matched = (
                len(parts) >= 3
                and parts[0] == "can"
                and int(parts[1]) == vendor
                and int(parts[2]) == dev_index
            )
        if not matched:
            continue
        for ch in cfg.get("channels") or []:
            if not isinstance(ch, dict):
                continue
            ci = int(ch.get("can_index", -1))
            if ci in channels:
                out[ci] = (
                    f"{r.get('deviceId')}:{ci} assembler={ch.get('assembler_id')} "
                    f"cable_flag={ch.get('cable_flag')} node_addr_to={ch.get('node_addr_to')}"
                )
        for ci in r.get("channels") or []:
            if int(ci) in channels and int(ci) not in out:
                out[int(ci)] = f"{r.get('deviceId')}:{ci}"
    return out


def test_close_can_clears_busy_can_projection_immediately() -> None:
    """关通道返回后，busy_can 对该通道立刻为空；不得依赖 idle 兜底。"""
    m = _mgr()
    m._push_ctrl = MagicMock()
    m._touch_snapshot = MagicMock()
    entry = ProcessEntry(
        "can:3:0",
        "can",
        process=MagicMock(poll=MagicMock(return_value=None)),
        config={
            "vendor": 3,
            "dev_index": 0,
            "channels": [
                {"can_index": 0, "assembler_id": "can_xl", "cable_flag": 0, "node_addr_to": 13},
                {"can_index": 1, "assembler_id": "can_xl", "cable_flag": 1, "node_addr_to": 13},
            ],
        },
    )
    entry.opened_channels.update({0, 1})
    m._registry["can:3:0"] = entry

    before = _busy_can(m.list_opened(), 3, 0, [0, 1])
    assert 0 in before and 1 in before

    m.close_can_channel(3, 0, 0)
    after_one = _busy_can(m.list_opened(), 3, 0, [0, 1])
    assert 0 not in after_one, f"关 ch0 后 busy 仍含 0: {after_one}"
    assert 1 in after_one

    m.close_can_channel(3, 0, 1)
    after_all = _busy_can(m.list_opened(), 3, 0, [0, 1])
    assert after_all == {}, f"双通道关后 busy 应空，实际={after_all}"
    assert m.list_opened() == []
