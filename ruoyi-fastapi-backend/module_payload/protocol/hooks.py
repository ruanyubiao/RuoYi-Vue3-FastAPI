"""协议模块对框架公开的钩子。

每个协议模块导出 ``BINDINGS = ProtocolBindings(...)``；``protocol_catalog`` 的行只写模块路径。
框架经 ``protocol.registry`` 按同一组属性名调用，没填的钩子走框架默认。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

ExtractFn = Callable[[bytes, str], list[bytes]]
MatchFn = Callable[[bytes, str], bytes | None]
VerifyFn = Callable[[bytes], tuple[bool, str, bytes]]


@dataclass(frozen=True, slots=True)
class FilePlaySpec:
    """一种表键的文件回放拆帧与解字段。"""

    kind: str
    extract: ExtractFn
    parse: Any
    parse_span: int = 1
    match: MatchFn | None = None


def method_extract(cls: Any, name: str) -> ExtractFn:
    """调用时再取类方法，测试 patch 才能作用到拆帧。"""

    def extract(buf: bytes, table_type: str) -> list[bytes]:
        return list(getattr(cls, name)(buf))

    return extract


@dataclass(frozen=True)
class ProtocolBindings:
    """一个协议模块的钩子。字段都可以空。"""

    # 收包拼帧类；CAN 总线不填时用 can_feed 按目录表的 gpcan_protocol 拼帧
    assembler_cls: type | None = None
    # 遥测解释器类（prepare_bytes / parse_bytes / ingest_*）
    ingest: Any = None
    # 清遥测配置缓存；tm_cfg_files 是它读的配置文件名，按文件热重载时只清对应的
    reset_tm: Callable[[], None] | None = None
    tm_cfg_files: tuple[str, ...] = ()
    # 非总线表的文件回放规格：本地表键 → 规格
    fileplay_tables: Mapping[str, FilePlaySpec] = field(default_factory=dict)
    # 遥控组帧 (order, values, **kwargs) → {'hex', ...}
    assemble: Callable[..., dict[str, Any]] | None = None
    # 以下只对总线族有意义
    # 遥测内容校验 (raw) → (ok, message, frame)
    verify_tm: VerifyFn | None = None
    # 总线表的文件回放规格；不填时按 verify_tm 滑动扫描，表号取 frame[3]
    fileplay: FilePlaySpec | None = None
    # 业务指令组 CAN 帧 (builder, raw, *, broadcast)；不填用 gpcan build_telecommand / build_broadcast
    build_can_command: Callable[..., Any] | None = None
    # 定时遥测请求 (tick) → (间隔秒, build_telemetry_request 参数)；不填为 1 秒、无参数
    timed_tm: Callable[[int], tuple[float, dict[str, Any]]] | None = None
    # 线缆目标地址 (请求值) → 实际地址；不填用请求值
    node_addr: Callable[[Any], int] | None = None
