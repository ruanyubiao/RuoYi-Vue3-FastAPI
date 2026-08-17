"""CAN 采集进程内的定时遥测 / 定时广播：操作解析与通道轮询（无硬件依赖）。"""

from __future__ import annotations

import time
from typing import Any


def next_round_robin_can(open_ids: list[int], last_id: int | None) -> int | None:
    """在当前已连接 CAN 列表中取「上次之后的下一个」（环形）。

    - 列表为空 → None（调用方应关闭定时）
    - 尚无上次记录 → 列表第一项（通常 CAN-A / 较小 index）
    - 上次仍在列表中 → 其后一项，末尾则回到 [0]
    - 上次已不在列表（该通道刚关掉）→ 从「比上次更大的第一个」起找，否则回到 [0]
    """
    ids = sorted({int(x) for x in open_ids})
    if not ids:
        return None
    if last_id is None:
        return ids[0]
    last = int(last_id)
    if last in ids:
        i = ids.index(last)
        return ids[(i + 1) % len(ids)]
    for x in ids:
        if x > last:
            return x
        return ids[0]


def pick_timed_tm_can(open_ids: list[int], prefer_id: int | None) -> int | None:
    """定时遥测通道：优先用打开时选中的口；该口关闭则用剩余口；再打开则回到首选。"""
    ids = sorted({int(x) for x in open_ids})
    if not ids:
        return None
    if prefer_id is not None and int(prefer_id) in ids:
        return int(prefer_id)
    return ids[0]


def can_port_label(can_index: int, cable_flag: int | None = None) -> str:
    """CAN-A / CAN-B：优先线缆标志（0=A, 1=B），否则按通道号。"""
    if cable_flag is not None:
        flag = int(cable_flag)
        if flag == 0:
            return 'CAN-A'
        if flag == 1:
            return 'CAN-B'
    idx = int(can_index)
    if idx == 0:
        return 'CAN-A'
    if idx == 1:
        return 'CAN-B'
    return f'CAN{idx}'


def utc_to_epoch_ms_floor_sec(utc: str | None) -> int:
    """UTC 文本取整到秒后转为 epoch 毫秒，对齐 Demo ``_datetime_epoch_ms_floor_sec``。"""
    from datetime import datetime, timezone

    text = str(utc or '').strip()
    if not text:
        return int(time.time()) * 1000 // 1000 * 1000
    try:
        dt = datetime.strptime(text[:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        return int(dt.timestamp()) * 1000
    except ValueError:
        return int(time.time()) * 1000 // 1000 * 1000


def parse_timer_op(op: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """识别 ``biu|xl`` 定时遥测 / 时间同步控制。按压缩子串匹配，避免大小写或下划线漏判。"""
    p = params or {}
    compact = str(op or '').replace('_', '').replace('-', '').replace(' ', '').replace('.', '').lower()
    if not compact:
        return None

    parts = [x.strip() for x in str(op or '').split('.') if x.strip()]
    names = [x.lower() for x in parts]
    if 'xl' in names:
        family = 'xl'
    elif 'biu' in names:
        family = 'biu'
    else:
        return None

    enable = bool(p.get('enable'))
    gnss = bool(p.get('gnssValid', p.get('gnss_valid', True)))
    offset = p.get('offsetMs', p.get('offset_ms', 0))

    if 'timedtmenable' in compact:
        return {'kind': 'timed_tm', 'enable': enable, 'family': family}
    if 'timesync' not in compact:
        return None
    if 'timesyncget' in compact or 'timesyncstatus' in compact:
        return {'kind': 'get_status', 'family': family}
    if 'resetstart' in compact or 'resetoffset' in compact:
        return {'kind': 'reset_start', 'family': family}
    if 'setoffset' in compact:
        return {'kind': 'set_offset', 'offsetMs': offset, 'family': family}
    if 'setstart' in compact:
        return {'kind': 'set_start', 'utc': p.get('utc'), 'family': family}
    if 'setgnss' in compact:
        return {'kind': 'set_gnss', 'gnssValid': gnss, 'family': family}
    if 'broadcast' in compact:
        return {'kind': 'timed_sync', 'enable': enable, 'gnssValid': gnss, 'family': family}
    return None


def time_sync_for_family(family: str):
    """gpcan 1.0.2：按协议取 TimeSync，禁止直接 ``TimeSync.xxx``。"""
    from gpcan import CanProtocolType, TimeSyncManager

    proto = CanProtocolType.XL if str(family or '').lower() == 'xl' else CanProtocolType.BIU
    return TimeSyncManager.find(proto)
