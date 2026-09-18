"""XL CPA 指向遥测解释器（协议 V1.0）。

物理层 RS422 921600 8N1；字节内 LSB 由硬件处理，软件不改位序。
定长 29 字节（文档写数据段 18 与 Byte1–26、样例矛盾，以样例为准）：
  55 AA | 26B 数据 | 校验
校验为前 28 字节累加后取低 8 位（含 55AA）。
数据段：工作状态(1) + 方位/俯仰位置(8) + 方位/俯仰速度(8) + 方位/俯仰零位(8) + 故障(1)。
多字节 Int32 小端；TeleMetryParser.parse(..., big_endian_buffer=False)。
故障 Bit1=字节最高位（bitpos 0）；Bit8=LSB（bitpos 7）。1 为故障。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from redis import asyncio as aioredis

from module_payload.cfg.payload_config_loader import PayloadConfigLoader
from module_payload.error_text import checksum_mismatch, frame_len_mismatch
from module_payload.constants import (
    DATA_KIND_TM,
    PARSER_TM_XL_CPAZX,
    SRC_KIND_SERIAL,
    checksum_u8,
    infer_src_kind,
)
from module_payload.parsers.tm_ingest_batch import (
    PreparedTmFrame,
    enqueue_prepared_many,
    process_prepared_async,
)
from module_payload.parsers.tm_mgr_cache import TmMgrFileCache

FRAME_HEADER = bytes((0x55, 0xAA))
FRAME_LEN = 29  # 55AA(2) + 数据 26B + 校验 1B
PAYLOAD_LEN = 26
TABLE_KEY = 'CPAZX'
CFG_FILE = 'XL-CPAZX-TeleMetryCfg.json'

_tm_cache = TmMgrFileCache()


def reset_xl_cpazx_tm_mgr() -> None:
    """清空 CPA 指向遥测 TeleMetryCfgManager 缓存。"""
    _tm_cache.clear()


def _frame_checksum(frame: bytes) -> int:
    """校验和：含帧头 55AA，对校验前全部字节累加。"""
    if len(frame) < 3:
        return 0
    return checksum_u8(frame[:-1])


def _get_tm_mgr(*, reload: bool = False):
    """加载 CPA 指向 TeleMetryCfgManager。"""
    return _tm_cache.get(
        CFG_FILE, reload=reload, error=f'CPA 指向遥测配置初始化失败: {CFG_FILE}'
    )


@dataclass(slots=True)
class ParsedXlCpazxTm:
    """校验并字段解析后的一帧（尚未落库）。"""

    table_key: str
    name: str
    fields: list[dict[str, Any]]
    raw_frame: bytes
    data_len: int
    size: int

    @property
    def raw_hex(self) -> str:
        """完整帧十六进制，空格分隔。"""
        return ' '.join(f'{b:02X}' for b in self.raw_frame)


class XlCpazxTmIngest:
    """CPA 指向遥测：55AA 定长拆帧 + 小端 TeleMetryParser + Redis。"""

    PARSER_ID = PARSER_TM_XL_CPAZX
    DATA_KIND = DATA_KIND_TM

    @classmethod
    def extract_frames(cls, data: bytes) -> list[bytes]:
        """提取完整遥测帧（粘包友好）。校验失败跳过本帧再往下搜。"""
        out: list[bytes] = []
        i = 0
        n = len(data)
        while i + FRAME_LEN <= n:
            idx = data.find(FRAME_HEADER, i)
            if idx < 0:
                break
            if idx + FRAME_LEN > n:
                break
            frame = data[idx : idx + FRAME_LEN]
            if _frame_checksum(frame) != frame[-1]:
                i = idx + 2
                continue
            out.append(frame)
            i = idx + FRAME_LEN
        return out

    @classmethod
    def io_preview_frames(cls, data: bytes) -> list[bytes]:
        """IO 预览：校验通过的完整 CPA 指向遥测帧。"""
        return cls.extract_frames(data)

    @classmethod
    def _complete_candidate(cls, data: bytes) -> bytes | None:
        """切出第一帧候选（不论校验是否通过），给数据模拟报校验原因。"""
        if len(data) < FRAME_LEN or data[0:2] != FRAME_HEADER:
            return None
        return data[:FRAME_LEN]

    @classmethod
    def _table_cfg(cls) -> dict[str, Any]:
        """从 PayloadConfigLoader 取 CPA 表显示配置。"""
        cfg = PayloadConfigLoader.get_xl_board_telemetry_cfg('cpazx')
        return (cfg.get('table') or {}).get(TABLE_KEY) or {}

    @classmethod
    def prepare_frame(cls, frame: bytes) -> PreparedTmFrame:
        """单帧校验拆包 → 待批处理帧（不做 TeleMetry 解析）。"""
        if frame[0:2] != FRAME_HEADER:
            raise ValueError('CPA指向遥测帧头不是55AA')
        if len(frame) != FRAME_LEN:
            raise ValueError(
                frame_len_mismatch('CPA指向遥测', PAYLOAD_LEN, FRAME_LEN, len(frame))
            )
        calc_sum = _frame_checksum(frame)
        if calc_sum != frame[-1]:
            raise ValueError(checksum_mismatch('CPA指向遥测', calc_sum, frame[-1]))
        payload = bytes(frame[2:-1])
        table = cls._table_cfg()
        mgr = _get_tm_mgr()
        return PreparedTmFrame(
            table_key=TABLE_KEY,
            name=table.get('name') or TABLE_KEY,
            payload=payload,
            raw_frame=bytes(frame),
            src_param='',
            src_kind='',
            parser_id=cls.PARSER_ID,
            mgr=mgr,
            data_kind=cls.DATA_KIND,
            big_endian_buffer=False,
        )

    @classmethod
    def parse_frame(cls, frame: bytes) -> ParsedXlCpazxTm:
        """完整帧 → TeleMetryParser 全量字段（调试/预览）。"""
        prepared = cls.prepare_frame(frame)
        fields = (
            prepared.mgr.parse(
                prepared.cfg_parse_key(),
                prepared.payload,
                big_endian_buffer=False,
            )
            or []
        )
        return ParsedXlCpazxTm(
            table_key=prepared.table_key,
            name=prepared.name,
            fields=fields,
            raw_frame=prepared.raw_frame,
            data_len=len(prepared.payload),
            size=len(prepared.raw_frame),
        )

    @classmethod
    def parse_bytes(cls, data: bytes) -> ParsedXlCpazxTm:
        """缓冲字节 → 最后一帧字段列表；允许粘包。"""
        frames = cls.extract_frames(data)
        if frames:
            return cls.parse_frame(frames[-1])
        cand = cls._complete_candidate(data)
        if cand is not None:
            return cls.parse_frame(cand)
        raise ValueError('未找到有效的 CPA指向遥测帧')

    @classmethod
    def _collect_prepared(cls, data: bytes) -> list[PreparedTmFrame]:
        """采集热路径：只收完整且校验通过的帧。"""
        frames = cls.extract_frames(data)
        if frames:
            return [cls.prepare_frame(fr) for fr in frames]
        return []

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
        assembler_id: str | None = None,
    ) -> dict[str, Any] | None:
        """硬件采集入口：拆帧后入批处理队列。"""
        del assembler_id
        pid = parser_id or cls.PARSER_ID
        sk = src_kind or infer_src_kind(src_param, SRC_KIND_SERIAL)
        try:
            prepared_list = cls._collect_prepared(data)
            if not prepared_list:
                return None
            for prepared in prepared_list:
                prepared.src_param = src_param
                prepared.src_kind = sk
                prepared.parser_id = pid
            return enqueue_prepared_many(redis_client, prepared_list, immediate=immediate)
        except ValueError as e:
            from module_payload.store.error_store import push_pipeline_error

            push_pipeline_error(
                redis_client,
                stage='xl_cpazx',
                message=str(e),
                device_id=src_param or '',
                parser_id=pid,
                data_len=len(data) if data is not None else None,
            )
            if quiet:
                return None
            raise

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
        """数据模拟等主进程入口。坏校验时对完整 29B 候选报校验和错误。"""
        pid = parser_id or cls.PARSER_ID
        sk = src_kind or infer_src_kind(src_param, SRC_KIND_SERIAL)
        prepared_list = cls._collect_prepared(data)
        if not prepared_list:
            cand = cls._complete_candidate(data)
            if cand is None:
                raise ValueError('未找到有效的 CPA指向遥测帧')
            prepared_list = [cls.prepare_frame(cand)]
        last: dict[str, Any] | None = None
        for prepared in prepared_list:
            prepared.src_param = src_param
            prepared.src_kind = sk
            prepared.parser_id = pid
            stored = await process_prepared_async(redis, [prepared]) or {}
            last = {
                'dataType': prepared.table_key,
                'dataLen': len(prepared.payload),
                'size': len(prepared.raw_frame),
                'fieldCount': len(stored.get('fields') or []),
                'name': stored.get('name', prepared.name),
                'ts': stored.get('ts', ''),
                'srcKind': sk,
                'srcParam': src_param,
                'parserId': pid,
            }
        if last is None:  # pragma: no cover
            raise ValueError('未找到有效的 CPA指向遥测帧')
        return last
