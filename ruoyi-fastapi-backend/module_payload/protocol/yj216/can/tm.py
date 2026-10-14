"""
YJ216-CAN 实时遥测解析与落库（解释器 tm_can_yj216）。

gpcan 重组并去掉复帧长度前缀后，应用数据为：
帧类型 0x3A、表号 1 字节、附录 B0–B34（35 字节）、SUM。
SUM 为前面全部字节的无符号累加和低 8 位；不符则丢帧。
校验在本文件的 ``verify_tm``；文件回放的帧扫描是本文件的 ``FILEPLAY``。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from redis import asyncio as aioredis

from module_payload.cfg.hex_text import hex_to_bytes
from module_payload.constants import (
    DATA_KIND_TM,
    ERROR_TYPE_PARSER,
    SRC_KIND_HTTP,
    checksum_u8,
    infer_src_kind,
    make_bus_tm_key,
    split_tm_table_key,
)
from module_payload.protocol.hooks import FilePlaySpec
from module_payload.protocol.protocol_catalog import bus_parser_id, require_bus_family
from module_payload.tm.tm_ingest_batch import (
    PreparedTmFrame,
    enqueue_prepared,
    process_prepared_async,
)
from module_payload.tm.tm_mgr_cache import TmMgrFileCache

TM_FRAME_TYPE = 0x3A
TM_PAYLOAD_LEN = 35  # 附录 B0–B34
TM_CFG_FILE = require_bus_family('yj216').telemetry_cfg

_tm_cache = TmMgrFileCache()


def reset_tm_mgr() -> None:
    """清空 YJ216 遥测配置缓存。"""
    _tm_cache.clear()


def _get_tm_mgr():
    """加载 YJ216-TeleMetryCfg。"""
    return _tm_cache.get(TM_CFG_FILE, error='YJ216 遥测配置初始化失败')


def verify_tm(data: bytes | None) -> tuple[bool, str, bytes]:
    """校验帧类型、长度与 SUM。失败时第二项为错误说明。"""
    frame = bytes(data or b'')
    expect_len = 2 + TM_PAYLOAD_LEN + 1
    if len(frame) != expect_len:
        return False, f'帧长度错误: {len(frame)}', frame
    if frame[0] != TM_FRAME_TYPE:
        return False, f'帧类型错误: 0x{frame[0]:02X}', frame
    checksum = checksum_u8(frame[:-1])
    if frame[-1] != checksum:
        return False, '校验和错误', frame
    return True, '', frame


@dataclass(slots=True)
class ParsedYj216CanTm:
    """校验并字段解析后的一帧（尚未落库）。"""

    table_key: str
    name: str
    fields: list[dict[str, Any]]
    raw_frame: bytes
    data_len: int
    frame_type: str
    size: int

    @property
    def raw_hex(self) -> str:
        """完整帧十六进制，空格分隔。"""
        return ' '.join(f'{b:02X}' for b in self.raw_frame)


class Yj216CanTmIngest:
    """YJ216-CAN 遥测解释器：解析 + Redis + 归档入队。"""

    PARSER_ID = bus_parser_id('yj216')
    DATA_KIND = DATA_KIND_TM

    @classmethod
    def prepare_bytes(cls, data: bytes) -> PreparedTmFrame:
        """校验拆帧 → 待批处理帧（不做 TeleMetry 解析）。"""
        ok, msg, frame = verify_tm(data)
        if not ok:
            raise ValueError(msg)
        local_key = f'{frame[1]:02X}'
        storage_key = make_bus_tm_key('yj216', local_key)
        payload = bytes(frame[2:-1])
        mgr = _get_tm_mgr()
        cfg = mgr.get_table_cfg_by_key(local_key)
        if cfg is None:
            raise ValueError(f'遥测表未配置: dataType=0x{local_key}')
        return PreparedTmFrame(
            table_key=storage_key,
            name=cfg.name or local_key,
            payload=payload,
            raw_frame=bytes(frame),
            src_param='',
            src_kind='',
            parser_id=cls.PARSER_ID,
            mgr=mgr,
            data_kind=cls.DATA_KIND,
            parse_key=local_key,
        )

    @classmethod
    def parse_bytes(cls, data: bytes) -> ParsedYj216CanTm:
        """二进制完整帧 → 全量字段列表。"""
        prepared = cls.prepare_bytes(data)
        fields = prepared.mgr.parse(prepared.cfg_parse_key(), prepared.payload) or []
        if not fields:
            raise ValueError(f'遥测解析无结果: {prepared.table_key}')
        frame = prepared.raw_frame
        return ParsedYj216CanTm(
            table_key=prepared.table_key,
            name=prepared.name,
            fields=fields,
            raw_frame=frame,
            data_len=len(prepared.payload),
            frame_type=f'{frame[0]:02X}',
            size=len(frame),
        )

    @classmethod
    def parse_hex(cls, hex_text: str) -> ParsedYj216CanTm:
        """HEX 文本（空格可选）→ 字段列表。"""
        try:
            raw = hex_to_bytes(hex_text)
        except ValueError as e:
            raise ValueError(f'HEX 格式错误: {e}') from e
        return cls.parse_bytes(raw)

    @classmethod
    def ingest_bytes_sync(
        cls,
        redis_client: Any,
        data: bytes,
        *,
        src_param: str,
        src_kind: str | None = None,
        parser_id: str | None = None,
        quiet: bool = True,
        immediate: bool = False,
    ) -> dict[str, Any] | None:
        """采集侧入队。校验失败写 payload:error；quiet 时返回 None。"""
        pid = parser_id or cls.PARSER_ID
        try:
            prepared = cls.prepare_bytes(data)
        except ValueError as e:
            from module_payload.store.error_store import push_pipeline_error

            push_pipeline_error(
                redis_client,
                error_type=ERROR_TYPE_PARSER,
                message=str(e),
                device_id=src_param or '',
                parser_id=pid,
                data_len=len(data) if data is not None else None,
            )
            if quiet:
                return None
            raise
        prepared.src_param = src_param
        prepared.src_kind = src_kind or infer_src_kind(src_param)
        prepared.parser_id = pid
        return enqueue_prepared(redis_client, prepared, immediate=immediate)

    @classmethod
    async def ingest_hex_async(
        cls,
        redis: aioredis.Redis,
        hex_text: str,
        *,
        src_param: str = 'http:devtest',
        src_kind: str = SRC_KIND_HTTP,
        parser_id: str | None = None,
    ) -> dict[str, Any]:
        """HTTP 注入：HEX → 立即解析落库。"""
        try:
            raw = hex_to_bytes(hex_text)
        except ValueError as e:
            raise ValueError(f'HEX 格式错误: {e}') from e
        return await cls.ingest_bytes_async(
            redis, raw, src_param=src_param, src_kind=src_kind, parser_id=parser_id
        )

    @classmethod
    async def ingest_bytes_async(
        cls,
        redis: aioredis.Redis,
        data: bytes,
        *,
        src_param: str,
        src_kind: str | None = None,
        parser_id: str | None = None,
    ) -> dict[str, Any]:
        """主进程二进制入口：立即处理。"""
        prepared = cls.prepare_bytes(data)
        prepared.src_param = src_param
        prepared.src_kind = src_kind or infer_src_kind(src_param)
        prepared.parser_id = parser_id or cls.PARSER_ID
        stored = await process_prepared_async(redis, [prepared]) or {}
        frame = prepared.raw_frame
        return {
            'dataType': prepared.table_key,
            'frameType': f'{frame[0]:02X}',
            'dataLen': len(prepared.payload),
            'size': len(frame),
            'fieldCount': len(stored.get('fields') or []),
            'name': stored.get('name', prepared.name),
            'ts': stored.get('ts', ''),
            'srcKind': prepared.src_kind,
            'srcParam': src_param,
            'parserId': prepared.parser_id,
        }


_SPAN = 2 + TM_PAYLOAD_LEN + 1


def _fileplay_match(raw: bytes, table_type: str) -> bytes | None:
    ok, _, frame = verify_tm(raw)
    if not ok:
        return None
    local = split_tm_table_key(table_type)[1]
    if local and f'{frame[1]:02X}' != local:
        return None
    return frame


def _fileplay_extract(buf: bytes, table_type: str) -> list[bytes]:
    local = split_tm_table_key(table_type)[1]
    out: list[bytes] = []
    i = 0
    n = len(buf)
    while i + _SPAN <= n:
        ok, _, frame = verify_tm(buf[i : i + _SPAN])
        if ok and (not local or f'{frame[1]:02X}' == local):
            out.append(frame)
            i += _SPAN
            continue
        i += 1
    return out


# 帧没有 2 字节长度，框架默认扫描对不上：按定长 38 字节滑动，表号在 frame[1]
FILEPLAY = FilePlaySpec(kind='can', extract=_fileplay_extract, parse=Yj216CanTmIngest, match=_fileplay_match)
