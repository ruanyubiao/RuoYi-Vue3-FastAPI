"""会话：组装器/解释器校验、同步开闭、网口 srcKind。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from exceptions.exception import ServiceException
from module_payload.constants import ASSEMBLER_CAN_BIU, ASSEMBLER_PASSTHROUGH, SRC_KIND_CAN, SRC_KIND_UDP
from module_payload.service.payload_device_service import PayloadDeviceService
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


class _AsyncMemRedis:
    """list_sessions 用的异步 Redis 门面，底层仍是同步内存 dict。"""

    def __init__(self, mem: _MemRedis) -> None:
        self._mem = mem

    async def scan_iter(self, match: str, count: int = 100):
        import fnmatch

        for key in list(self._mem.store):
            if fnmatch.fnmatch(key, match):
                yield key

    async def get(self, key: str):
        return self._mem.get(key)

    async def delete(self, key: str) -> None:
        self._mem.delete(key)


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
                'header': '1BCF',
                'frameSize': 844,
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


def test_open_session_parser_none_means_unbound() -> None:
    r = _MemRedis()
    session = PayloadSessionService.open_session_sync(
        r,
        src_param='serial:COM9',
        parser_id='none',
    )
    assert session['parserId'] == ''
    assert PayloadSessionService.get_parser_id_sync(r, 'serial:COM9') is None


def test_list_options() -> None:
    parsers = {p['id'] for p in PayloadSessionService.list_parser_options()}
    assert 'tm_can_biu' in parsers and 'tm_xl_camera' in parsers
    can_as = {a['id'] for a in PayloadSessionService.list_assembler_options(SRC_KIND_CAN)}
    assert ASSEMBLER_CAN_BIU in can_as
    serial_as = {a['id'] for a in PayloadSessionService.list_assembler_options('serial')}
    assert ASSEMBLER_CAN_BIU not in serial_as


def test_session_alive_udp_and_can() -> None:
    """存活判断从 SessionService 挪到 DeviceService，规则保持不变。"""
    mgr = MagicMock()
    mgr.list_opened.return_value = [
        {'type': 'net', 'deviceId': 'udp:127.0.0.1:9', 'alive': True},
        {'type': 'can', 'deviceId': 'can:3:0', 'alive': True, 'channels': [0]},
    ]
    with patch(
        'module_payload.collectors.process_manager.CollectorProcessManager.instance',
        return_value=mgr,
    ):
        assert PayloadDeviceService.is_session_device_alive('udp:127.0.0.1:9') is True
        assert PayloadDeviceService.is_session_device_alive('udp:1.1.1.1:1') is False
        assert PayloadDeviceService.is_session_device_alive('can:3:0:0') is True
        assert PayloadDeviceService.is_session_device_alive('can:3:0:1') is False


def test_list_sessions_without_is_alive_keeps_dead() -> None:
    """未传 is_alive 不裁剪，避免漏传时静默依赖 ProcessManager。"""
    import asyncio

    r = _MemRedis()
    PayloadSessionService.open_session_sync(
        r, src_param='udp:127.0.0.1:9', src_kind=SRC_KIND_UDP, assembler_id='passthrough'
    )
    PayloadSessionService.open_session_sync(
        r, src_param='udp:1.1.1.1:1', src_kind=SRC_KIND_UDP, assembler_id='passthrough'
    )
    ar = _AsyncMemRedis(r)

    async def _run():
        return await PayloadSessionService.list_sessions(ar)

    out = asyncio.run(_run())
    params = {s['srcParam'] for s in out}
    assert params == {'udp:127.0.0.1:9', 'udp:1.1.1.1:1'}


def test_list_sessions_prunes_when_is_alive_false() -> None:
    """传入 is_alive 后删除僵尸会话键，遥控列表不再显示已断开设备。"""
    import asyncio

    r = _MemRedis()
    PayloadSessionService.open_session_sync(
        r, src_param='udp:127.0.0.1:9', src_kind=SRC_KIND_UDP, assembler_id='passthrough'
    )
    PayloadSessionService.open_session_sync(
        r, src_param='udp:1.1.1.1:1', src_kind=SRC_KIND_UDP, assembler_id='passthrough'
    )
    ar = _AsyncMemRedis(r)

    async def _run():
        return await PayloadSessionService.list_sessions(
            ar, is_alive=lambda p: p == 'udp:127.0.0.1:9'
        )

    out = asyncio.run(_run())
    assert [s['srcParam'] for s in out] == ['udp:127.0.0.1:9']
    assert PayloadSessionService.get_session_sync(r, 'udp:1.1.1.1:1', SRC_KIND_UDP) is None
    assert PayloadSessionService.get_session_sync(r, 'udp:127.0.0.1:9', SRC_KIND_UDP) is not None
