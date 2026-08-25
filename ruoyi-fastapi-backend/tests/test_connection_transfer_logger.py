"""连接级收发落盘：tag 净化、CAN/非 CAN 分流、文件写入。"""

from __future__ import annotations

import time
from pathlib import Path

from module_payload.collectors.connection_transfer_logger import (
    ConnectionTransferLogger,
    format_can_id,
    format_hex_bytes,
    infer_xfer_kind,
    sanitize_tag,
    tag_from_device_id,
)


def test_sanitize_and_kind() -> None:
    assert sanitize_tag('source:camera_ctrl') == 'source_camera_ctrl'
    assert sanitize_tag('a/b\\c d') == 'a_b_c_d'
    assert sanitize_tag('') == 'unknown'
    assert infer_xfer_kind('can:3:0:0') == 'can'
    assert infer_xfer_kind('serial:COM4') == 'other'
    assert infer_xfer_kind('udp:127.0.0.1:9') == 'other'
    assert tag_from_device_id('serial:COM4') == 'serial_COM4'


def test_format_helpers() -> None:
    assert format_hex_bytes(b'\x0a\xff') == '0A FF'
    assert format_can_id(None) == ' ' * 8
    assert format_can_id(0x123) == '00000123'


def test_serial_recv_bin_and_send_txt(tmp_path: Path) -> None:
    log = ConnectionTransferLogger('serial:COM4', kind='other', root_dir=tmp_path)
    try:
        log.append_recv(b'\xeb\x90\x01')
        log.append_send(b'\xaa\xbb')
        log.append_can_assembled(b'\x11')  # 非 CAN 忽略
    finally:
        log.close()
    recv = list(tmp_path.rglob('*_recv.bin'))
    send = list(tmp_path.rglob('*_send.txt'))
    assert len(recv) == 1
    assert recv[0].read_bytes() == b'\xeb\x90\x01'
    assert len(send) == 1
    text = send[0].read_text(encoding='utf-8')
    assert 'AA BB' in text


def test_can_recv_send_are_txt(tmp_path: Path) -> None:
    log = ConnectionTransferLogger('can:3:0:0', kind='can', root_dir=tmp_path)
    try:
        log.append_recv(b'\x11\x22', frame_id=0x1A)
        log.append_can_assembled(b'\x33\x44')
        log.append_send(b'\x55', frame_id=0x0D)
    finally:
        log.close()
    assert list(tmp_path.rglob('*.bin')) == []
    recv = list(tmp_path.rglob('*_recv.txt'))
    send = list(tmp_path.rglob('*_send.txt'))
    assert recv and send
    recv_text = recv[0].read_text(encoding='utf-8')
    assert '11 22' in recv_text
    assert '33 44' in recv_text
    assert '0000001A' in recv_text
    assert '        [' in recv_text  # 组包完成 id 列空格
    assert '55' in send[0].read_text(encoding='utf-8')


def test_closed_logger_drops() -> None:
    log = ConnectionTransferLogger('x', kind='other', root_dir=Path('.'))
    log.close(flush=False)
    log.append_recv(b'\x01')
    log.append_send(b'\x02')
    time.sleep(0.05)
