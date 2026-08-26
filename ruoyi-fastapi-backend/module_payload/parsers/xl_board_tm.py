"""XL 单板遥测解释器（热控电机 / CPA-ZK 等）。

遥测帧：EB90 | len_be | src | dst | data… | chk
- len = 「长度字段之后～校验和之前」的字节数（src+dst+data）
- chk = 「长度字段～校验前」各字节累加和 & 0xFF（不含帧头 EB90）
- 源地址为子类型：0x93→RKDJ，0x92→ZK
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from redis import asyncio as aioredis

from module_payload.cfg.payload_config_loader import PayloadConfigLoader, XL_BOARD_TM_TABLE
from module_payload.error_text import checksum_mismatch, frame_len_mismatch
from module_payload.constants import (
    DATA_KIND_TM,
    PARSER_XL_BOARD_TM,
    SRC_KIND_SERIAL,
    infer_src_kind,
)
from module_payload.parsers.tm_ingest_batch import (
    PreparedTmFrame,
    enqueue_prepared_many,
    process_prepared_async,
)
from module_payload.parsers.tm_mgr_cache import TmMgrFileCache

FRAME_HEADER = bytes([0xEB, 0x90])

# 源地址 → 遥测 table key
SRC_TO_TABLE: dict[int, str] = {
    0x93: 'RKDJ',
    0x92: 'ZK',
}

# table key → TeleMetryCfg 文件名
TABLE_TO_CFG_FILE: dict[str, str] = {
    'RKDJ': 'XL-RKDJ-TeleMetryCfg.json',
    'ZK': 'XL-ZK-TeleMetryCfg.json',
}
# table key → PayloadConfigLoader 单板 id（避免每帧扫描全部 *-TeleMetryCfg）
TABLE_TO_BOARD: dict[str, str] = {v.upper(): k for k, v in XL_BOARD_TM_TABLE.items()}

_tm_caches: dict[str, TmMgrFileCache] = {}


def reset_xl_board_tm_mgr() -> None:
    """清空 XL 单板遥测 TeleMetryCfgManager 缓存。"""
    _tm_caches.clear()


def _calc_checksum(data: bytes) -> int:
    """协议校验：参与字节求和后取低 8 位。"""
    return sum(data) & 0xFF


def _frame_checksum(frame: bytes) -> int:
    """校验和：不含帧头 EB90，对长度字段～校验前累加。"""
    if len(frame) < 4:
        return 0
    return _calc_checksum(frame[2:-1])


def _cfg_path_for_table(table_key: str) -> Path:
    """按 table key 解析 TeleMetryCfg 文件路径。"""
    from config.paths import resolve_config_file

    name = TABLE_TO_CFG_FILE.get(table_key.upper())
    if not name:
        raise ValueError(f'未知 XL 单板遥测表: {table_key}')
    return resolve_config_file(name)


def _get_tm_mgr(table_key: str, *, reload: bool = False):
    """按表加载 TeleMetryCfgManager（进程内文件缓存）。"""
    key = table_key.upper()
    name = TABLE_TO_CFG_FILE.get(key)
    if not name:
        raise ValueError(f'未知 XL 单板遥测表: {table_key}')
    cache = _tm_caches.setdefault(key, TmMgrFileCache())
    return cache.get(name, reload=reload, error=f'XL 单板遥测配置初始化失败: {name}')


@dataclass(slots=True)
class ParsedXlBoardTm:
    """校验并字段解析后的一帧（尚未落库）。"""

    table_key: str
    name: str
    fields: list[dict[str, Any]]
    raw_frame: bytes
    data_len: int
    src: int
    dst: int
    size: int

    @property
    def raw_hex(self) -> str:
        """完整帧十六进制，空格分隔。"""
        return ' '.join(f'{b:02X}' for b in self.raw_frame)


class XlBoardTmIngest:
    """XL 单板遥测：拆帧校验 + TeleMetryParser + Redis/曲线（不入 MySQL）。"""

    PARSER_ID = PARSER_XL_BOARD_TM
    DATA_KIND = DATA_KIND_TM

    @classmethod
    def table_key_for_src(cls, src: int) -> str | None:
        """源地址 → 遥测表 key（未知源返回 None）。"""
        return SRC_TO_TABLE.get(int(src) & 0xFF)

    @classmethod
    def extract_frames(cls, data: bytes) -> list[bytes]:
        """提取完整遥测帧（粘包友好）。"""
        out: list[bytes] = []
        i = 0
        while i + 6 <= len(data):
            idx = data.find(FRAME_HEADER, i)
            if idx < 0:
                break
            if idx + 5 > len(data):
                break
            body_len = (data[idx + 2] << 8) | data[idx + 3]
            if body_len < 2:
                i = idx + 2  # 长度非法：滑过帧头继续搜
                continue
            total = 2 + 2 + body_len + 1
            if idx + total > len(data):
                break  # 半截帧留给下次粘包
            frame = data[idx : idx + total]
            # 校验失败前进 2 字节再搜，避免错同步后把后续真帧也丢掉
            if _frame_checksum(frame) != frame[-1]:
                i = idx + 2
                continue
            src = frame[4]
            if src not in SRC_TO_TABLE:
                i = idx + 2
                continue
            out.append(frame)
            i = idx + total
        return out

    @classmethod
    def _table_cfg(cls, table_key: str) -> dict[str, Any]:
        """从 PayloadConfigLoader 取该表的显示配置。"""
        board = TABLE_TO_BOARD.get((table_key or '').upper())
        if not board:
            return {}
        cfg = PayloadConfigLoader.get_xl_board_telemetry_cfg(board)
        return (cfg.get('table') or {}).get(table_key.upper()) or {}

    @classmethod
    def prepare_frame(cls, frame: bytes) -> PreparedTmFrame:
        """单帧校验拆包 → 待批处理帧（不做 TeleMetry 解析）。"""
        if len(frame) < 7 or frame[0:2] != FRAME_HEADER:
            raise ValueError('XL 单板遥测帧头不是EB90')
        body_len = (frame[2] << 8) | frame[3]
        calc_total_len = 2 + 2 + body_len + 1
        if len(frame) != calc_total_len:
            raise ValueError(frame_len_mismatch('XL 单板遥测', body_len, calc_total_len, len(frame)))
        calc_sum = _frame_checksum(frame)
        if calc_sum != frame[-1]:
            raise ValueError(checksum_mismatch('XL 单板遥测', calc_sum, frame[-1]))
        src = frame[4]
        dst = frame[5]
        table_key = cls.table_key_for_src(src)
        if not table_key:
            raise ValueError(f'未知源地址 0x{src:02X}')
        payload = bytes(frame[6 : 6 + (body_len - 2)])
        table = cls._table_cfg(table_key)
        mgr = _get_tm_mgr(table_key)
        return PreparedTmFrame(
            table_key=table_key,
            name=table.get('name') or table_key,
            payload=payload,
            raw_frame=bytes(frame),
            src_param='',
            src_kind='',
            parser_id=cls.PARSER_ID,
            mgr=mgr,
            data_kind=cls.DATA_KIND,
            extra={'srcAddr': src, 'dstAddr': dst},
        )

    @classmethod
    def parse_frame(cls, frame: bytes) -> ParsedXlBoardTm:
        """完整帧 → TeleMetryParser 全量字段（调试/预览）。"""
        prepared = cls.prepare_frame(frame)
        fields = prepared.mgr.parse(prepared.table_key, prepared.payload) or []
        return ParsedXlBoardTm(
            table_key=prepared.table_key,
            name=prepared.name,
            fields=fields,
            raw_frame=prepared.raw_frame,
            data_len=len(prepared.payload),
            src=int(prepared.extra.get('srcAddr') or 0),
            dst=int(prepared.extra.get('dstAddr') or 0),
            size=len(prepared.raw_frame),
        )

    @classmethod
    def parse_bytes(cls, data: bytes) -> ParsedXlBoardTm:
        """缓冲字节 → 最后一帧字段列表；允许粘包。"""
        frames = cls.extract_frames(data)
        if frames:
            return cls.parse_frame(frames[-1])
        if len(data) >= 7 and data[0:2] == FRAME_HEADER:
            return cls.parse_frame(data)
        raise ValueError('未找到有效的 XL 单板遥测帧')

    @classmethod
    def _collect_prepared(cls, data: bytes) -> list[PreparedTmFrame]:
        """采集热路径：只收完整帧；半截块返回空。"""
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
    ) -> dict[str, Any] | None:
        """采集侧：拆帧后入批处理队列（默认 0.5s 刷写）。quiet 时校验失败只记错误。"""
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
            # Redis 入队：采集线程不 parse
            return enqueue_prepared_many(redis_client, prepared_list, immediate=immediate)
        except ValueError as e:
            from module_payload.service.payload_error_store import push_pipeline_error

            push_pipeline_error(
                redis_client,
                stage='xl_board',
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
        """主进程二进制入口（数据模拟 / 串口采集共用）。"""
        pid = parser_id or cls.PARSER_ID
        sk = src_kind or infer_src_kind(src_param, SRC_KIND_SERIAL)
        prepared_list = cls._collect_prepared(data)
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
        if last is None:
            raise ValueError('未找到有效的 XL 单板遥测帧')
        return last
