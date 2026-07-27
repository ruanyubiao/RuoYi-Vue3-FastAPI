"""SC-LINK41EP 串口遥测解释器：慢遥 0xD8、快遥 0xD9。

帧头/校验在本模块处理；字段解析交给 TeleMetryParser（只传入数据区）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from redis import asyncio as aioredis

from module_payload.cfg.payload_config_loader import CAMERA_TELE_METRY_CFG_FILE, PayloadConfigLoader
from module_payload.constants import (
    CURVE_MAX_POINTS,
    DATA_KIND_TM,
    PARSER_CAMERA_SC_LINK41EP,
    SRC_KIND_SERIAL,
    infer_src_kind,
)
from module_payload.service.payload_telemetry_archive_service import (
    PayloadTelemetryArchiveService,
    build_archive_event,
)

FRAME_HEADER = bytes([0xEB, 0x90])
FRAME_TYPE_D8 = 0xD8
FRAME_TYPE_D9 = 0xD9
D8_DATA_LEN = 0x002D
D8_FRAME_MIN = 2 + 1 + 1 + 2 + 2 + D8_DATA_LEN + 1  # 54
D9_FRAME_LEN = 20  # EB | D9 | seq | data(16) | chk
D9_DATA_LEN = 16

# 独立实例，避免覆盖 CAN 用的 TeleMetryCfgManager.instance()
_cam_tm_mgr = None
_cam_tm_mgr_path: str | None = None


def reset_cam_tm_mgr() -> None:
    """清空相机遥测 TeleMetryCfgManager 缓存。"""
    global _cam_tm_mgr, _cam_tm_mgr_path
    _cam_tm_mgr = None
    _cam_tm_mgr_path = None


def _calc_checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def _get_cam_tm_mgr(*, reload: bool = False):
    """加载 XL-Camera-TeleMetryCfg.json 的 TeleMetryParser 管理器（非单例）。"""
    global _cam_tm_mgr, _cam_tm_mgr_path
    from TeleMetryParser import TeleMetryCfgManager

    path = str(CAMERA_TELE_METRY_CFG_FILE)
    if reload or _cam_tm_mgr is None or _cam_tm_mgr_path != path:
        mgr = TeleMetryCfgManager()
        if not mgr.init(path):
            raise RuntimeError(f'相机遥测配置初始化失败: {path}')
        _cam_tm_mgr = mgr
        _cam_tm_mgr_path = path
    return _cam_tm_mgr


@dataclass(slots=True)
class ParsedCameraTm:
    table_key: str
    name: str
    fields: list[dict[str, Any]]
    raw_hex: str
    data_len: int
    frame_type: str
    size: int


class CameraScLink41epIngest:
    """串口1 慢遥测 D8 / 快遥测 D9：拆帧校验 + TeleMetryParser 字段解析 + Redis。"""

    PARSER_ID = PARSER_CAMERA_SC_LINK41EP
    DATA_KIND = DATA_KIND_TM

    @classmethod
    def _table_cfg(cls, table_key: str = 'D8', reload: bool = False) -> dict[str, Any]:
        cfg = PayloadConfigLoader.get_camera_telemetry_cfg(reload=reload)
        if reload:
            _get_cam_tm_mgr(reload=True)
        return (cfg.get('table') or {}).get(table_key) or {}

    @classmethod
    def extract_d8_frames(cls, data: bytes) -> list[bytes]:
        """从缓冲中提取完整 D8 帧（可能粘包）。"""
        out: list[bytes] = []
        i = 0
        while i + D8_FRAME_MIN <= len(data):
            idx = data.find(FRAME_HEADER, i)
            if idx < 0:
                break
            if idx + D8_FRAME_MIN > len(data):
                break
            if data[idx + 2] != FRAME_TYPE_D8:
                i = idx + 2
                continue
            data_len = (data[idx + 4] << 8) | data[idx + 5]
            total = 2 + 1 + 1 + 2 + 2 + data_len + 1
            if idx + total > len(data):
                break
            out.append(data[idx : idx + total])
            i = idx + total
        return out

    @classmethod
    def extract_d9_frames(cls, data: bytes) -> list[bytes]:
        """快遥：EB D9 seq data[16] chk，总长 20；校验覆盖序号~数据（1-based 3~19）。"""
        out: list[bytes] = []
        i = 0
        while i + D9_FRAME_LEN <= len(data):
            idx = data.find(bytes([0xEB, FRAME_TYPE_D9]), i)
            if idx < 0:
                break
            if idx + D9_FRAME_LEN > len(data):
                break
            frame = data[idx : idx + D9_FRAME_LEN]
            if _calc_checksum(frame[2:19]) != frame[19]:
                i = idx + 1
                continue
            out.append(frame)
            i = idx + D9_FRAME_LEN
        return out

    @classmethod
    def parse_bytes(cls, data: bytes) -> ParsedCameraTm:
        frames = cls.extract_d8_frames(data)
        if frames:
            return cls._parse_d8_frame(frames[-1])
        frames9 = cls.extract_d9_frames(data)
        if frames9:
            return cls._parse_d9_frame(frames9[-1])
        if len(data) >= D8_FRAME_MIN and data[0:2] == FRAME_HEADER and data[2] == FRAME_TYPE_D8:
            return cls._parse_d8_frame(data[: D8_FRAME_MIN if len(data) >= D8_FRAME_MIN else len(data)])
        if len(data) >= D9_FRAME_LEN and data[0] == 0xEB and data[1] == FRAME_TYPE_D9:
            return cls._parse_d9_frame(data[:D9_FRAME_LEN])
        if len(data) >= D8_DATA_LEN:
            return cls._parse_payload(data[:D8_DATA_LEN], raw_frame=data, table_key='D8')
        raise ValueError('未找到有效的相机遥测帧(D8/D9)')

    @classmethod
    def _parse_d8_frame(cls, frame: bytes) -> ParsedCameraTm:
        if len(frame) < D8_FRAME_MIN:
            raise ValueError(f'D8 帧过短: {len(frame)}')
        if frame[0:2] != FRAME_HEADER or frame[2] != FRAME_TYPE_D8:
            raise ValueError('D8 帧头/类型错误')
        data_len = (frame[4] << 8) | frame[5]
        if data_len < D8_DATA_LEN:
            raise ValueError(f'D8 数据长度异常: 0x{data_len:04X}')
        payload = frame[8 : 8 + data_len]
        chk = frame[8 + data_len]
        if _calc_checksum(frame[2 : 8 + data_len]) != chk:
            raise ValueError('D8 校验和错误')
        return cls._parse_payload(payload[:D8_DATA_LEN], raw_frame=frame, table_key='D8')

    @classmethod
    def _parse_d9_frame(cls, frame: bytes) -> ParsedCameraTm:
        if len(frame) < D9_FRAME_LEN:
            raise ValueError(f'D9 帧过短: {len(frame)}')
        if frame[0] != 0xEB or frame[1] != FRAME_TYPE_D9:
            raise ValueError('D9 帧头/类型错误')
        if _calc_checksum(frame[2:19]) != frame[19]:
            raise ValueError('D9 校验和错误')
        payload = frame[3:19]
        return cls._parse_payload(payload, raw_frame=frame, table_key='D9')

    @classmethod
    def _parse_payload(cls, payload: bytes, *, raw_frame: bytes, table_key: str) -> ParsedCameraTm:
        """仅把数据区交给 TeleMetryParser。"""
        table = cls._table_cfg(table_key)
        mgr = _get_cam_tm_mgr()
        payload_hex = ' '.join(f'{b:02X}' for b in payload)
        lines = mgr.parse_hex(table_key, payload_hex, include_datetime=False)
        fields: list[dict[str, Any]] = []
        for ln in lines:
            num = getattr(ln, 'val', None)
            raw = num.value() if num is not None and hasattr(num, 'value') else None
            fields.append(
                {
                    'id': getattr(ln, 'id', '') or '',
                    'name': getattr(ln, 'name', '') or '',
                    'value': raw,
                    'show': getattr(ln, 'show', '') or '',
                    'hex': getattr(ln, 'hex', '') or '',
                    'unit': '',
                }
            )
        row_by_id = {str(r.get('id')): r for r in (table.get('row') or [])}
        for f in fields:
            cfg_row = row_by_id.get(f['id']) or {}
            if cfg_row.get('unit'):
                f['unit'] = cfg_row['unit']
        return ParsedCameraTm(
            table_key=table_key,
            name=table.get('name') or ('快遥测(开窗)' if table_key == 'D9' else '慢遥测(全窗)'),
            fields=fields,
            raw_hex=' '.join(f'{b:02X}' for b in raw_frame),
            data_len=len(payload),
            frame_type=table_key,
            size=len(raw_frame),
        )

    @classmethod
    def parse_hex(cls, hex_text: str) -> ParsedCameraTm:
        from module_payload.cfg.telecontrol_assembler import hex_to_bytes

        return cls.parse_bytes(hex_to_bytes(hex_text))

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
        parsed: ParsedCameraTm,
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
        parsed: ParsedCameraTm,
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
            frames8 = cls.extract_d8_frames(data)
            frames9 = cls.extract_d9_frames(data)
            if not frames8 and not frames9:
                parsed = cls.parse_bytes(data)
                return cls.store_sync(
                    redis_client, parsed, src_param=src_param, src_kind=src_kind, parser_id=pid
                )
            last = None
            for fr in frames8:
                parsed = cls._parse_d8_frame(fr)
                last = cls.store_sync(
                    redis_client, parsed, src_param=src_param, src_kind=src_kind, parser_id=pid
                )
            for fr in frames9:
                parsed = cls._parse_d9_frame(fr)
                last = cls.store_sync(
                    redis_client, parsed, src_param=src_param, src_kind=src_kind, parser_id=pid
                )
            return last
        except ValueError as e:
            from module_payload.service.payload_error_store import push_pipeline_error

            push_pipeline_error(
                redis_client,
                stage='camera',
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
            'parserId': parser_id or cls.PARSER_ID,
        }
