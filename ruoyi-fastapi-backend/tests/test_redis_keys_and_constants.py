"""Redis Key 规范与业务常量（网口无 net: 前缀、总线表键、IO 节流常量）。"""

from __future__ import annotations

from module_payload import constants as c
from module_payload import redis_keys as rk


def test_device_ids() -> None:
    assert rk.can_card_id(3, 0) == 'can:3:0'
    assert rk.can_channel_id(3, 0, 1) == 'can:3:0:1'
    assert rk.serial_id('COM4') == 'serial:COM4'
    assert rk.net_id('udp', '127.0.0.1', 9000) == 'udp:127.0.0.1:9000'
    assert rk.net_id('TCP', '10.0.0.1', 8000) == 'tcp:10.0.0.1:8000'
    assert rk.net_id('', '1.2.3.4', 1) == 'udp:1.2.3.4:1'
    assert not rk.net_id('udp', '1.2.3.4', 9).startswith('net:')
    assert rk.source_id('camera_ctrl') == 'source:camera_ctrl'


def test_queue_and_status_keys() -> None:
    did = 'serial:COM3'
    assert rk.status_key(did) == 'payload:serial:COM3:status'
    assert rk.heartbeat_key(did) == 'payload:serial:COM3:heartbeat'
    assert rk.cmd_queue_key(did) == 'payload:serial:COM3:cmd'
    assert rk.ctrl_queue_key(did) == 'payload:serial:COM3:ctrl'
    assert rk.cmd_result_key(did, 'abc') == 'payload:serial:COM3:cmd:result:abc'
    assert rk.history_key(did) == 'payload:serial:COM3:history'
    assert rk.io_log_key(did) == 'payload:serial:COM3:io'
    assert rk.io_log_seq_key(did) == 'payload:serial:COM3:io:seq'


def test_seq_and_tm_keys() -> None:
    assert rk.seq_run_key('rid') == 'payload:seq:run:rid'
    assert rk.seq_run_history_key(7) == 'payload:seq:7:runs'
    assert rk.telemetry_latest_key('d8') == 'payload:tm:D8:latest'
    assert rk.telemetry_latest_ts_key('biu:ff') == 'payload:tm:BIU:FF:latest:ts'
    assert rk.curve_latest_key('FF', 'JGB001') == 'payload:tm:FF:curve:JGB001'
    assert rk.archive_queue_key() == 'payload:archive:queue'
    assert rk.tx_queue_key() == 'payload:tx:queue'
    assert rk.session_key('serial', 'serial:COM4') == 'payload:session:serial:serial:COM4'


def test_image_lvds_error_keys() -> None:
    did = 'serial:COM4'
    assert rk.image_key(did) == 'payload:serial:COM4:image'
    assert rk.lvds_key(did, 'qd_x') == 'payload:serial:COM4:lvds:qd_x'
    assert rk.error_type_key('tm') == 'payload:error:tm'
    assert rk.error_type_latest_key('assembler') == 'payload:error:latest:assembler'
    assert rk.tm_calc_history_key() == 'payload:tm:calc:history'


def test_io_log_constants() -> None:
    assert c.IO_LOG_HEX_MAX_BYTES == 256
    assert c.IO_LOG_MIN_INTERVAL_S == 0.5
    assert c.CURVE_MAX_POINTS == 50000
    assert c.IO_LOG_MAX == 1000


def test_bus_tm_keys() -> None:
    assert c.make_bus_tm_key('biu', 'ff') == 'BIU:FF'
    assert c.make_bus_tm_key('XL', 'fd') == 'XL:FD'
    assert c.make_bus_tm_key(None, 'aa') == 'BIU:AA'
    assert c.split_tm_table_key('BIU:FF') == ('biu', 'FF')
    assert c.split_tm_table_key('XL:FD') == ('xl', 'FD')
    assert c.split_tm_table_key('D8') == (None, 'D8')
    assert c.split_tm_table_key('RKDJ') == (None, 'RKDJ')
    assert c.tm_parse_key('BIU:FF') == 'FF'
    assert c.tm_parse_key('ZK') == 'ZK'


def test_infer_src_kind() -> None:
    assert c.infer_src_kind('can:3:0:0') == c.SRC_KIND_CAN
    assert c.infer_src_kind('serial:COM4') == c.SRC_KIND_SERIAL
    assert c.infer_src_kind('COM3') == c.SRC_KIND_SERIAL
    assert c.infer_src_kind('udp:127.0.0.1:9') == c.SRC_KIND_UDP
    assert c.infer_src_kind('tcp:10.0.0.1:8') == c.SRC_KIND_TCP
    assert c.infer_src_kind('http:devtest') == c.SRC_KIND_HTTP
    assert c.infer_src_kind('unknown') == c.SRC_KIND_CAN
    assert c.infer_src_kind('', fallback=c.SRC_KIND_SERIAL) == c.SRC_KIND_SERIAL
    assert c.infer_src_kind('unknown', fallback='') == ''


def test_should_archive_tm_mysql() -> None:
    assert c.should_archive_tm_mysql('can', 'can:3:0:0', c.PARSER_TM_CAN_BIU)
    assert c.should_archive_tm_mysql('http', 'http:devtest', c.PARSER_TM_CAN_BIU)
    assert c.should_archive_tm_mysql('http', 'http:devtest', c.PARSER_TM_CAN_XL)
    assert not c.should_archive_tm_mysql('http', 'http:devtest', c.PARSER_CAMERA_SC_LINK41EP)
    assert not c.should_archive_tm_mysql('serial', 'serial:COM3', c.PARSER_CAMERA_SC_LINK41EP)
    assert not c.should_archive_tm_mysql('udp', 'udp:127.0.0.1:9', c.PARSER_XL_BOARD_TM)
    assert not c.should_archive_tm_mysql('tcp', 'tcp:10.0.0.1:8', c.PARSER_XL_BOARD_TM)
    assert not c.should_archive_tm_mysql('', 'serial:COM4', c.PARSER_CAMERA_SC_LINK41EP)
    assert c.should_archive_tm_mysql('', 'can:3:0:0', c.PARSER_TM_CAN_BIU)
