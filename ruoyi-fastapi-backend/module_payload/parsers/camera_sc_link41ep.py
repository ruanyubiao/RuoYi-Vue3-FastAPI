"""SC-LINK41EP 串口遥测解释器：慢遥 0xD8、快遥 0xD9。

帧头/校验在本模块处理；字段解析交给 TeleMetryParser（只传入数据区 bytes）。

D9 帧布局（20B）：``EB D9 seq data[16] chk``。
CAMF001–CAMF011 落在本帧 16B 数据区；CAMF011 的 4 字节按 ``seq & 7`` 分时复用 8 组状态。
组 payload 时在 16B 后拼接 mux0–7 共 32B（缺槽填 0），得到 48B 再交给 D9 配置表解析 CAMF012–CAMF031。
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
D9_MUX_COUNT = 8
D9_MUX_SLOT_LEN = 4
D9_EXTENDED_DATA_LEN = D9_DATA_LEN + D9_MUX_COUNT * D9_MUX_SLOT_LEN  # 16 + 32 = 48
_D9_MUX_ZERO = b'\x00' * D9_MUX_SLOT_LEN

_cam_tm_cache = TmMgrFileCache()
_TABLE_NAMES: dict[str, str] = {}
# 按串口/源隔离：src_param -> mux(0..7) -> 该槽最近一次 CAMF011 四字节
_d9_mux_cache: dict[str, dict[int, bytes]] = {}


def reset_cam_tm_mgr() -> None:
    """清空相机遥测 TeleMetryCfgManager、表名缓存，以及 D9 mux last-known。

    关串口 / 热重载配置时调用，避免旧源的 mux 槽污染新会话。
    """
    _cam_tm_cache.clear()
    _TABLE_NAMES.clear()
    _d9_mux_cache.clear()


def _d9_mux_index(seq_byte: int) -> int:
    """D9 序号低 3 位即 mux 槽号 0..7（与 seq 是否从 0 起步无关）。"""
    return seq_byte & 7


def _d9_camf011_bytes(frame: bytes) -> bytes:
    """取出本帧 CAMF011 的 4 字节。

    全帧 20B：偏移 15:19（跳过 EB D9 seq 后的数据区 [12:16]）。
    仅 16B 数据区：直接 [12:16]。不够长则返回全 0。
    """
    if len(frame) >= D9_FRAME_LEN:
        return bytes(frame[15:19])
    if len(frame) >= 16:
        return bytes(frame[12:16])
    return _D9_MUX_ZERO


def _d9_mux_from_batch(frames: list[bytes]) -> dict[int, bytes]:
    """从本批 D9 全帧列表收集每个 mux 的最新 CAMF011。

    倒序扫描：同一 mux 多次出现时保留最后一次。不要求本批从 mux0 开始，
    也不要求凑满 8 槽；缺的槽不进返回值，由 ``_d9_mux_resolve`` 用缓存或 0 补。
    """
    out: dict[int, bytes] = {}
    for fr in reversed(frames):
        if len(fr) < D9_FRAME_LEN:
            continue
        mux = _d9_mux_index(fr[2])
        if mux in out:
            continue
        out[mux] = _d9_camf011_bytes(fr)
        if len(out) == D9_MUX_COUNT:
            break
    return out


def _d9_mux_resolve(batch_map: dict[int, bytes], src_param: str) -> bytes:
    """组装 8×4=32 字节 mux 块，取数顺序：本批 → 该 src_param 缓存 → 00。

    本批见到的槽立刻写回缓存，供下一包 ingest（含 1 帧/秒回放）使用。
    未见到的槽不覆盖缓存。返回值始终 32 字节，槽序固定为 mux0..mux7。
    """
    cached = _d9_mux_cache.setdefault(src_param, {})
    slots: list[bytes] = []
    for i in range(D9_MUX_COUNT):
        # 本批优先；没有再 last-known；再没有填 0
        raw = batch_map.get(i, cached.get(i, _D9_MUX_ZERO))
        blob = bytes(raw)[:D9_MUX_SLOT_LEN].ljust(D9_MUX_SLOT_LEN, b'\x00')
        slots.append(blob)
        if i in batch_map:
            cached[i] = blob
    return b''.join(slots)


def _d9_build_extended_payload(payload16: bytes, mux32: bytes) -> bytes:
    """本帧 16B 数据区 + mux0–7 的 32B → TeleMetryParser 用的 48B D9 payload。"""
    p = bytes(payload16)[:D9_DATA_LEN].ljust(D9_DATA_LEN, b'\x00')
    m = bytes(mux32)[: D9_MUX_COUNT * D9_MUX_SLOT_LEN].ljust(D9_MUX_COUNT * D9_MUX_SLOT_LEN, b'\x00')
    return p + m


def _calc_checksum(data: bytes) -> int:
    """协议校验：参与字节求和后取低 8 位。"""
    return sum(data) & 0xFF


def _ensure_bytes(data: bytes | bytearray | memoryview) -> bytes:
    """已是 bytes 则原样返回，避免热路径上无谓拷贝。"""
    return data if type(data) is bytes else bytes(data)


def _get_cam_tm_mgr(*, reload: bool = False):
    """加载 XL-Camera-TeleMetryCfg.json 的 TeleMetryParser 管理器（进程内文件缓存）。"""
    return _cam_tm_cache.get(
        CAMERA_TELE_METRY_CFG_NAME,
        reload=reload,
        error=f'相机遥测配置初始化失败: {CAMERA_TELE_METRY_CFG_NAME}',
    )


@dataclass(slots=True)
class ParsedCameraTm:
    """单帧解析结果：表键、字段列表、原始帧；D9 的 data_len 为扩展后的 48。"""

    table_key: str
    name: str
    fields: list[dict[str, Any]]
    raw_frame: bytes
    data_len: int
    frame_type: str
    size: int

    @property
    def raw_hex(self) -> str:
        """原始帧十六进制，空格分隔大写。"""
        return ' '.join(f'{b:02X}' for b in self.raw_frame)


class CameraScLink41epIngest:
    """串口1 慢遥测 D8 / 快遥测 D9：拆帧校验 + TeleMetryParser 字段解析 + Redis。"""

    PARSER_ID = PARSER_CAMERA_SC_LINK41EP
    DATA_KIND = DATA_KIND_TM

    @classmethod
    def _table_cfg(cls, table_key: str = 'D8', reload: bool = False) -> dict[str, Any]:
        """取 D8/D9 表配置；reload 时同步重建 TeleMetryParser 管理器。"""
        cfg = PayloadConfigLoader.get_camera_telemetry_cfg(reload=reload)
        if reload:
            _get_cam_tm_mgr(reload=True)
        return (cfg.get('table') or {}).get(table_key) or {}

    @classmethod
    def extract_d8_frames(cls, data: bytes) -> list[bytes]:
        """从缓冲中提取完整 D8 帧（允许粘包、前缀噪声）。

        同步头 ``EB 90`` 后类型字节必须为 ``D8``；长度字段决定帧总长。
        非 D8 类型只跳过类型字节继续搜，避免把其它 EB90 帧吞掉。
        """
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
        """快遥拆帧：``EB D9 seq data[16] chk``，定长 20B。

        校验覆盖序号~数据（全帧下标 2..18）。校验失败前进 1 字节再搜，
        避免错同步后把后续真帧也丢掉。
        """
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
        """表显示名（进程内缓存）；配置缺 name 时用慢遥/快遥默认文案。"""
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
        """组装待解析帧：payload 已是 TeleMetryParser 数据区（D8=45B，D9=48B）。"""
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
        """单帧 D8：校验头/长度/checksum，截取 45B 数据区。"""
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
    def _prepare_d9_frame(
        cls,
        frame: bytes,
        mux32: bytes | None = None,
        src_param: str = '',
    ) -> PreparedTmFrame:
        """单帧 D9：校验后取 16B，再拼 mux32 得到 48B。

        ``mux32`` 为空时本批只含这一帧，缺槽走缓存或 0（历史回放 1 帧/秒同此路径）。
        """
        if len(frame) < D9_FRAME_LEN:
            raise ValueError(frame_len_mismatch('D9', D9_DATA_LEN, D9_FRAME_LEN, len(frame)))
        if frame[0] != 0xEB or frame[1] != FRAME_TYPE_D9:
            raise ValueError('D9 帧头/类型错误')
        calc = _calc_checksum(frame[2:19])
        chk = frame[19]
        if calc != chk:
            raise ValueError(checksum_mismatch('D9', calc, chk))
        payload16 = frame[3:19]
        if mux32 is None:
            mux32 = _d9_mux_resolve(_d9_mux_from_batch([frame]), src_param)
        payload = _d9_build_extended_payload(payload16, mux32)
        return cls._prepare_payload(payload, raw_frame=frame, table_key='D9')

    @classmethod
    def _to_parsed(cls, prepared: PreparedTmFrame) -> ParsedCameraTm:
        """调用 TeleMetryParser：D9 传入 48B 即可解出 CAMF001–CAMF031。"""
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
        """离线/调试入口：优先完整 D8，否则 D9；取缓冲里最后一帧。"""
        frames = cls.extract_d8_frames(data)
        if frames:
            return cls._to_parsed(cls._prepare_d8_frame(frames[-1]))
        frames9 = cls.extract_d9_frames(data)
        if frames9:
            # 多帧 D9 时用整批拼 mux，再解析最后一帧（本帧 16B + 批内最新 mux）
            mux32 = _d9_mux_resolve(_d9_mux_from_batch(frames9), '')
            return cls._to_parsed(cls._prepare_d9_frame(frames9[-1], mux32=mux32))
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
        """十六进制文本走 ``hex_text``（空白分段，与前端输入框一致）后再 ``parse_bytes``。"""
        from module_payload.cfg.hex_text import hex_to_bytes

        return cls.parse_bytes(hex_to_bytes(hex_text))

    @classmethod
    def _collect_prepared(cls, data: bytes, src_param: str = '') -> list[PreparedTmFrame]:
        """采集热路径：只收完整 D8/D9。半截块返回空，避免把噪声当遥测解析。

        D9：先对本批倒序收齐 mux，再对每一帧立刻拼 48B（禁止等凑满 8 槽才 parse）。
        ``src_param`` 作为 mux 缓存键，须与 ingest 的源一致。
        """
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
            # 整批扫一遍 mux；本批每一帧共用这份 32B（本帧 16B 仍各自不同）
            mux32 = _d9_mux_resolve(_d9_mux_from_batch(frames9), src_param)
            for fr in frames9:
                out.append(
                    cls._prepare_payload(
                        _d9_build_extended_payload(fr[3:19], mux32),
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
        """同步采集入口：拆帧后入队 Redis。``src_param`` 同时用于 D9 mux 缓存隔离。"""
        pid = parser_id or cls.PARSER_ID
        sk = src_kind or infer_src_kind(src_param, SRC_KIND_SERIAL)
        try:
            prepared_list = cls._collect_prepared(data, src_param=src_param)
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
        """异步入口：逐帧 parse 写入；返回最后一帧摘要。无完整帧则抛错。"""
        pid = parser_id or cls.PARSER_ID
        sk = src_kind or infer_src_kind(src_param, SRC_KIND_SERIAL)
        prepared_list = cls._collect_prepared(data, src_param=src_param)
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
