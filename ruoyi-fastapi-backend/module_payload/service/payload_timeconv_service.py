"""调试-时间转换：协议时间纪元（gpcan ``EPOCH_UTC``）只读清单。"""

from __future__ import annotations

import importlib
from datetime import datetime, timezone
from typing import Any

from module_payload.protocol.protocol_catalog import CAN_BUS_FAMILIES

_NONE_PROTOCOL = 'none'


def epoch_utc_seconds(protocol: str) -> int:
    """按 gpcan 协议名取 ``defs.EPOCH_UTC``。协议目录新增总线时无需改这里。"""
    defs = importlib.import_module(f'gpcan.protocol.{protocol}.defs')
    return int(defs.EPOCH_UTC)


def _epoch_date(epoch_utc_sec: int) -> str:
    return datetime.fromtimestamp(epoch_utc_sec, timezone.utc).strftime('%Y-%m-%d')


def _epoch_item(protocol: str) -> dict[str, Any]:
    epoch = epoch_utc_seconds(protocol)
    date_utc = _epoch_date(epoch)
    name = protocol.upper()
    return {
        'id': protocol,
        'label': f'{name}: {date_utc}',
        'epochUtcSec': epoch,
        'dateUtc': date_utc,
    }


class PayloadTimeconvService:
    """时间转换页的协议纪元来源；不接控制页 TimeSync 偏移。"""

    @classmethod
    def list_epochs(cls) -> list[dict[str, Any]]:
        """``none`` + 协议目录中的全部总线族，顺序稳定。"""
        protocols = (_NONE_PROTOCOL, *(row.family for row in CAN_BUS_FAMILIES))
        return [_epoch_item(protocol) for protocol in protocols]
