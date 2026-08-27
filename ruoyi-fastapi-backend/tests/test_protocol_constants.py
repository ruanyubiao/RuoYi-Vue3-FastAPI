"""协议常量表征：8 位校验、EB90 头、工程帧、单板源、采集节拍。

重构前锁定各模块现有值；抽到 constants 后仍经模块别名保持一致。
"""

from __future__ import annotations

from module_payload.assemblers.camera_image_d6 import FRAME_HEADER as D6_HEADER
from module_payload.assemblers.camera_image_d6 import calc_checksum as d6_checksum
from module_payload.assemblers.eng_tm_subpkt import (
    ENG_CHK_OFF,
    ENG_DATA_CAPACITY,
    ENG_FRAME_SIZE,
    ENG_START,
)
from module_payload.cfg.camera_telecontrol_assembler import FRAME_HEADER as CAM_TC_HEADER
from module_payload.cfg.can_yc_frame import calc_checksum_byte
from module_payload.cfg.telecontrol_assembler import calc_checksum
from module_payload.cfg.xl_board_telecontrol_assembler import FRAME_HEADER as XL_TC_HEADER
from module_payload.parsers.camera_sc_link41ep import FRAME_HEADER as CAM_TM_HEADER
from module_payload.parsers.camera_sc_link41ep import _calc_checksum as cam_tm_checksum
from module_payload.parsers.tm_ingest_batch import FLUSH_INTERVAL_S, LATEST_INTERVAL_S
from module_payload.parsers.xl_board_tm import FRAME_HEADER as XL_TM_HEADER
from module_payload.parsers.xl_board_tm import SRC_TO_TABLE
from module_payload.parsers.xl_board_tm import _calc_checksum as xl_tm_checksum

_EB90 = bytes([0xEB, 0x90])
_SAMPLE = b'\xff\x01'
_SUM8 = 0  # (0xFF + 0x01) & 0xFF


def test_eb90_headers_agree() -> None:
    assert XL_TM_HEADER == _EB90
    assert CAM_TM_HEADER == _EB90
    assert D6_HEADER == _EB90
    assert CAM_TC_HEADER == _EB90
    assert XL_TC_HEADER == _EB90


def test_checksum_u8_modules_agree() -> None:
    assert calc_checksum(_SAMPLE) == _SUM8
    assert calc_checksum_byte(_SAMPLE) == _SUM8
    assert xl_tm_checksum(_SAMPLE) == _SUM8
    assert cam_tm_checksum(_SAMPLE) == _SUM8
    assert d6_checksum(_SAMPLE) == _SUM8
    assert calc_checksum(b'') == 0
    assert calc_checksum(b'\xff\xff') == 0xFE


def test_eng_tm_frame_layout() -> None:
    assert ENG_START == 0x1BCF
    assert ENG_DATA_CAPACITY == 828
    assert ENG_FRAME_SIZE == 844
    assert ENG_CHK_OFF == ENG_FRAME_SIZE - 4
    # 16 位校验与 8 位不是同一函数
    assert (sum(_SAMPLE) & 0xFFFF) != (sum(_SAMPLE) & 0xFF) or _SAMPLE == b''


def test_xl_board_src_to_table() -> None:
    assert SRC_TO_TABLE[0x33] == 'RKDJ'
    assert SRC_TO_TABLE[0x44] == 'ZK'
    assert SRC_TO_TABLE[0x77] == 'DJ'


def test_ingest_and_collector_timing() -> None:
    assert LATEST_INTERVAL_S == 0.5
    assert FLUSH_INTERVAL_S == 0.5
    from module_payload.constants import (
        ASSEMBLED_STORE_MIN_INTERVAL_S,
        COLLECTOR_LOOP_INTERVAL_S,
        TM_FLUSH_INTERVAL_S,
        TM_LATEST_INTERVAL_S,
    )

    assert COLLECTOR_LOOP_INTERVAL_S == 0.01
    assert ASSEMBLED_STORE_MIN_INTERVAL_S == 0.2
    assert TM_LATEST_INTERVAL_S == LATEST_INTERVAL_S
    assert TM_FLUSH_INTERVAL_S == FLUSH_INTERVAL_S


def test_canonical_protocol_constants() -> None:
    from module_payload.constants import (
        EB90_HEADER,
        ENG_DATA_CAPACITY,
        ENG_FRAME_SIZE,
        ENG_START,
        XL_SRC_DJ,
        XL_SRC_RKDJ,
        XL_SRC_TO_TABLE,
        XL_SRC_ZK,
        checksum_u8,
        checksum_u16,
    )

    assert EB90_HEADER == _EB90
    assert checksum_u8(_SAMPLE) == _SUM8
    assert checksum_u8 is calc_checksum
    assert checksum_u16(_SAMPLE) == (0xFF + 0x01)
    assert ENG_START == 0x1BCF
    assert ENG_DATA_CAPACITY == 828
    assert ENG_FRAME_SIZE == 844
    assert XL_SRC_TO_TABLE[XL_SRC_RKDJ] == 'RKDJ'
    assert XL_SRC_TO_TABLE[XL_SRC_ZK] == 'ZK'
    assert XL_SRC_TO_TABLE[XL_SRC_DJ] == 'DJ'
    assert SRC_TO_TABLE is XL_SRC_TO_TABLE

