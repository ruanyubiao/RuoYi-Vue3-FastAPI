"""YJ216 RS422 遥测。

应答帧格式：EB90 | 类型(1) | 数据区长度(u16 BE) | 数据区 | 校验(u16 BE)。
类型为 ``0xAA``。数据区首字节为帧序号（选遥测表），其后为表字段区。
校验为整段数据区字节累加和（不含帧头/类型/长度），高字节在前。

拆帧原则（与遥测表解耦）：
1. 找固定帧头 EB 90；
2. 读长度字段，定位整帧与校验码位置；
3. 对数据区做 sum16 校验；
4. 通过后才进入字段解析。不得用 TeleMetryCfg 行跨度决定帧边界或是否收帧。
硬件改了表内容但帧格式仍正确时，拆帧+校验必须仍能成功；
帧序号↔配置 key 只用于选哪张表解码字段，不决定帧是否有效。
"""

from __future__ import annotations

import threading
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
from module_payload.framing import FixedHeaderLenFieldFrameBuffer
from module_payload.tm.tm_mgr_cache import TmMgrFileCache

FRAME_HEADER = bytes((0xEB, 0x90))
DATA_TYPE = 0xAA
# EB90(2) + 类型(1) + 长度(2)；其后为数据区 + 校验(2)
_PREFIX = 5
# 至少含帧序号 1 字节 + 校验 2 字节
_MIN_FRAME = _PREFIX + 1 + 2

CFG_FILE = telemetry_cfg_for(board_cfg_id('yj216', 'rs422'))

_tm_cache = TmMgrFileCache()
_spans: dict[str, int] | None = None
_key_index: dict[int, str] | None = None

# 串口粘包：每源一个 FixedHeaderLenFieldFrameBuffer（帧内长度字段，可变总长）
_RX_STICKY_MAX = 1 << 20
_RX_MAX_FRAME = 7 + 0xFFFF  # 前缀5+校验2；u16 数据区最大
_rx_framers: dict[str, FixedHeaderLenFieldFrameBuffer] = {}
_rx_framers_lock = threading.Lock()


def clear_rx_sticky(src_param: str | None = None) -> None:
    """清空串口粘包拆帧状态；src_param 为 None 时清全部。"""
    with _rx_framers_lock:
        if src_param is None:
            _rx_framers.clear()
            return
        _rx_framers.pop(str(src_param or ""), None)


def _framer_for(src_param: str) -> FixedHeaderLenFieldFrameBuffer:
    """每串口源复用一个长度字段粘包缓冲。"""
    key = str(src_param or "")
    buf = _rx_framers.get(key)
    if buf is None:
        # 同步头含类型码 AA，避免假 EB90；length_adjust=校验(2)
        buf = FixedHeaderLenFieldFrameBuffer(
            FRAME_HEADER + bytes((DATA_TYPE,)),
            length_offset=3,
            length_width=2,
            endian="big",
            length_base="payload",
            length_adjust=2,
            min_frame_size=_MIN_FRAME,
            max_frame_size=_RX_MAX_FRAME,
            max_buffer=_RX_STICKY_MAX,
        )
        _rx_framers[key] = buf
    return buf


def feed_rx_sticky(src_param: str, data: bytes) -> list[bytes]:
    """串口粘包入口：FixedHeaderLenFieldFrameBuffer 拆出完整帧。"""
    with _rx_framers_lock:
        buf = _framer_for(src_param)
        if data:
            buf.write(data)
        return buf.read_frames()


def reset_cfg_derived() -> None:
    """配置 mtime 变化只清跨度与 key 索引；遥测管理器由调用方显式重载。"""
    global _spans, _key_index
    _spans = None
    _key_index = None


def reset_yj216_rs422_tm_mgr() -> None:
    """清空 RS422 遥测解析缓存与串口粘包拆帧器。"""
    global _spans, _key_index
    _tm_cache.clear()
    _spans = None
    _key_index = None
    clear_rx_sticky()


def _get_tm_mgr(*, reload: bool = False):
    return _tm_cache.get(CFG_FILE, reload=reload, error=f'YJ216 RS422 遥测配置初始化失败: {CFG_FILE}')


def _telemetry_tables() -> dict[str, Any]:
    cfg = PayloadConfigLoader.get_board_telemetry_cfg('yj216', 'rs422')
    return cfg.get('table') or {}


def _table_spans() -> dict[str, int]:
    """每张表配置字段跨度（仅供造数/HIL 等参考，不参与拆帧与收帧）。"""
    global _spans
    if _spans is not None:
        return _spans
    spans: dict[str, int] = {}
    for key, table in _telemetry_tables().items():
        end = 0
        for row in table.get('row') or []:
            bits = int(row.get('bits') or 8)
            pos = int(row.get('bytepos') or 0)
            end = max(end, pos + (bits + 7) // 8)
        spans[str(key)] = end
    _spans = spans
    return spans


def _table_key_index() -> dict[int, str]:
    """配置表 key → 表 id 索引（仅含带 key 字段的表）。"""
    global _key_index
    if _key_index is not None:
        return _key_index
    index: dict[int, str] = {}
    for table_id, table in _telemetry_tables().items():
        if not isinstance(table, dict) or 'key' not in table:
            continue
        norm = PayloadConfigLoader.normalize_table_match_key(table.get('key'))
        if norm is None:
            continue
        index[norm] = str(table_id)
    _key_index = index
    return index


def table_keys_ordered() -> tuple[str, ...]:
    """按配置 key 数值排序的表 id 列表（文件回放等）。"""
    index = _table_key_index()
    return tuple(index[k] for k in sorted(index))


def table_for_seq(seq: int) -> str:
    """按帧序号对应 TeleMetryCfg 表项的 key 选表。

    通用规则：多表时先检查表是否带 key，能对应则使用该表。
    """
    if not isinstance(seq, int):
        seq = int(seq)
    table_id = PayloadConfigLoader.find_table_id_by_key(_telemetry_tables(), seq)
    if not table_id:
        raise ValueError(f'RS422 遥测帧序号无法对应表(key): {seq}')
    return table_id


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


def _data_area_of(frame: bytes) -> bytes:
    """整段数据区（含首字节帧序号）。"""
    length = int.from_bytes(frame[3:5], 'big')
    return frame[_PREFIX : _PREFIX + length]


def _seq_of(frame: bytes) -> int:
    """数据区首字节为帧序号。"""
    return frame[_PREFIX]


def _field_payload_of(frame: bytes) -> bytes:
    """去掉帧序号后的表字段区。"""
    data = _data_area_of(frame)
    return data[1:] if len(data) >= 1 else b''


class Yj216Rs422TmIngest:
    """RS422 遥测：收 EB90 应答，按表写入 TeleMetry 配置。"""

    PARSER_ID = PARSER_TM_YJ216_RS422
    DATA_KIND = DATA_KIND_TM

    @classmethod
    def extract_frames(cls, data: bytes) -> list[bytes]:
        """按帧格式拆帧：EB90 → 长度 → 校验位置 → 校验。不查遥测表跨度。"""
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
            if length < 1:
                i = idx + 2
                continue
            frame = data[idx : idx + total]
            data_area = frame[_PREFIX : _PREFIX + length]
            got = int.from_bytes(frame[-2:], 'big')
            if checksum_u16(data_area) != got:
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
        return _telemetry_tables().get(table_key) or {}

    @classmethod
    def prepare_frame(cls, frame: bytes, *, table_key: str = '') -> PreparedTmFrame:
        """整帧校验 → 预备写入。未指定 table_key 时按数据区首字节帧序号选表。"""
        if frame[0:2] != FRAME_HEADER or frame[2] != DATA_TYPE:
            raise ValueError('RS422 遥测帧头应为 EB90 AA')
        if len(frame) < _MIN_FRAME:
            raise ValueError(frame_len_mismatch('RS422遥测', 0, _MIN_FRAME, len(frame)))
        length = int.from_bytes(frame[3:5], 'big')
        if length < 1:
            raise ValueError(frame_len_mismatch('RS422遥测', 1, _PREFIX + 1 + 2, len(frame)))
        if len(frame) != _PREFIX + length + 2:
            raise ValueError(frame_len_mismatch('RS422遥测', length, _PREFIX + length + 2, len(frame)))
        data_area = _data_area_of(frame)
        got = int.from_bytes(frame[-2:], 'big')
        calc = checksum_u16(data_area)
        if calc != got:
            raise ValueError(checksum_mismatch('RS422遥测', calc, got, width=4))
        key = table_key or table_for_seq(_seq_of(frame))
        table = cls._table_cfg(key)
        return PreparedTmFrame(
            table_key=key,
            name=table.get('name') or key,
            payload=_field_payload_of(frame),
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
        """单帧 → 字段列表。"""
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
        """缓冲 → 最后一帧（文件回放等）；按帧序号选表。"""
        frames = cls.extract_frames(data)
        if not frames:
            raise ValueError('未找到有效的 RS422 遥测帧')
        return cls.parse_frame(frames[-1])

    @classmethod
    def _collect_prepared(cls, data: bytes, *, src_param: str | None = None, sticky: bool = False) -> list[PreparedTmFrame]:
        if sticky:
            # 串口粘包：FixedHeaderLenFieldFrameBuffer 拆整帧 → 再校验/选表
            raw_frames = feed_rx_sticky(src_param or "", data or b"")
            frames = []
            for frame in raw_frames:
                length = int.from_bytes(frame[3:5], "big")
                if length < 1:
                    continue
                data_area = frame[_PREFIX : _PREFIX + length]
                if checksum_u16(data_area) != int.from_bytes(frame[-2:], "big"):
                    continue
                frames.append(frame)
        else:
            frames = cls.extract_frames(data)
        return [cls.prepare_frame(frame, table_key=table_for_seq(_seq_of(frame))) for frame in frames]

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
        """硬件采集：多帧入队或立即写入。"""
        _ = assembler_id
        pid = parser_id or cls.PARSER_ID
        sk = src_kind or infer_src_kind(src_param, SRC_KIND_SERIAL)
        try:
            prepared_list = cls._collect_prepared(data, src_param=src_param, sticky=True)
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
        """串口模拟入口。"""
        _ = assembler_id
        pid = parser_id or cls.PARSER_ID
        sk = src_kind or infer_src_kind(src_param, SRC_KIND_SERIAL)
        prepared_list = cls._collect_prepared(data, src_param=src_param, sticky=True)
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
    """文件回放：先按帧格式拆帧+校验，再按帧序号↔配置 key 筛属于该表的帧。

    不按 TeleMetryCfg 字段跨度过滤长度——表布局变化不得导致合法帧被丢弃。
    """
    local = table_type.split(':', 1)[-1].strip().upper()
    wanted = {seq for seq, tid in _table_key_index().items() if tid.upper() == local}
    if not wanted:
        return []
    return [fr for fr in Yj216Rs422TmIngest.extract_frames(buf) if _seq_of(fr) in wanted]


BINDINGS = ProtocolBindings(
    ingest=Yj216Rs422TmIngest,
    reset_tm=reset_yj216_rs422_tm_mgr,
    reset_cfg_derived=reset_cfg_derived,
    tm_cfg_files=(CFG_FILE,),
    fileplay_tables={key: FilePlaySpec('rs422', _fileplay_extract, Yj216Rs422TmIngest) for key in table_keys_ordered()},
)
