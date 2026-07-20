"""
CAN 遥测复合帧统一解析与落库（解释器 tm_can_yc）。

入口：
- 字节：真 CAN / 后续 UDP·串口组完后的完整帧
- HEX：开发测试 HTTP 注入

流程统一：严格校验(长度/校验和/帧类型) → TeleMetry 字段解析 → Redis 热层 → 归档队列。
遥测表类型(data_sub，如 FF)取自帧内 dataType 字节，不由 API 传入。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from redis import asyncio as aioredis

from module_payload.cfg.can_yc_frame import hex_to_bytes, verify_can_yc_frame
from module_payload.cfg.payload_config_loader import TELE_METRY_CFG_FILE
from module_payload.constants import (
    DATA_KIND_TM,
    PARSER_TM_CAN_YC,
    SRC_KIND_HTTP,
    infer_src_kind,
)
from module_payload import redis_keys as rk
from module_payload.service.payload_telemetry_archive_service import (
    PayloadTelemetryArchiveService,
    build_archive_event,
)

CURVE_MAX_POINTS = 50000

_tm_mgr = None


def _get_tm_mgr():
    global _tm_mgr
    if _tm_mgr is None:
        from TeleMetryParser import TeleMetryCfgManager

        mgr = TeleMetryCfgManager.instance()
        if not mgr.init(str(TELE_METRY_CFG_FILE)):
            raise RuntimeError('遥测配置初始化失败')
        _tm_mgr = mgr
    return _tm_mgr


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


@dataclass(slots=True)
class ParsedTmCanYc:
    """校验并字段解析后的一帧（尚未落库）。"""

    table_key: str
    name: str
    fields: list[dict[str, Any]]
    raw_hex: str
    data_len: int
    frame_type: str
    size: int


class TmCanYcIngest:
    """CAN 遥测复合帧解释器：解析 + Redis + 归档入队。"""

    PARSER_ID = PARSER_TM_CAN_YC
    DATA_KIND = DATA_KIND_TM

    # ------------------------------------------------------------------ 解析
    @classmethod
    def parse_bytes(cls, data: bytes) -> ParsedTmCanYc:
        """二进制完整帧 → 字段列表。校验失败或解析无结果抛 ValueError。"""
        ok, msg, frame = verify_can_yc_frame(data)
        if not ok:
            raise ValueError(msg)

        table_key = f'{frame[3]:02X}'
        # 与历史采集路径一致：dataType 之后到帧尾（含校验和）交给 parse_hex
        payload_hex = ' '.join(f'{b:02X}' for b in frame[4:])
        tm_mgr = _get_tm_mgr()
        lines = tm_mgr.parse_hex(table_key, payload_hex, include_datetime=False)
        if not lines:
            raise ValueError(f'遥测解析无结果: dataType=0x{table_key}')

        cfg = tm_mgr.get_table_cfg_by_key(table_key)
        fields: list[dict[str, Any]] = []
        for ln in lines:
            num = getattr(ln, 'val', None)
            raw = num.value() if num is not None and hasattr(num, 'value') else None
            fields.append(
                {
                    'id': getattr(ln, 'id', ''),
                    'name': getattr(ln, 'name', ''),
                    'value': raw,
                    'show': getattr(ln, 'show', ''),
                    'hex': getattr(ln, 'hex', ''),
                    'unit': getattr(ln, 'unit', ''),
                }
            )

        data_len = (frame[0] << 8) | frame[1]
        return ParsedTmCanYc(
            table_key=table_key,
            name=(cfg.name if cfg else table_key),
            fields=fields,
            raw_hex=' '.join(f'{b:02X}' for b in frame),
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

    # ------------------------------------------------------------------ 落库
    @classmethod
    def _build_latest_payload(
        cls,
        parsed: ParsedTmCanYc,
        *,
        src_kind: str,
        src_param: str,
        parser_id: str,
        ts: str,
        ts_ms: int,
    ) -> dict[str, Any]:
        return {
            'type': parsed.table_key,
            'name': parsed.name,
            'ts': ts,
            'dataId': ts_ms,
            'fields': parsed.fields,
            'dataKind': cls.DATA_KIND,
            'dataSub': parsed.table_key,
            'srcKind': src_kind,
            'srcParam': src_param,
            'parserId': parser_id,
        }

    @classmethod
    def _curve_members(
        cls, fields: list[dict[str, Any]], ts_ms: int
    ) -> list[tuple[str, dict[str, int]]]:
        out: list[tuple[str, dict[str, int]]] = []
        for row in fields:
            fid = row.get('id')
            if not fid:
                continue
            try:
                val = float(row.get('value', row.get('show', 0)))
            except (TypeError, ValueError):
                continue
            out.append((str(fid), {f'{ts_ms}|{val}': ts_ms}))
        return out

    @classmethod
    def store_sync(
        cls,
        redis_client: Any,
        parsed: ParsedTmCanYc,
        *,
        src_param: str,
        src_kind: str | None = None,
        parser_id: str | None = None,
    ) -> dict[str, Any]:
        """同步写 Redis 热层 + 归档队列（采集进程）。"""
        src_kind = src_kind or infer_src_kind(src_param)
        parser_id = parser_id or cls.PARSER_ID
        now = datetime.now()
        ts = now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        ts_ms = int(now.timestamp() * 1000)
        payload = cls._build_latest_payload(
            parsed, src_kind=src_kind, src_param=src_param, parser_id=parser_id, ts=ts, ts_ms=ts_ms
        )
        dumped = _dumps(payload)
        tkey = parsed.table_key
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
        parsed: ParsedTmCanYc,
        *,
        src_param: str,
        src_kind: str | None = None,
        parser_id: str | None = None,
    ) -> dict[str, Any]:
        """异步写 Redis 热层 + 归档队列（FastAPI 主进程）。"""
        from module_payload.redis_store import append_curve_points, set_telemetry

        src_kind = src_kind or infer_src_kind(src_param)
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

    # ------------------------------------------------------------------ 一站式
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
        """
        采集侧：解析并落库。
        quiet=True 时校验/解析失败返回 None（不打断收包循环）；否则抛 ValueError。
        """
        try:
            parsed = cls.parse_bytes(data)
        except ValueError:
            if quiet:
                return None
            raise
        return cls.store_sync(
            redis_client, parsed, src_param=src_param, src_kind=src_kind, parser_id=parser_id
        )

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
        """HTTP 注入：HEX → 解析 → 落库。失败抛 ValueError。"""
        parsed = cls.parse_hex(hex_text)
        stored = await cls.store_async(
            redis, parsed, src_param=src_param, src_kind=src_kind, parser_id=parser_id
        )
        return {
            'dataType': parsed.table_key,
            'frameType': parsed.frame_type,
            'dataLen': parsed.data_len,
            'size': parsed.size,
            'fieldCount': len(parsed.fields),
            'name': stored.get('name', parsed.name),
            'ts': stored.get('ts', ''),
            'srcKind': src_kind,
            'srcParam': src_param,
            'parserId': parser_id or cls.PARSER_ID,
        }

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
        """主进程二进制入口（后续 UDP/串口模拟可复用）。"""
        parsed = cls.parse_bytes(data)
        stored = await cls.store_async(
            redis, parsed, src_param=src_param, src_kind=src_kind, parser_id=parser_id
        )
        return {
            'dataType': parsed.table_key,
            'frameType': parsed.frame_type,
            'dataLen': parsed.data_len,
            'size': parsed.size,
            'fieldCount': len(parsed.fields),
            'name': stored.get('name', parsed.name),
            'ts': stored.get('ts', ''),
            'srcKind': src_kind or infer_src_kind(src_param),
            'srcParam': src_param,
            'parserId': parser_id or cls.PARSER_ID,
        }
