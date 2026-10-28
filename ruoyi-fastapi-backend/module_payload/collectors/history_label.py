"""遥控发送历史展示名：把 op / protocolBuild method 收成可读中文。

所有协议共用；写 Redis 历史时用，前端直接显示 entry.name。
"""

from __future__ import annotations

from typing import Any

# gpcan builder 方法 → 历史文案（各协议共用同一套 method 名）
_PROTOCOL_METHOD_LABELS: dict[str, str] = {
    "build_telemetry_request": "遥测请求",
    "build_time_sync": "时间同步",
    "build_telecommand": "遥控指令",
    "build_broadcast": "广播",
    "build_system": "系统指令",
}

# 完整 op 或尾段 action → 文案（覆盖非 protocolBuild 路径）
_OP_LABELS: dict[str, str] = {
    "protocolbuild": "协议组帧",
    "timedtmenable": "定时遥测",
    "timesyncbroadcast": "定时同步广播",
    "timesyncsetpayload": "时间同步",
    "timesyncbroadcasttick": "时间同步",
    "timesyncsetstart": "设置起始时间",
    "timesyncresetstart": "重置起始时间",
    "timesyncsetoffset": "设置时间偏移",
    "timesyncsetgnss": "设置 GNSS 标志",
    "timesyncget": "查询定时状态",
    "tmrequest": "遥测请求",
    "systemreset": "系统复位",
    "systemcmd": "系统指令",
    "customsend": "自定义发送",
}


def _compact(s: str) -> str:
    return (
        str(s or "")
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
        .replace(".", "")
        .lower()
    )


def history_display_name(cmd: dict[str, Any] | None) -> str:
    """从命令字典得到历史列表中间的展示名。

    优先 protocol_build.method；其次已知 op；否则退回 name / order_id。
    """
    cmd = cmd or {}
    pb = cmd.get("protocol_build") or {}
    if not isinstance(pb, dict):
        pb = {}
    method = str(pb.get("method") or "").strip()
    if method:
        label = _PROTOCOL_METHOD_LABELS.get(method) or _PROTOCOL_METHOD_LABELS.get(
            method.lower()
        )
        if label:
            return label

    raw_name = str(cmd.get("name") or cmd.get("order_id") or "").strip()
    if not raw_name:
        return ""

    # 已是中文/人工名（板卡遥控指令等）直接保留
    if not any(ch.isascii() and (ch.isalpha() or ch == ".") for ch in raw_name):
        return raw_name
    # 含点号的机器 op，或纯 ASCII 标识
    compact = _compact(raw_name)
    # 去掉协议族前缀再匹配：yj216.protocolBuild → protocolbuild
    if "." in raw_name:
        tail = _compact(raw_name.split(".", 1)[-1])
        for key, label in _OP_LABELS.items():
            if tail == key or key in tail:
                return label
    for key, label in _OP_LABELS.items():
        if compact == key or compact.endswith(key):
            return label
    return raw_name
