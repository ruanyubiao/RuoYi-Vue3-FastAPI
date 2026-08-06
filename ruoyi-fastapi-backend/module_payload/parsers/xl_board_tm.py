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

from module_payload.cfg.payload_config_loader import PayloadConfigLoader
from module_payload.constants import (
    CURVE_MAX_POINTS,
    DATA_KIND_TM,
    PARSER_XL_BOARD_TM,
    SRC_KIND_SERIAL,
    infer_src_kind,
)
from module_payload.service.payload_telemetry_archive_service import (
    PayloadTelemetryArchiveService,
    build_archive_event,
)

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

_tm_mgrs: dict[str, Any] = {}
_tm_mgr_paths: dict[str, str] = {}


def reset_xl_board_tm_mgr() -> None:
    """清空 XL 单板遥测 TeleMetryCfgManager 缓存。"""
    _tm_mgrs.clear()
    _tm_mgr_paths.clear()


def _calc_checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def _frame_checksum(frame: bytes) -> int:
    """校验和：不含帧头 EB90，对长度字段～校验前累加。"""
    if len(frame) < 4:
        return 0
    return _calc_checksum(frame[2:-1])


def _cfg_path_for_table(table_key: str) -> Path:
    from module_payload.cfg.payload_config_loader import CONFIG_DIR

    name = TABLE_TO_CFG_FILE.get(table_key.upper())
    if not name:
        raise ValueError(f'未知 XL 单板遥测表: {table_key}')
    return CONFIG_DIR / name


def _get_tm_mgr(table_key: str, *, reload: bool = False):
    from TeleMetryParser import TeleMetryCfgManager

    key = table_key.upper()
    path = str(_cfg_path_for_table(key))
    if reload or key not in _tm_mgrs or _tm_mgr_paths.get(key) != path:
        mgr = TeleMetryCfgManager()
        if not mgr.init(path):
            raise RuntimeError(f'XL 单板遥测配置初始化失败: {path}')
        _tm_mgrs[key] = mgr
        _tm_mgr_paths[key] = path
    return _tm_mgrs[key]


@dataclass(slots=True)
class ParsedXlBoardTm:
    table_key: str
    name: str
    fields: list[dict[str, Any]]
    raw_hex: str
    data_len: int
    src: int
    dst: int
    size: int


class XlBoardTmIngest:
    """XL 单板遥测：拆帧校验 + TeleMetryParser + Redis/曲线/归档。"""

    PARSER_ID = PARSER_XL_BOARD_TM
    DATA_KIND = DATA_KIND_TM

    @classmethod
    def table_key_for_src(cls, src: int) -> str | None:
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
                i = idx + 2
                continue
            total = 2 + 2 + body_len + 1
            if idx + total > len(data):
                break
            frame = data[idx : idx + total]
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
    def parse_frame(cls, frame: bytes) -> ParsedXlBoardTm:
        if len(frame) < 7 or frame[0:2] != FRAME_HEADER:
            raise ValueError('XL 单板遥测帧头不是EB90')
        body_len = (frame[2] << 8) | frame[3]
        calc_total_len = 2 + 2 + body_len + 1
        if len(frame) != calc_total_len:
            raise ValueError(f'XL 单板遥测帧长不符: 数据长度：{body_len}， 解析总长度：{calc_total_len}，实际总长度：{len(frame)}')
        calc_sum = _frame_checksum(frame)
        if calc_sum != frame[-1]:
            raise ValueError(f'XL 单板遥测校验和错误: 计算：{calc_sum:02X}， 帧内：{frame[-1]:02X}')
        src = frame[4]
        dst = frame[5]
        table_key = cls.table_key_for_src(src)
        if not table_key:
            raise ValueError(f'未知源地址 0x{src:02X}')
        payload = frame[6 : 6 + (body_len - 2)]
        return cls._parse_payload(payload, raw_frame=frame, table_key=table_key, src=src, dst=dst)

    @classmethod
    def _table_cfg(cls, table_key: str) -> dict[str, Any]:
        return PayloadConfigLoader.find_telemetry_table(table_key) or {}

    @classmethod
    def _parse_payload(
        cls,
        payload: bytes,
        *,
        raw_frame: bytes,
        table_key: str,
        src: int,
        dst: int,
    ) -> ParsedXlBoardTm:
        table = cls._table_cfg(table_key)
        mgr = _get_tm_mgr(table_key)
        payload_hex = ' '.join(f'{b:02X}' for b in payload)
        lines = mgr.parse_hex(table_key, payload_hex, include_datetime=False)
        from module_payload.parsers.tm_field_util import line_to_field_dict

        fields: list[dict[str, Any]] = [line_to_field_dict(ln) for ln in lines]
        row_by_id = {str(r.get('id')): r for r in (table.get('row') or [])}
        for f in fields:
            cfg_row = row_by_id.get(f['id']) or {}
            if cfg_row.get('unit'):
                f['unit'] = cfg_row['unit']
        return ParsedXlBoardTm(
            table_key=table_key,
            name=table.get('name') or table_key,
            fields=fields,
            raw_hex=' '.join(f'{b:02X}' for b in raw_frame),
            data_len=len(payload),
            src=src,
            dst=dst,
            size=len(raw_frame),
        )

    @classmethod
    def parse_bytes(cls, data: bytes) -> ParsedXlBoardTm:
        frames = cls.extract_frames(data)
        if frames:
            return cls.parse_frame(frames[-1])
        if len(data) >= 7 and data[0:2] == FRAME_HEADER:
            return cls.parse_frame(data)
        raise ValueError('未找到有效的 XL 单板遥测帧')

    @classmethod
    def _curve_members(
        cls, fields: list[dict[str, Any]], ts_ms: int
    ) -> list[tuple[str, dict[str, int]]]:
        from module_payload.parsers.tm_field_util import curve_numeric

        out: list[tuple[str, dict[str, int]]] = []
        for row in fields:
            fid = row.get('id')
            if not fid:
                continue
            val = curve_numeric(row)
            if val is None:
                continue
            out.append((str(fid), {f'{ts_ms}|{val}': ts_ms}))
        return out

    @classmethod
    def store_sync(
        cls,
        redis_client: Any,
        parsed: ParsedXlBoardTm,
        *,
        src_param: str,
        src_kind: str | None = None,
        parser_id: str | None = None,
    ) -> dict[str, Any]:
        from datetime import datetime

        from module_payload import redis_keys as rk
        from module_payload.collectors.redis_sync import dumps_json

        src_kind = src_kind or infer_src_kind(src_param, SRC_KIND_SERIAL)
        parser_id = parser_id or cls.PARSER_ID
        now = datetime.now()
        ts = now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        ts_ms = int(now.timestamp() * 1000)
        tkey = parsed.table_key
        payload = {
            'type': tkey,
            'name': parsed.name,
            'ts': ts,
            'dataId': ts_ms,
            'fields': parsed.fields,
            'dataKind': cls.DATA_KIND,
            'dataSub': tkey,
            'srcKind': src_kind,
            'srcParam': src_param,
            'parserId': parser_id,
            'srcAddr': parsed.src,
            'dstAddr': parsed.dst,
        }
        dumped = dumps_json(payload)
        redis_client.set(rk.telemetry_latest_key(tkey), dumped)
        redis_client.set(rk.telemetry_latest_ts_key(tkey), ts)

        members = cls._curve_members(parsed.fields, ts_ms)
        if members:
            pipe = redis_client.pipeline(transaction=False)
            for fid, member in members:
                lkey = rk.curve_latest_key(tkey, fid)
                pipe.zadd(lkey, member)
                pipe.zremrangebyrank(lkey, 0, -(CURVE_MAX_POINTS + 1))
            pipe.execute()

        PayloadTelemetryArchiveService.enqueue_sync(
            redis_client,
            build_archive_event(
                data_sub=tkey,
                ts_ms=ts_ms,
                raw_hex=parsed.raw_hex,
                fields=parsed.fields,
                name=parsed.name,
                src_kind=src_kind,
                src_param=src_param,
                parser_id=parser_id,
            ),
        )
        return payload

    @classmethod
    async def store_async(
        cls,
        redis: aioredis.Redis,
        parsed: ParsedXlBoardTm,
        *,
        src_param: str,
        src_kind: str | None = None,
        parser_id: str | None = None,
    ) -> dict[str, Any]:
        from module_payload.redis_store import append_curve_points, set_telemetry

        src_kind = src_kind or infer_src_kind(src_param, SRC_KIND_SERIAL)
        parser_id = parser_id or cls.PARSER_ID
        stored = await set_telemetry(
            redis,
            parsed.table_key,
            parsed.fields,
            parsed.name,
            src_kind=src_kind,
            src_param=src_param,
            parser_id=parser_id,
            data_kind=cls.DATA_KIND,
        )
        await append_curve_points(redis, parsed.table_key, parsed.fields, stored.get('ts', ''))
        ts_ms = int(stored.get('dataId') or 0)
        if ts_ms:
            await PayloadTelemetryArchiveService.enqueue(
                redis,
                build_archive_event(
                    data_sub=parsed.table_key,
                    ts_ms=ts_ms,
                    raw_hex=parsed.raw_hex,
                    fields=parsed.fields,
                    name=parsed.name,
                    src_kind=src_kind,
                    src_param=src_param,
                    parser_id=parser_id,
                ),
            )
        return stored

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
    ) -> dict[str, Any] | None:
        pid = parser_id or cls.PARSER_ID
        try:
            frames = cls.extract_frames(data)
            if not frames:
                parsed = cls.parse_bytes(data)
                return cls.store_sync(
                    redis_client, parsed, src_param=src_param, src_kind=src_kind, parser_id=pid
                )
            last = None
            for fr in frames:
                parsed = cls.parse_frame(fr)
                last = cls.store_sync(
                    redis_client, parsed, src_param=src_param, src_kind=src_kind, parser_id=pid
                )
            return last
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
        frames = cls.extract_frames(data)
        if not frames:
            parsed = cls.parse_bytes(data)
            stored = await cls.store_async(
                redis, parsed, src_param=src_param, src_kind=src_kind, parser_id=pid
            )
            return {
                'dataType': parsed.table_key,
                'dataLen': parsed.data_len,
                'size': parsed.size,
                'fieldCount': len(parsed.fields),
                'name': stored.get('name', parsed.name),
                'ts': stored.get('ts', ''),
                'srcKind': src_kind or infer_src_kind(src_param, SRC_KIND_SERIAL),
                'srcParam': src_param,
                'parserId': pid,
            }
        last: dict[str, Any] | None = None
        for fr in frames:
            parsed = cls.parse_frame(fr)
            stored = await cls.store_async(
                redis, parsed, src_param=src_param, src_kind=src_kind, parser_id=pid
            )
            last = {
                'dataType': parsed.table_key,
                'dataLen': parsed.data_len,
                'size': parsed.size,
                'fieldCount': len(parsed.fields),
                'name': stored.get('name', parsed.name),
                'ts': stored.get('ts', ''),
                'srcKind': src_kind or infer_src_kind(src_param, SRC_KIND_SERIAL),
                'srcParam': src_param,
                'parserId': pid,
            }
        if last is None:
            raise ValueError('未找到有效的 XL 单板遥测帧')
        return last
