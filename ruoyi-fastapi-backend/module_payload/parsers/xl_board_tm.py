"""XL 单板遥测解释器（热控电机 / CPA-ZK / 地检板）。

本平台兼具：上位机地检 + 模拟星务。单板串口调试时可中途拦截，
帧的目的地址不一定是星务 0x11，故不对 dst 做校验，只按源地址分表。

串口/DEBUG EB90 帧（协议 V1.0.6 表格 11/13 等）：
  EB90 | len_be | src | dst | data… | chk
- len = 「长度字段之后～校验和之前」的字节数（src+dst+data）
- chk = 「长度字段～校验前」各字节累加和 & 0xFF（不含帧头 EB90）
- 源地址（谁发遥测）：0x33 主控板 → RKDJ（热控），0x44 CPA 驱动板 → ZK，
  0x77 地检板 → DJ（连本平台的地检板，勿称「上位机地检」）
- 目的地址：记录在字段里，不拦截（单板调试/截获场景）

地检 UDP 工程遥测：外层 eng_tm_subpkt（表格 4，0x1BCF）组帧后，
内层载荷走 DJ TeleMetryCfg；不靠本表 EB90 源地址分表。
延迟数据不入 MySQL（should_archive_tm_mysql 对 udp 为 False）。

同一套解析（拆帧 + TeleMetryCfg 字段），三条入口仅差「谁调用 / 写哪」：
- 硬件采集：collector → ingest_bytes_sync → 写 payload:tm:*
- 文件回放：fileplay.parse_frame → parse_bytes → 只写 payload:fileplay:*
- 数据模拟：HTTP → ingest_bytes_async → 写 payload:tm:*
字段解释都经 prepare_frame / parse_frame → mgr.parse，勿另写一套。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from redis import asyncio as aioredis

from module_payload.cfg.payload_config_loader import PayloadConfigLoader, XL_BOARD_TM_TABLE
from module_payload.error_text import checksum_mismatch, frame_len_mismatch
from module_payload.constants import (
    ASSEMBLER_ENG_TM_SUBPKT,
    DATA_KIND_TM,
    EB90_HEADER,
    PARSER_XL_BOARD_TM,
    SRC_KIND_SERIAL,
    XL_SRC_TO_TABLE,
    checksum_u8,
    infer_src_kind,
)
from module_payload.parsers.tm_ingest_batch import (
    PreparedTmFrame,
    enqueue_prepared_many,
    process_prepared_async,
)
from module_payload.parsers.tm_mgr_cache import TmMgrFileCache

FRAME_HEADER = EB90_HEADER

# 源设备编号 → 遥测 table key（分表只看源；目的不校验，见模块说明）
# 0x33 主控→热控 RKDJ；0x44 CPA→ZK；0x77 地检板→DJ
SRC_TO_TABLE: dict[int, str] = XL_SRC_TO_TABLE

# table key → TeleMetryCfg 文件名
TABLE_TO_CFG_FILE: dict[str, str] = {
    'RKDJ': 'XL-RKDJ-TeleMetryCfg.json',
    'ZK': 'XL-ZK-TeleMetryCfg.json',
    'DJ': 'XL-DJ-TeleMetryCfg.json',  # 地检：表格4组帧后的内层载荷；ZK 拷贝占位
}
# table key → PayloadConfigLoader 单板 id（避免每帧扫描全部 *-TeleMetryCfg）
TABLE_TO_BOARD: dict[str, str] = {v.upper(): k for k, v in XL_BOARD_TM_TABLE.items()}

_tm_caches: dict[str, TmMgrFileCache] = {}


def reset_xl_board_tm_mgr() -> None:
    """清空 XL 单板遥测 TeleMetryCfgManager 缓存。"""
    _tm_caches.clear()


_calc_checksum = checksum_u8


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
    """XL 单板遥测：拆帧校验 + TeleMetryParser + Redis/曲线（不入 MySQL）。

    硬件 / 文件回放 / 数据模拟共用本类；入口方法见模块说明。
    """

    PARSER_ID = PARSER_XL_BOARD_TM
    DATA_KIND = DATA_KIND_TM

    @classmethod
    def table_key_for_src(cls, src: int) -> str | None:
        """源地址 → 遥测表 key（未知源返回 None）。"""
        return SRC_TO_TABLE.get(int(src) & 0xFF)

    @classmethod
    def extract_frames(cls, data: bytes) -> list[bytes]:
        """提取完整遥测帧（粘包友好）。

        校验和失败会跳过本帧再往下搜：粘包时不能把后面的真帧丢掉。
        硬件实时采集因此不会因一包坏校验打断整段流。
        副作用：数据模拟若只贴一帧并改了末字节校验和，这里会得到空列表，
        不能当成「未找到帧」——须由 parse_bytes / ingest_bytes_async
        对完整 EB90 候选走 prepare_frame，报「校验和错误: 计算：xx， 帧内：xx」。
        """
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
    def io_preview_frames(cls, data: bytes) -> list[bytes]:
        """IO 预览：校验通过的完整单板遥测帧。"""
        return cls.extract_frames(data)

    @classmethod
    def _complete_eb90_candidate(cls, data: bytes) -> bytes | None:
        """按长度字段切出第一帧候选（不论校验是否通过）。

        给数据模拟用：帧本身结构完整、只是校验和或源地址不对时，
        extract_frames 会得到空列表（见上），这里仍切出候选交给 prepare_frame
        抛出真实原因，而不是「未找到有效的 XL 单板遥测帧」。
        """
        if len(data) < 7 or data[0:2] != FRAME_HEADER:
            return None
        body_len = (data[2] << 8) | data[3]
        if body_len < 2:
            return None
        total = 2 + 2 + body_len + 1
        if len(data) < total:
            return None
        return data[:total]

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
            raise ValueError(f'未知源地址 0x{src:02X}（期望主控 0x33 / CPA 0x44 / 地检板 0x77）')
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
    def prepare_assembled_payload(cls, data: bytes, *, table_key: str = 'DJ') -> PreparedTmFrame:
        """表格 4 组帧完成后的内层载荷：无 EB90 外壳，直接按 TeleMetryCfg 解析。

        地检 UDP 路径：eng_tm_subpkt 已剥掉 0x1BCF 帧头/校验/结束码，
        这里只把拼接后的「数据内容」交给 DJ 表（ZK 拷贝占位）。
        """
        key = (table_key or 'DJ').upper()
        table = cls._table_cfg(key)
        mgr = _get_tm_mgr(key)
        raw = bytes(data or b'')
        return PreparedTmFrame(
            table_key=key,
            name=table.get('name') or key,
            payload=raw,
            raw_frame=raw,
            src_param='',
            src_kind='',
            parser_id=cls.PARSER_ID,
            mgr=mgr,
            data_kind=cls.DATA_KIND,
            extra={'assembled': True, 'frameFmt': 'table4'},
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
        """缓冲字节 → 最后一帧字段列表；允许粘包。

        文件回放（fileplay）与部分预览走此入口；与硬件 ingest_bytes_sync
        共用 prepare_frame / TeleMetryCfg，不落 payload:tm:*。

        extract 为空时若缓冲是完整 EB90 帧，走 prepare_frame 报校验和/源地址，
        避免数据模拟把「改了末字节校验和」误报成未找到帧。
        """
        frames = cls.extract_frames(data)
        if frames:
            return cls.parse_frame(frames[-1])
        cand = cls._complete_eb90_candidate(data)
        if cand is not None:
            return cls.parse_frame(cand)
        raise ValueError('未找到有效的 XL 单板遥测帧')

    @classmethod
    def _collect_prepared(cls, data: bytes) -> list[PreparedTmFrame]:
        """采集热路径：只收完整且校验通过的帧；半截或坏校验返回空，不打断后续粘包。"""
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
        """硬件采集入口：拆帧后入批处理队列（默认 0.5s 刷写）。quiet 时校验失败只记错误。

        与文件回放 parse_bytes、数据模拟 ingest_bytes_async 同一套 prepare/cfg；
        本入口由 collector 调用，结果写 payload:tm:*。

        assembler_id=eng_tm_subpkt 时 data 已是表格 4 组帧后的内层载荷，
        不再按 EB90 单板帧拆包，直接走 DJ TeleMetryCfg。
        """
        pid = parser_id or cls.PARSER_ID
        sk = src_kind or infer_src_kind(src_param, SRC_KIND_SERIAL)
        try:
            if (assembler_id or '') == ASSEMBLER_ENG_TM_SUBPKT:
                prepared_list = [cls.prepare_assembled_payload(data, table_key='DJ')]
            else:
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
            from module_payload.store.error_store import push_pipeline_error

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
        """数据模拟等主进程入口：与硬件/文件回放同一套 prepare_frame + TeleMetryCfg。

        与硬件共用 extract_frames：坏校验会跳过。数据模拟只有一帧且改了末字节
        校验和时 extract 为空——对完整 EB90 候选再 prepare_frame，提示
        「XL 单板遥测 校验和错误: 计算：xx， 帧内：xx」，而不是未找到帧。
        硬件 ingest_bytes_sync 仍只走 _collect_prepared，坏帧跳过不打断后续流。
        """
        pid = parser_id or cls.PARSER_ID
        sk = src_kind or infer_src_kind(src_param, SRC_KIND_SERIAL)
        prepared_list = cls._collect_prepared(data)
        if not prepared_list:
            cand = cls._complete_eb90_candidate(data)
            if cand is None:
                raise ValueError('未找到有效的 XL 单板遥测帧')
            # 完整 EB90 帧但被 extract 丢掉：多半是校验和/源地址，把原因抛给数据模拟
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
        if last is None:
            raise ValueError('未找到有效的 XL 单板遥测帧')
        return last
