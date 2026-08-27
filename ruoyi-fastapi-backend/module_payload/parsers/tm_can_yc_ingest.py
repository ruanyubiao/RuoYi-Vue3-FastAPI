"""
BIU-CAN 遥测复合帧统一解析与落库（解释器 tm_can_biu）。

入口：
- 字节：真 CAN / 后续 UDP·串口组完后的完整帧
- HEX：开发测试 HTTP 注入

流程：严格校验 → 采集入队；表格 0.5s parse 一帧；曲线线程全部 parse_calc；原始流落盘。
遥测表存储键 data_sub=BIU:FF（帧内 dataType 为本地 FF）；解析仍用文件内 key。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from redis import asyncio as aioredis

from module_payload.cfg.can_yc_frame import verify_can_yc_frame
from module_payload.cfg.hex_text import hex_to_bytes
from module_payload.cfg.payload_config_loader import TELE_METRY_CFG_NAME
from module_payload.constants import (
    DATA_KIND_TM,
    PARSER_TM_CAN_BIU,
    SRC_KIND_HTTP,
    infer_src_kind,
    make_bus_tm_key,
)
from module_payload.parsers.tm_ingest_batch import (
    PreparedTmFrame,
    enqueue_prepared,
    process_prepared_async,
)
from module_payload.parsers.tm_mgr_cache import TmMgrFileCache

_tm_cache = TmMgrFileCache()


def reset_tm_mgr() -> None:
    """清空 CAN 遥测 TeleMetryCfgManager 缓存，下次解析时按当前配置文件重新 init。"""
    _tm_cache.clear()


def _get_tm_mgr():
    """加载 BIU TeleMetryCfg 的 TeleMetryParser 管理器（进程内文件缓存）。"""
    return _tm_cache.get(TELE_METRY_CFG_NAME, error='遥测配置初始化失败')


@dataclass(slots=True)
class ParsedTmCanYc:
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


class TmCanYcIngest:
    """CAN 遥测复合帧解释器：解析 + Redis + 归档入队。"""

    PARSER_ID = PARSER_TM_CAN_BIU
    DATA_KIND = DATA_KIND_TM

    @classmethod
    def prepare_bytes(cls, data: bytes) -> PreparedTmFrame:
        """校验拆帧 → 待批处理帧（不做 TeleMetry 解析）。"""
        ok, msg, frame = verify_can_yc_frame(data)
        if not ok:
            raise ValueError(msg)

        local_key = f'{frame[3]:02X}'  # 帧内 dataType，TeleMetryCfg 本地 key
        storage_key = make_bus_tm_key('biu', local_key)
        payload = bytes(frame[4:])
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
    def parse_bytes(cls, data: bytes) -> ParsedTmCanYc:
        """二进制完整帧 → 全量字段列表（调试/注入预览）。"""
        prepared = cls.prepare_bytes(data)
        # TeleMetryParser：按本地 key 解析数据区
        fields = prepared.mgr.parse(prepared.cfg_parse_key(), prepared.payload) or []
        if not fields:
            raise ValueError(f'遥测解析无结果: {prepared.table_key}')
        frame = prepared.raw_frame
        data_len = (frame[0] << 8) | frame[1]
        return ParsedTmCanYc(
            table_key=prepared.table_key,
            name=prepared.name,
            fields=fields,
            raw_frame=frame,
            data_len=data_len,
            frame_type=f'{frame[2]:02X}',
            size=len(frame),
        )

    @classmethod
    def parse_hex(cls, hex_text: str) -> ParsedTmCanYc:
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
        """
        采集侧：入批处理队列（默认 0.5s 刷写）。
        quiet=True 时校验失败写 payload:error 后返回 None；否则抛 ValueError。
        immediate=True 时立即处理本帧（测试/低频）。
        """
        pid = parser_id or cls.PARSER_ID
        try:
            prepared = cls.prepare_bytes(data)
        except ValueError as e:
            from module_payload.service.payload_error_store import push_pipeline_error

            push_pipeline_error(
                redis_client,
                stage='parser',
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
        # Redis 入队：采集线程不 parse
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
        """HTTP 注入：HEX → 立即解析落库。失败抛 ValueError。"""
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
        """主进程二进制入口：立即处理（不走 0.5s 批）。"""
        prepared = cls.prepare_bytes(data)
        prepared.src_param = src_param
        prepared.src_kind = src_kind or infer_src_kind(src_param)
        prepared.parser_id = parser_id or cls.PARSER_ID
        stored = await process_prepared_async(redis, [prepared]) or {}
        frame = prepared.raw_frame
        return {
            'dataType': prepared.table_key,
            'frameType': f'{frame[2]:02X}',
            'dataLen': (frame[0] << 8) | frame[1],
            'size': len(frame),
            'fieldCount': len(stored.get('fields') or []),
            'name': stored.get('name', prepared.name),
            'ts': stored.get('ts', ''),
            'srcKind': prepared.src_kind,
            'srcParam': src_param,
            'parserId': prepared.parser_id,
        }
