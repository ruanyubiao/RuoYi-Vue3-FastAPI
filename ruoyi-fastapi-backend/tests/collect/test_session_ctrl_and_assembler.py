"""P0-2：session_changed 走卡 ctrl；already_open 按本次 cfg 切 assembler（非 DEMO）。"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

from gpcan import CanProtocolType

from module_payload import redis_keys as rk
from module_payload.collectors.can_collector import CanCollector
from module_payload.collectors.process_manager import CollectorProcessManager
from module_payload.protocol.protocol_catalog import bus_assembler_id
from redis_fakes import fake_collector_redis

_CAN_BIU = bus_assembler_id("biu")
_CAN_XL = bus_assembler_id("xl")


def _mgr() -> CollectorProcessManager:
    m = CollectorProcessManager.__new__(CollectorProcessManager)
    m._registry = {}
    m._lifecycle_lock = threading.RLock()
    m._shutting_down = False
    m._redis = None
    return m


def _fake_client(*, proto=CanProtocolType.XL) -> MagicMock:
    client = MagicMock()
    client.get_protocol.return_value = proto
    return client


def _can_stub() -> CanCollector:
    c = CanCollector.__new__(CanCollector)
    c.device_id = "can:3:0"
    c.config = {"vendor": 3, "dev_index": 0}
    redis, c._fake = fake_collector_redis()
    c._redis = redis
    c._channels = {}
    c._session_cache = {}
    c._session_cache_mono = {}
    c._pipeline_lock = threading.RLock()
    return c


def test_notify_session_changed_uses_collector_ctrl_id_card_not_channel() -> None:
    """CAN 通道 id 须落到卡进程控制队列（collector_ctrl_id），不能推到通道 id。"""
    mgr = _mgr()
    mgr._push_ctrl = MagicMock()

    channel_id = "can:3:0:1"
    assert rk.collector_ctrl_id(channel_id) == "can:3:0"

    mgr.notify_session_changed(channel_id)
    mgr._push_ctrl.assert_called_once_with("can:3:0", {"op": "session_changed"})

    mgr._push_ctrl.reset_mock()
    mgr.notify_session_changed("serial:COM4")
    mgr._push_ctrl.assert_called_once_with("serial:COM4", {"op": "session_changed"})


def test_already_open_applies_cfg_assembler_not_old_redis_session() -> None:
    """already_open：本次打开 cfg 的 assembler 生效，旧 Redis 会话不得盖掉。"""
    c = _can_stub()
    c._write_channel_status = MagicMock()
    client = _fake_client(proto=CanProtocolType.XL)
    c._channels[0] = {
        "client": client,
        "cfg": {"can_index": 0, "assembler_id": _CAN_XL},
        "channel_device_id": "can:3:0:0",
    }
    c._get_session_cached = MagicMock(return_value={"assemblerId": _CAN_XL})
    c._sync_client_protocol = MagicMock(return_value=_CAN_XL)

    ok, err = c._open_channel_client(0, {"can_index": 0, "assembler_id": _CAN_BIU})
    assert ok is True and err == ""
    assert c._channels[0]["cfg"]["assembler_id"] == _CAN_BIU
    client.set_protocol_param.assert_called()
    c._sync_client_protocol.assert_not_called()
    client.get_protocol.return_value = CanProtocolType.BIU
    del c._sync_client_protocol
    assert c._sync_client_protocol(c._channels[0]) == _CAN_BIU
