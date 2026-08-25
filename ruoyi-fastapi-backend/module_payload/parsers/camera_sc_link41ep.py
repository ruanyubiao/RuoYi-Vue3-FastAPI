"""SC-LINK41EP 串口遥测解释器：慢遥 0xD8、快遥 0xD9。

帧头/校验在本模块处理；字段解析交给 TeleMetryParser（只传入数据区 bytes）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from redis import asyncio as aioredis

from module_payload.cfg.payload_config_loader import CAMERA_TELE_METRY_CFG_NAME, PayloadConfigLoader
from module_payload.error_text import checksum_mismatch, frame_len_mismatch
from module_payload.constants import (
    DATA_KIND_TM,
    PARSER_CAMERA_SC_LINK41EP,
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
FRAME_TYPE_D8 = 0xD8
FRAME_TYPE_D9 = 0xD9
FRAME_D9_HEADER = bytes([0xEB, FRAME_TYPE_D9])
D8_DATA_LEN = 0x002D
D8_FRAME_MIN = 2 + 1 + 1 + 2 + 2 + D8_DATA_LEN + 1  # 54
D9_FRAME_LEN = 20  # EB | D9 | seq | data(16) | chk
D9_DATA_LEN = 16

_cam_tm_cache = TmMgrFileCache()
_TABLE_NAMES: dict[str, str] = {}


def reset_cam_tm_mgr() -> None:
    """清空相机遥测 TeleMetryCfgManager 缓存。"""
    _cam_tm_cache.clear()
    _TABLE_NAMES.clear()


def _calc_checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def _ensure_bytes(data: bytes | bytearray | memoryview) -> bytes:
    return data if type(data) is bytes else bytes(data)


def _get_cam_tm_mgr(*, reload: bool = False):
    """加载 XL-Camera-TeleMetryCfg.json 的 TeleMetryParser 管理器（非单例）。"""
    return _cam_tm_cache.get(
        CAMERA_TELE_METRY_CFG_NAME,
        reload=reload,
        error=f'相机遥测配置初始化失败: {CAMERA_TELE_METRY_CFG_NAME}',
    )


@dataclass(slots=True)
class ParsedCameraTm:
    table_key: str
    name: str
    fields: list[dict[str, Any]]
    raw_frame: bytes
    data_len: int
    frame_type: str
    size: int

    @property
    def raw_hex(self) -> str:
        return ' '.join(f'{b:02X}' for b in self.raw_frame)


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
            idx = data.find(FRAME_D9_HEADER, i)
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
    def _table_name(cls, table_key: str) -> str:
        name = _TABLE_NAMES.get(table_key)
        if name is not None:
            return name
        table = cls._table_cfg(table_key)
        name = table.get('name') or ('快遥测(开窗)' if table_key == 'D9' else '慢遥测(全窗)')
        _TABLE_NAMES[table_key] = name
        return name

    @classmethod
    def _prepare_payload(
        cls,
        payload: bytes,
        *,
        raw_frame: bytes,
        table_key: str,
        mgr: Any | None = None,
        name: str | None = None,
    ) -> PreparedTmFrame:
        return PreparedTmFrame(
            table_key=table_key,
            name=cls._table_name(table_key) if name is None else name,
            payload=_ensure_bytes(payload),
            raw_frame=_ensure_bytes(raw_frame),
            src_param='',
            src_kind='',
            parser_id=cls.PARSER_ID,
            mgr=_get_cam_tm_mgr() if mgr is None else mgr,
            data_kind=cls.DATA_KIND,
        )

    @classmethod
    def _prepare_d8_frame(cls, frame: bytes) -> PreparedTmFrame:
        if len(frame) < D8_FRAME_MIN:
            raise ValueError(frame_len_mismatch('D8', D8_DATA_LEN, D8_FRAME_MIN, len(frame)))
        if frame[0:2] != FRAME_HEADER or frame[2] != FRAME_TYPE_D8:
            raise ValueError('D8 帧头/类型错误')
        data_len = (frame[4] << 8) | frame[5]
        need = 8 + data_len + 1
        if len(frame) < need:
            raise ValueError(frame_len_mismatch('D8', data_len, need, len(frame)))
        if data_len < D8_DATA_LEN:
            raise ValueError(f'D8 数据长度异常: 0x{data_len:04X}')
        chk = frame[8 + data_len]
        calc = _calc_checksum(frame[2 : 8 + data_len])
        if calc != chk:
            raise ValueError(checksum_mismatch('D8', calc, chk))
        payload = frame[8 : 8 + D8_DATA_LEN]
        return cls._prepare_payload(payload, raw_frame=frame, table_key='D8')

    @classmethod
    def _prepare_d9_frame(cls, frame: bytes) -> PreparedTmFrame:
        if len(frame) < D9_FRAME_LEN:
            raise ValueError(frame_len_mismatch('D9', D9_DATA_LEN, D9_FRAME_LEN, len(frame)))
        if frame[0] != 0xEB or frame[1] != FRAME_TYPE_D9:
            raise ValueError('D9 帧头/类型错误')
        calc = _calc_checksum(frame[2:19])
        chk = frame[19]
        if calc != chk:
            raise ValueError(checksum_mismatch('D9', calc, chk))
        payload = frame[3:19]
        return cls._prepare_payload(payload, raw_frame=frame, table_key='D9')

    @classmethod
    def _to_parsed(cls, prepared: PreparedTmFrame) -> ParsedCameraTm:
        fields = prepared.mgr.parse(prepared.table_key, prepared.payload) or []
        return ParsedCameraTm(
            table_key=prepared.table_key,
            name=prepared.name,
            fields=fields,
            raw_frame=prepared.raw_frame,
            data_len=len(prepared.payload),
            frame_type=prepared.table_key,
            size=len(prepared.raw_frame),
        )

    @classmethod
    def parse_bytes(cls, data: bytes) -> ParsedCameraTm:
        frames = cls.extract_d8_frames(data)
        if frames:
            return cls._to_parsed(cls._prepare_d8_frame(frames[-1]))
        frames9 = cls.extract_d9_frames(data)
        if frames9:
            return cls._to_parsed(cls._prepare_d9_frame(frames9[-1]))
        if len(data) >= D8_FRAME_MIN and data[0:2] == FRAME_HEADER and data[2] == FRAME_TYPE_D8:
            return cls._to_parsed(
                cls._prepare_d8_frame(data[: D8_FRAME_MIN if len(data) >= D8_FRAME_MIN else len(data)])
            )
        if len(data) >= D9_FRAME_LEN and data[0] == 0xEB and data[1] == FRAME_TYPE_D9:
            return cls._to_parsed(cls._prepare_d9_frame(data[:D9_FRAME_LEN]))
        if len(data) >= D8_DATA_LEN:
            return cls._to_parsed(
                cls._prepare_payload(data[:D8_DATA_LEN], raw_frame=data, table_key='D8')
            )
        raise ValueError('未找到有效的相机遥测帧(D8/D9)')

    @classmethod
    def parse_hex(cls, hex_text: str) -> ParsedCameraTm:
        from module_payload.cfg.telecontrol_assembler import hex_to_bytes

        return cls.parse_bytes(hex_to_bytes(hex_text))

    @classmethod
    def _collect_prepared(cls, data: bytes) -> list[PreparedTmFrame]:
        """采集热路径：只收完整 D8/D9。半截块返回空，避免把噪声当遥测解析。"""
        frames8 = cls.extract_d8_frames(data) if FRAME_HEADER in data else []
        frames9 = cls.extract_d9_frames(data) if FRAME_D9_HEADER in data else []
        if not frames8 and not frames9:
            return []
        mgr = _get_cam_tm_mgr()
        out: list[PreparedTmFrame] = []
        if frames8:
            name8 = cls._table_name('D8')
            for fr in frames8:
                data_len = (fr[4] << 8) | fr[5]
                end = 8 + data_len
                calc = _calc_checksum(fr[2:end])
                chk = fr[end]
                if calc != chk:
                    raise ValueError(checksum_mismatch('D8', calc, chk))
                out.append(
                    cls._prepare_payload(
                        fr[8 : 8 + D8_DATA_LEN],
                        raw_frame=fr,
                        table_key='D8',
                        mgr=mgr,
                        name=name8,
                    )
                )
        if frames9:
            name9 = cls._table_name('D9')
            for fr in frames9:
                out.append(
                    cls._prepare_payload(
                        fr[3:19],
                        raw_frame=fr,
                        table_key='D9',
                        mgr=mgr,
                        name=name9,
                    )
                )
        return out

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
                'frameType': prepared.table_key,
                'dataLen': len(prepared.payload),
                'size': len(prepared.raw_frame),
                'fieldCount': len(stored.get('fields') or []),
                'name': stored.get('name', prepared.name),
                'ts': stored.get('ts', ''),
                'parserId': pid,
            }
        if last is None:
            raise ValueError('未找到有效的相机遥测帧(D8/D9)')
        return last
