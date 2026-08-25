"""会话：组装器/解释器校验、同步开闭、网口 srcKind。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from exceptions.exception import ServiceException
from module_payload.constants import ASSEMBLER_CAN_BIU, ASSEMBLER_PASSTHROUGH, SRC_KIND_CAN, SRC_KIND_UDP
from module_payload.service.payload_session_service import PayloadSessionService


class _MemRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, val: str, ex=None) -> None:
        self.store[key] = val

    def get(self, key: str):
        return self.store.get(key)

    def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def aget(self, key: str):
        return self.store.get(key)


def test_validate_assembler_for_src() -> None:
    assert PayloadSessionService.validate_assembler_id(None, 'serial') == ASSEMBLER_PASSTHROUGH
    assert PayloadSessionService.validate_assembler_id(ASSEMBLER_CAN_BIU, SRC_KIND_CAN) == ASSEMBLER_CAN_BIU
    with pytest.raises(ValueError, match='仅可用于 CAN'):
        PayloadSessionService.validate_assembler_id(ASSEMBLER_CAN_BIU, 'serial')
    with pytest.raises(ValueError, match='仅支持'):
        PayloadSessionService.validate_assembler_id('eng_tm_subpkt', SRC_KIND_CAN)
    with pytest.raises(ValueError, match='未知'):
        PayloadSessionService.validate_assembler_id('nope', 'serial')


def test_validate_routes() -> None:
    routes = PayloadSessionService.validate_routes(
        [
            {
                'id': 'eng',
                'framing': 'header_len_trailer',
                'header': '1ACF',
                'frameSize': 1040,
                'trailers': ['0A0D'],
                'assemblerId': 'eng_tm_subpkt',
                'parserId': '',
            }
        ]
    )
    assert routes[0]['assemblerId'] == 'eng_tm_subpkt'
    with pytest.raises(ValueError, match='未知'):
        PayloadSessionService.validate_routes(
            [{'framing': 'header_len', 'header': 'EB90', 'frameSize': 8, 'assemblerId': 'missing'}]
        )
    with pytest.raises(ValueError, match='未知解释器'):
        PayloadSessionService.validate_routes(
            [
                {
                    'framing': 'header_len',
                    'header': 'EB90',
                    'frameSize': 8,
                    'assemblerId': 'passthrough',
                    'parserId': 'nope',
                }
            ]
        )


def test_open_get_close_sync() -> None:
    r = _MemRedis()
    session = PayloadSessionService.open_session_sync(
        r,
        src_param='udp:127.0.0.1:9000',
        src_kind=SRC_KIND_UDP,
        assembler_id='passthrough',
        source='home',
    )
    assert session['srcKind'] == SRC_KIND_UDP
    assert session['assemblerId'] == ASSEMBLER_PASSTHROUGH
    got = PayloadSessionService.get_session_sync(r, 'udp:127.0.0.1:9000')
    assert got['source'] == 'home'
    assert PayloadSessionService.get_parser_id_sync(r, 'udp:127.0.0.1:9000') is None
    PayloadSessionService.close_session_sync(r, 'udp:127.0.0.1:9000', SRC_KIND_UDP)
    assert PayloadSessionService.get_session_sync(r, 'udp:127.0.0.1:9000', SRC_KIND_UDP) is None


def test_open_rejects_unknown_parser() -> None:
    with pytest.raises(ValueError, match='未知解释器'):
        PayloadSessionService.open_session_sync(
            _MemRedis(), src_param='serial:COM3', parser_id='nope'
        )


def test_list_options() -> None:
    parsers = {p['id'] for p in PayloadSessionService.list_parser_options()}
    assert 'tm_can_biu' in parsers and 'camera_sc_link41ep' in parsers
    can_as = {a['id'] for a in PayloadSessionService.list_assembler_options(SRC_KIND_CAN)}
    assert ASSEMBLER_CAN_BIU in can_as
    serial_as = {a['id'] for a in PayloadSessionService.list_assembler_options('serial')}
    assert ASSEMBLER_CAN_BIU not in serial_as


def test_session_alive_udp_and_can() -> None:
    mgr = MagicMock()
    mgr.list_opened.return_value = [
        {'type': 'net', 'deviceId': 'udp:127.0.0.1:9', 'alive': True},
        {'type': 'can', 'deviceId': 'can:3:0', 'alive': True, 'channels': [0]},
    ]
    with patch(
        'module_payload.collectors.process_manager.CollectorProcessManager.instance',
        return_value=mgr,
    ):
        assert PayloadSessionService._is_session_device_alive('udp:127.0.0.1:9') is True
        assert PayloadSessionService._is_session_device_alive('udp:1.1.1.1:1') is False
        assert PayloadSessionService._is_session_device_alive('can:3:0:0') is True
        assert PayloadSessionService._is_session_device_alive('can:3:0:1') is False
