"""YJ216 RS422 遥测。

应答：EB90 | 3A | 数据区长度(2) | 帧序号(1) | 数据区 | 数据区累加和(2)。
五张 LCWP 数据区一样长，写入本连接最近一次指令码对应的表。
LCOS 与 U-Phi 用数据区长度区分。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from redis import asyncio as aioredis

from module_payload.cfg.payload_config_loader import PayloadConfigLoader
from module_payload.cfg.telecontrol_cfg import board_cfg_id, telemetry_cfg_for
from module_payload.constants import DATA_KIND_TM, ERROR_TYPE_PARSER, SRC_KIND_SERIAL, checksum_u16, infer_src_kind
from module_payload.error_text import checksum_mismatch, frame_len_mismatch
from module_payload.protocol.hooks import FilePlaySpec, ProtocolBindings
from module_payload.protocol.protocol_catalog import PARSER_TM_YJ216_RS422
from module_payload.tm.tm_ingest_batch import PreparedTmFrame, enqueue_prepared_many, process_prepared_async
from module_payload.tm.tm_mgr_cache import TmMgrFileCache

FRAME_HEADER = bytes((0xEB, 0x90))
DATA_TYPE = 0x3A
# EB90(2) + 类型(1) + 长度(2) + 序号(1) + 校验(2)
_PREFIX = 6
_MIN_FRAME = _PREFIX + 2

CMD_TO_TABLE = {
    0x01: 'LCWP20',
    0x02: 'LCWP30',
    0x03: 'LCWP40',
    0x04: 'LCWP50',
    0x05: 'LCWP60',
    0x06: 'LCOS',
    0x07: 'UPHI',
}
TABLE_KEYS = tuple(CMD_TO_TABLE.values())
CFG_FILE = telemetry_cfg_for(board_cfg_id('yj216', 'rs422'))

_tm_cache = TmMgrFileCache()
_spans: dict[str, int] | None = None


def last_table_redis_key(device_id: str) -> str:
    """本串口最近一次遥测请求对应的表键。"""
    return f'payload:rs422:last_table:{device_id}'


async def remember_last_table(redis: aioredis.Redis, device_id: str, table_key: str) -> None:
    """下发遥测请求后记下要写入的表。"""
    if device_id and table_key:
        await redis.set(last_table_redis_key(device_id), table_key)


def read_last_table(redis_client: Any, device_id: str) -> str:
    """读最近一次指令码对应的表；没有则空串。"""
    if redis_client is None or not device_id:
        return ''
    raw = redis_client.get(last_table_redis_key(device_id))
    if raw is None:
        return ''
    if isinstance(raw, bytes):
        return raw.decode()
    return str(raw)


def reset_yj216_rs422_tm_mgr() -> None:
    """清空 RS422 遥测配置缓存。"""
    global _spans
    _tm_cache.clear()
    _spans = None


def _get_tm_mgr(*, reload: bool = False):
    return _tm_cache.get(CFG_FILE, reload=reload, error=f'YJ216 RS422 遥测配置初始化失败: {CFG_FILE}')


def _table_spans() -> dict[str, int]:
    """每张表数据区字节数：最大 bytepos + 位宽。"""
    global _spans
    if _spans is not None:
        return _spans
    cfg = PayloadConfigLoader.get_board_telemetry_cfg('yj216', 'rs422')
    spans: dict[str, int] = {}
    for key, table in (cfg.get('table') or {}).items():
        end = 0
        for row in table.get('row') or []:
            bits = int(row.get('bits') or 8)
            pos = int(row.get('bytepos') or 0)
            end = max(end, pos + (bits + 7) // 8)
        spans[str(key)] = end
    _spans = spans
    return spans


def table_for_payload(length: int, last: str = '') -> str:
    """按数据区长度选表；长度相同的 LCWP 用最近一次指令码。"""
    hits = [key for key, span in _table_spans().items() if span == length]
    if last and last in hits:
        return last
    if len(hits) == 1:
        return hits[0]
    if hits:
        return hits[0]
    raise ValueError(f'RS422 遥测数据区长度无法对应表: {length}')


@dataclass(slots=True)
class ParsedYj216Rs422Tm:
    """校验并字段解析后的一帧。"""

    table_key: str
    name: str
    fields: list[dict[str, Any]]
    raw_frame: bytes
    data_len: int

    @property
    def size(self) -> int:
        return len(self.raw_frame)


def _payload_of(frame: bytes) -> bytes:
    length = int.from_bytes(frame[3:5], 'big')
    return frame[_PREFIX : _PREFIX + length]


class Yj216Rs422TmIngest:
    """RS422 遥测：拆 EB90 应答，按表写入 TeleMetry 配置。"""

    PARSER_ID = PARSER_TM_YJ216_RS422
    DATA_KIND = DATA_KIND_TM

    @classmethod
    def extract_frames(cls, data: bytes) -> list[bytes]:
        """提取校验通过的完整应答。半截帧留到下次。"""
        out: list[bytes] = []
        i = 0
        n = len(data)
        while i + _MIN_FRAME <= n:
            idx = data.find(FRAME_HEADER, i)
            if idx < 0 or idx + _MIN_FRAME > n:
                break
            if data[idx + 2] != DATA_TYPE:
                i = idx + 2
                continue
            length = int.from_bytes(data[idx + 3 : idx + 5], 'big')
            total = _PREFIX + length + 2
            if idx + total > n:
                break
            frame = data[idx : idx + total]
            payload = frame[_PREFIX : _PREFIX + length]
            got = int.from_bytes(frame[-2:], 'big')
            if checksum_u16(payload) != got:
                i = idx + 2
                continue
            out.append(frame)
            i = idx + total
        return out

    @classmethod
    def io_preview_frames(cls, data: bytes) -> list[bytes]:
        return cls.extract_frames(data)

    @classmethod
    def _table_cfg(cls, table_key: str) -> dict[str, Any]:
        cfg = PayloadConfigLoader.get_board_telemetry_cfg('yj216', 'rs422')
        return (cfg.get('table') or {}).get(table_key) or {}

    @classmethod
    def prepare_frame(cls, frame: bytes, *, table_key: str = '') -> PreparedTmFrame:
        """单帧校验 → 待批处理帧。table_key 空则按长度和最近指令选择。"""
        if frame[0:2] != FRAME_HEADER or frame[2] != DATA_TYPE:
            raise ValueError('RS422 遥测帧头不是 EB90 3A')
        if len(frame) < _MIN_FRAME:
            raise ValueError(frame_len_mismatch('RS422遥测', 0, _MIN_FRAME, len(frame)))
        length = int.from_bytes(frame[3:5], 'big')
        if len(frame) != _PREFIX + length + 2:
            raise ValueError(frame_len_mismatch('RS422遥测', length, _PREFIX + length + 2, len(frame)))
        payload = _payload_of(frame)
        got = int.from_bytes(frame[-2:], 'big')
        calc = checksum_u16(payload)
        if calc != got:
            raise ValueError(checksum_mismatch('RS422遥测', calc, got, width=4))
        key = table_key or table_for_payload(len(payload))
        table = cls._table_cfg(key)
        return PreparedTmFrame(
            table_key=key,
            name=table.get('name') or key,
            payload=payload,
            raw_frame=bytes(frame),
            src_param='',
            src_kind='',
            parser_id=cls.PARSER_ID,
            mgr=_get_tm_mgr(),
            data_kind=cls.DATA_KIND,
            big_endian_buffer=True,
        )

    @classmethod
    def parse_frame(cls, frame: bytes, *, table_key: str = '') -> ParsedYj216Rs422Tm:
        """完整帧 → 字段列表。"""
        prepared = cls.prepare_frame(frame, table_key=table_key)
        fields = prepared.mgr.parse(prepared.cfg_parse_key(), prepared.payload, big_endian_buffer=True) or []
        return ParsedYj216Rs422Tm(
            table_key=prepared.table_key,
            name=prepared.name,
            fields=fields,
            raw_frame=prepared.raw_frame,
            data_len=len(prepared.payload),
        )

    @classmethod
    def parse_bytes(cls, data: bytes) -> ParsedYj216Rs422Tm:
        """缓冲 → 最后一帧。文件回放用；表按数据区长度选择。"""
        frames = cls.extract_frames(data)
        if not frames:
            raise ValueError('未找到有效的 RS422 遥测帧')
        return cls.parse_frame(frames[-1])

    @classmethod
    def _collect_prepared(cls, data: bytes, *, last: str = '') -> list[PreparedTmFrame]:
        frames = cls.extract_frames(data)
        out: list[PreparedTmFrame] = []
        for frame in frames:
            payload_len = int.from_bytes(frame[3:5], 'big')
            key = table_for_payload(payload_len, last)
            out.append(cls.prepare_frame(frame, table_key=key))
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
        assembler_id: str | None = None,
    ) -> dict[str, Any] | None:
        """硬件采集：拆帧后入批处理队列。"""
        _ = assembler_id
        pid = parser_id or cls.PARSER_ID
        sk = src_kind or infer_src_kind(src_param, SRC_KIND_SERIAL)
        try:
            last = read_last_table(redis_client, src_param)
            prepared_list = cls._collect_prepared(data, last=last)
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
                error_type=ERROR_TYPE_PARSER,
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
        assembler_id: str | None = None,
    ) -> dict[str, Any]:
        """数据模拟入口。"""
        _ = assembler_id
        pid = parser_id or cls.PARSER_ID
        sk = src_kind or infer_src_kind(src_param, SRC_KIND_SERIAL)
        last = ''
        raw = await redis.get(last_table_redis_key(src_param))
        if isinstance(raw, bytes):
            last = raw.decode()
        elif raw:
            last = str(raw)
        prepared_list = cls._collect_prepared(data, last=last)
        if not prepared_list:
            raise ValueError('未找到有效的 RS422 遥测帧')
        last_out: dict[str, Any] | None = None
        for prepared in prepared_list:
            prepared.src_param = src_param
            prepared.src_kind = sk
            prepared.parser_id = pid
            stored = await process_prepared_async(redis, [prepared]) or {}
            last_out = {
                'dataType': prepared.table_key,
                'name': stored.get('name', prepared.name),
                'fieldCount': len(stored.get('fields') or []),
                'ts': stored.get('ts', ''),
            }
        return last_out or {}


def _fileplay_extract(buf: bytes, table_type: str) -> list[bytes]:
    """文件回放：只留数据区长度对得上这张表的帧。"""
    local = table_type.split(':', 1)[-1].strip().upper()
    span = _table_spans().get(local)
    if span is None:
        return []
    return [fr for fr in Yj216Rs422TmIngest.extract_frames(buf) if int.from_bytes(fr[3:5], 'big') == span]


BINDINGS = ProtocolBindings(
    ingest=Yj216Rs422TmIngest,
    reset_tm=reset_yj216_rs422_tm_mgr,
    tm_cfg_files=(CFG_FILE,),
    fileplay_tables={key: FilePlaySpec('rs422', _fileplay_extract, Yj216Rs422TmIngest) for key in TABLE_KEYS},
)
