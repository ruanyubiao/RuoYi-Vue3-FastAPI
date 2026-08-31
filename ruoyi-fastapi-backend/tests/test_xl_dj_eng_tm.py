"""地检 UDP + 表格 4 工程遥测：Part A 单测（注释对照协议）。

分层：
- 外层：XL 协议 V1.0.6 表格 4 内部工程数据帧（起始码 0x1BCF，子包数目=总包数）。
- 内层：组帧后载荷按 XL-DJ-TeleMetryCfg（表键 DJ，从 ZK 拷贝占位）解析。
- 相对现网：0x1ACF/1040/1024 → 0x1BCF/844/828。
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from module_payload.assemblers.eng_tm_subpkt import (
    ENG_CHK_OFF,
    ENG_DATA_CAPACITY,
    ENG_END_OFF,
    ENG_FRAME_SIZE,
    ENG_START,
    EngTmSubpktAssembler,
)
from module_payload.cfg.payload_config_loader import PayloadConfigLoader
from module_payload.cfg.telecontrol_cfg import cfg_id_for_board
from module_payload.collectors.connection_transfer_logger import ConnectionTransferLogger
from module_payload.constants import ASSEMBLER_ENG_TM_SUBPKT, PARSER_TM_XL_BOARD, should_archive_tm_mysql
from module_payload.demux import StreamDemux
from module_payload.entity.vo.payload_device_vo import NetOpenModel
from module_payload.parsers.xl_board_tm import XlBoardTmIngest
from module_payload.service.payload_device_service import PayloadDeviceService


def _build_table4_frame(
    *,
    data: bytes,
    src: int = 0x33,
    dst: int = 0x22,
    sub_count: int = 1,
    sub_index: int = 1,
    start: int | None = None,
) -> bytes:
    """构造表格 4 单帧（大端）。start 默认 0x1BCF，可改成旧 0x1ACF 做拒绝用例。"""
    assert len(data) <= ENG_DATA_CAPACITY
    body = bytearray(ENG_FRAME_SIZE)
    body[0:2] = (start if start is not None else ENG_START).to_bytes(2, 'big')
    body[2:4] = len(data).to_bytes(2, 'big')
    body[4:6] = src.to_bytes(2, 'big')
    body[6:8] = dst.to_bytes(2, 'big')
    body[8:10] = sub_count.to_bytes(2, 'big')
    body[10:12] = sub_index.to_bytes(2, 'big')
    body[12 : 12 + len(data)] = data
    checksum = sum(body[0:ENG_CHK_OFF]) & 0xFFFF
    body[ENG_CHK_OFF:ENG_END_OFF] = checksum.to_bytes(2, 'big')
    body[ENG_END_OFF:ENG_FRAME_SIZE] = (0x0A0D).to_bytes(2, 'big')
    return bytes(body)


def test_t1_table4_single_packet() -> None:
    """T1 — 表格 4 单包组帧。

    协议：子包数目=1 即总包数=1，子包序号=1，起始码 0x1BCF。
    输入：一帧合法 844B，数据区填 HELLO-DJ。
    期望：feed 立即产出一条载荷，无需等待后续包；meta.subCount=1。
    """
    payload = b'HELLO-DJ'
    frame = _build_table4_frame(data=payload, sub_count=1, sub_index=1)
    asm = EngTmSubpktAssembler()
    out = asm.feed(frame)
    assert len(out) == 1
    assert out[0].data == payload
    assert out[0].meta['subCount'] == 1
    assert len(frame) == ENG_FRAME_SIZE


def test_t2_table4_multi_packet_join() -> None:
    """T2 — 多包子包连续拼装。

    协议：全程子包数目字段恒为总包数 3；序号从 1 递增到 3。
    输入：三帧有效数据分别为 A/B/C 各一字节。
    期望：仅收到第 3 包后 _finish；拼接顺序 1∥2∥3；中途不产出。
    """
    asm = EngTmSubpktAssembler()
    assert asm.feed(_build_table4_frame(data=b'A', sub_count=3, sub_index=1)) == []
    assert asm.feed(_build_table4_frame(data=b'B', sub_count=3, sub_index=2)) == []
    out = asm.feed(_build_table4_frame(data=b'C', sub_count=3, sub_index=3))
    assert len(out) == 1
    assert out[0].data == b'ABC'
    assert out[0].meta['subCount'] == 3


def test_t3_gap_and_non_first_dropped() -> None:
    """T3 — 序号不连续 / 非首帧丢弃。

    协议/现网策略（OPEN-001）：无缓存时直接喂序号 2 丢弃；
    先 1 再 3（缺 2）丢缓存与当前帧，避免半包当全包解析进 DJ 表。
    """
    asm = EngTmSubpktAssembler()
    assert asm.feed(_build_table4_frame(data=b'2', sub_count=3, sub_index=2)) == []
    assert any('非首帧' in e for e in asm.take_errors())
    assert asm.feed(_build_table4_frame(data=b'A', sub_count=3, sub_index=1)) == []
    assert asm.feed(_build_table4_frame(data=b'C', sub_count=3, sub_index=3)) == []
    assert any('不连续' in e for e in asm.take_errors())


def test_t4_header_size_and_old_1acf_rejected() -> None:
    """T4 — 帧头/帧长对齐协议。

    协议表体：0x1BCF + 数据区 828 + 整帧 844。
    文档备注「1024」与表体冲突时以表体为准。
    现网差异：旧 0x1ACF/1040 帧不得被新缓冲识别为合法表格 4 帧。
    """
    assert ENG_START == 0x1BCF
    assert ENG_DATA_CAPACITY == 828
    assert ENG_FRAME_SIZE == 844
    old = _build_table4_frame(data=b'OLD', start=0x1ACF)
    import pytest

    with pytest.raises(ValueError, match='起始码'):
        EngTmSubpktAssembler.parse_frame(old)
    # 流缓冲只认 0x1BCF，旧同步字不会被拆成合法帧
    assert EngTmSubpktAssembler().feed(old) == []


def test_t5_demux_routes_1bcf() -> None:
    """T5 — demux 路由。

    地检 UDP 默认 assemblerId=eng_tm_subpkt；混流中夹杂其它头时只命中 0x1BCF 工程帧。
    """
    f1 = _build_table4_frame(data=b'A', sub_count=1, sub_index=1)
    demux = StreamDemux(
        [
            {
                'id': 'eng',
                'framing': 'header_len_trailer',
                'header': '1BCF',
                'frameSize': 844,
                'trailers': ['0A0D', '0D0A'],
                'assemblerId': 'eng_tm_subpkt',
            }
        ]
    )
    demux.write(b'\x00\x11' + f1 + b'\x22')
    hits = demux.drain()
    assert len(hits) == 1
    assert hits[0].assembler_id == ASSEMBLER_ENG_TM_SUBPKT
    assert hits[0].frame == f1


def test_t6_board_dj_config() -> None:
    """T6 — board=dj 配置加载。

    TeleMetryCfg 是内层载荷解析表，不是表格 4 外壳；DJ 文件从 ZK 拷贝仅为联调占位。
    """
    assert PayloadConfigLoader.normalize_xl_board('dj') == 'dj'
    assert PayloadConfigLoader.xl_board_tm_table_key('dj') == 'DJ'
    assert cfg_id_for_board('dj') == 'xl-dj-tc'
    tm = PayloadConfigLoader.get_xl_board_telemetry_cfg('dj', reload=True)
    table = (tm.get('table') or {}).get('DJ') or {}
    assert table.get('id') == 'DJ'
    assert table.get('row')
    tc = PayloadConfigLoader.get_xl_board_telecontrol_cfg('dj', reload=True)
    assert isinstance(tc.get('order'), dict) and tc['order']


def test_t7_open_net_remote_not_in_device_id() -> None:
    """T7 — openNet 携带远程且 deviceId 不变。

    打开 UDP：本机 127.0.0.1:66，远程 127.0.0.1:99，source=xl_udp_dj。
    远程只作默认发送对端，deviceId 仅为 udp:127.0.0.1:66。
    """
    mgr = MagicMock()
    mgr.start_net.return_value = ('udp:127.0.0.1:66', False)
    redis = MagicMock()
    body = NetOpenModel(
        proto='udp',
        local_host='127.0.0.1',
        local_port=66,
        remote_host='127.0.0.1',
        remote_port=99,
        source='xl_udp_dj',
        full_duplex=True,
    )
    with (
        patch(
            'module_payload.collectors.process_manager.CollectorProcessManager.instance',
            return_value=mgr,
        ),
        patch(
            'module_payload.collectors.redis_sync.create_sync_redis',
            return_value=redis,
        ),
        patch(
            'module_payload.service.payload_session_service.PayloadSessionService.open_session_sync',
            return_value={'srcParam': 'udp:127.0.0.1:66'},
        ),
    ):
        out = PayloadDeviceService._open_net_sync(body)
    assert out['deviceId'] == 'udp:127.0.0.1:66'
    cfg = mgr.start_net.call_args.args[3]
    assert cfg['remote_host'] == '127.0.0.1'
    assert cfg['remote_port'] == 99
    listed = [
        {
            'deviceId': 'udp:127.0.0.1:66',
            'alive': True,
            'type': 'net',
            'config': {
                'proto': 'udp',
                'local_host': '127.0.0.1',
                'local_port': 66,
                'remote_host': '127.0.0.1',
                'remote_port': 99,
            },
        }
    ]
    with patch(
        'module_payload.collectors.process_manager.CollectorProcessManager.instance',
        return_value=MagicMock(list_opened=lambda: listed),
    ):
        nets = PayloadDeviceService.list_net_opened()
    assert nets[0]['deviceId'] == 'udp:127.0.0.1:66'
    assert nets[0]['remoteHost'] == '127.0.0.1'
    assert nets[0]['remotePort'] == 99


def test_t8_delay_eng_not_mysql_file_stream() -> None:
    """T8 — 延迟工程数据不入 MySQL，组帧结果落文件流。

    与「非 CAN 不入库 + 地检工程明确文件流」一致：
    udp + xl_board_tm 不得归档 payload_tm_frame；
    组帧后的内层载荷可写入 *_eng.bin。
    """
    assert not should_archive_tm_mysql('udp', 'udp:127.0.0.1:66', PARSER_TM_XL_BOARD)
    prepared = XlBoardTmIngest.prepare_assembled_payload(b'\x00' * 16, table_key='DJ')
    assert prepared.table_key == 'DJ'
    assert prepared.extra.get('frameFmt') == 'table4'
    with TemporaryDirectory() as tmp:
        logger = ConnectionTransferLogger('udp_127.0.0.1_66', kind='other', root_dir=tmp)
        logger.append_eng(b'ENG-PAYLOAD')
        logger.close(flush=True)
        eng_files = list(Path(tmp).rglob('*_eng.bin'))
        assert eng_files
        assert eng_files[0].read_bytes() == b'ENG-PAYLOAD'
