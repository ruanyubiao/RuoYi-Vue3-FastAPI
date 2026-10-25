"""cfg_device_connect source 合并打开连接请求。"""

from module_payload.cfg.device_connect_merge import merge_can_open, merge_net_open, merge_serial_open
from module_payload.cfg.payload_config_loader import PayloadConfigLoader
from module_payload.entity.vo.payload_device_vo import CanOpenModel, NetOpenModel, SerialOpenModel


def setup_module() -> None:
    PayloadConfigLoader.get_device_connect_cfg(reload=True)


def test_merge_can_uses_cfg_and_keeps_hardware_ids() -> None:
    body = CanOpenModel(
        vendor=0,
        dev_index=1,
        can_index=2,
        baud_rate=999,
        parser_id='wrong',
        assembler_id='wrong',
        source='biu_can_a',
        full_duplex=True,
        cable_flag=0,
        node_addr_to=0x0C,
    )
    got = merge_can_open(body)
    assert got.vendor == 0
    assert got.dev_index == 1
    assert got.can_index == 2
    assert got.cable_flag == 0
    assert got.node_addr_to == 0x0C
    assert got.baud_rate == 500
    assert got.assembler_id == 'can_biu'
    assert got.parser_id == 'tm_can_biu'
    assert got.full_duplex is False
    assert got.source == 'biu_can_a'


def test_merge_can_keeps_baud_when_in_choices() -> None:
    # xl-camera-image 有多档波特；CAN 条目 baudChoices 仅 [500]
    body = CanOpenModel(baud_rate=500, source='biu_can_a', assembler_id='x', parser_id='y')
    assert merge_can_open(body).baud_rate == 500


def test_merge_can_home_or_missing_unchanged() -> None:
    home = CanOpenModel(baud_rate=250, assembler_id='can_xl', source='home')
    assert merge_can_open(home).baud_rate == 250
    assert merge_can_open(home).assembler_id == 'can_xl'
    missing = CanOpenModel(baud_rate=250, source='no_such_key')
    assert merge_can_open(missing).baud_rate == 250


def test_merge_serial_overrides_line_params() -> None:
    body = SerialOpenModel(
        port='COM9',
        baudrate=9600,
        data_bits=7,
        stop_bits=2,
        parity='E',
        flow_control='RTS/CTS',
        assembler_id='x',
        parser_id='y',
        source='xl-rkdj',
        full_duplex=False,
    )
    got = merge_serial_open(body)
    assert got.port == 'COM9'
    assert got.baudrate == 115200
    assert got.data_bits == 8
    assert got.stop_bits == 1.0
    assert got.parity == 'N'
    assert got.flow_control == 'NONE'
    assert got.assembler_id == 'passthrough'
    assert got.parser_id == 'tm_xl_board'
    assert got.full_duplex is True


def test_merge_serial_baud_choice_keeps_request_if_allowed() -> None:
    body = SerialOpenModel(port='COM1', baudrate=11_000_000, source='xl-camera')
    assert merge_serial_open(body).baudrate == 11_000_000
    bad = SerialOpenModel(port='COM1', baudrate=9600, source='xl-camera')
    assert merge_serial_open(bad).baudrate == 2_000_000


def test_merge_net_overrides_endpoints() -> None:
    body = NetOpenModel(
        local_host='0.0.0.0',
        local_port=1,
        remote_host='8.8.8.8',
        remote_port=53,
        assembler_id='x',
        parser_id='y',
        source='xl_udp_dj',
        full_duplex=False,
    )
    got = merge_net_open(body)
    assert got.local_host == '127.0.0.1'
    assert got.local_port == 66
    assert got.remote_host == '127.0.0.1'
    assert got.remote_port == 99
    assert got.assembler_id == 'eng_tm_subpkt'
    assert got.parser_id == 'tm_xl_board'
    assert got.full_duplex is True


def test_merge_kind_mismatch_skips() -> None:
    # serial source 套到 CAN 模型：kind 不匹配，不合并
    body = CanOpenModel(baud_rate=111, assembler_id='keep', source='xl-rkdj')
    got = merge_can_open(body)
    assert got.baud_rate == 111
    assert got.assembler_id == 'keep'
