"""协议目录：三家互不 import，框架只查表；新协议只登记目录表即可被框架调用。"""

from __future__ import annotations

import ast
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from module_payload import constants
from module_payload.protocol import protocol_catalog as catalog
from module_payload.cfg.telecontrol_cfg import TeleControlCfg
from module_payload.collectors.can_timers import parse_timer_op
from module_payload.fileplay.registry import resolve_fileplay
from module_payload.protocol.can_feed import CanFeedAssembler
from module_payload.protocol.hooks import ProtocolBindings
from module_payload.protocol.registry import (
    build_can_command,
    reset_tm_caches,
    resolve_assembler_cls,
    resolve_node_addr,
    resolve_parser,
    resolve_telecontrol,
    timed_tm_request,
)

BACKEND = Path(__file__).resolve().parents[1]
PROTOCOL_DIR = BACKEND / 'module_payload' / 'protocol'
FAMILY_PACKAGES = ('biu', 'xl', 'yj216')

# 这些框架文件只经注册表查协议，不得出现总线族名
FAMILY_FREE_FILES = (
    'module_payload/collectors/can_collector.py',
    'module_payload/collectors/can_timers.py',
    'module_payload/fileplay/registry.py',
    'module_payload/service/payload_canplay_service.py',
    'module_payload/service/device_can.py',
    'module_payload/protocol/registry.py',
    'module_payload/protocol/can_feed.py',
    'module_payload/protocol/hooks.py',
)
_FAMILY_WORD = re.compile(r'(?i)biu|yj216|(?<![a-z])xl(?![a-z])')


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
            out.extend(f'{node.module}.{alias.name}' for alias in node.names)
    return out


@pytest.mark.parametrize('family', FAMILY_PACKAGES)
def test_family_packages_do_not_import_each_other(family: str) -> None:
    others = [f'module_payload.protocol.{o}' for o in FAMILY_PACKAGES if o != family]
    bad = []
    for path in sorted((PROTOCOL_DIR / family).rglob('*.py')):
        for mod in _imported_modules(path):
            if any(mod == o or mod.startswith(o + '.') for o in others):
                bad.append(f'{path.relative_to(BACKEND).as_posix()}: {mod}')
    assert not bad, '\n'.join(bad)


@pytest.mark.parametrize('rel', FAMILY_FREE_FILES)
def test_framework_files_do_not_name_families(rel: str) -> None:
    text = (BACKEND / rel).read_text(encoding='utf-8')
    hits = [f'{i}: {line.strip()}' for i, line in enumerate(text.splitlines(), 1) if _FAMILY_WORD.search(line)]
    assert not hits, '\n'.join(hits)


BUS_PACKAGE_FILES = {'__init__.py', 'tc.py', 'tm.py', 'tm_timed.py'}


def _bus_package_dir(row: catalog.CanBusFamily) -> Path:
    return BACKEND.joinpath(*row.module.split('.'))


@pytest.mark.parametrize('row', catalog.CAN_BUS_FAMILIES, ids=lambda r: r.family)
def test_bus_packages_share_layout_and_names(row: catalog.CanBusFamily) -> None:
    """每条总线同一套文件；tc.py / tm.py 的公开函数不带族名。"""
    pkg = _bus_package_dir(row)
    assert pkg.name == 'can'
    assert {p.name for p in pkg.glob('*.py')} == BUS_PACKAGE_FILES
    bad = []
    for name in ('tc.py', 'tm.py'):
        tree = ast.parse((pkg / name).read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and not node.name.startswith('_') and _FAMILY_WORD.search(node.name):
                bad.append(f'{name}: {node.name}')
    assert not bad, '\n'.join(bad)


def test_no_old_protocol_file_names() -> None:
    old = [p for p in PROTOCOL_DIR.rglob('*.py') if p.name in ('telecontrol.py', 'timed_tm.py', 'fileplay.py')]
    assert not old, '\n'.join(p.relative_to(BACKEND).as_posix() for p in old)


def test_old_directories_are_gone() -> None:
    root = BACKEND / 'module_payload'
    assert not (root / 'protocol_catalog.py').exists()
    assert not list((root / 'assemblers').glob('*.py'))
    assert not list((root / 'parsers').glob('*.py'))
    assert not (root / 'cfg' / 'can_yc_frame.py').exists()
    assert not list((root / 'cfg').glob('*_telecontrol_assembler.py'))


def test_every_catalog_module_exports_bindings() -> None:
    from module_payload.protocol.registry import load_bindings

    modules = [row.module for row in catalog.CAN_BUS_FAMILIES]
    modules += [row.module for row in catalog.PLUGINS]
    modules += [row.module for row in catalog.TELECONTROL_PLUGINS]
    for module in modules:
        assert isinstance(load_bindings(module), ProtocolBindings), module


def test_yj216_send_and_addr_come_from_its_bindings() -> None:
    """YJ216 复帧经注册表按 8 字节切，线缆地址固定为 LCD 载荷；BIU 用请求值。"""
    from gpcan import CanCableParam, CanSendParam

    builder = SimpleNamespace(
        send_param=CanSendParam(),
        cable_param=CanCableParam(n_node_addr_to=13, n_cable_flag=0),
    )
    built = build_can_command('can_yj216', builder, bytes.fromhex('000915BB1100000000EA'), broadcast=False)
    assert [bytes(f.str_data) for f in built.frames] == [bytes.fromhex('000915BB11000000'), bytes.fromhex('00EA')]
    assert [f.un_id for f in built.frames] == [0x359, 0x35B]

    plain = MagicMock()
    build_can_command('can_biu', plain, b'\x0a\x11', broadcast=False)
    plain.build_telecommand.assert_called_once_with(b'\x0a\x11')
    build_can_command('can_xl', plain, b'\x30', broadcast=True)
    plain.build_broadcast.assert_called_once_with(b'\x30')

    assert resolve_node_addr('can_yj216', 0x0C) == 13
    assert resolve_node_addr('can_biu', 0x0C) == 0x0C
    assert resolve_node_addr('passthrough', None) is None


def test_unknown_telecontrol_protocol() -> None:
    with pytest.raises(ValueError, match='未知遥控封帧协议'):
        resolve_telecontrol('nope')


# ---------------------------------------------------------------------------
# 只登记目录表的假协议：框架文件不改也能调到
# ---------------------------------------------------------------------------

_FAKE_FAMILY = 'fake'
_FAKE_BUS = catalog.CanBusFamily(family=_FAKE_FAMILY).module
_FAKE_TC = 'tests_fake_tc_protocol'


class _FakeIngest:
    PARSER_ID = 'tm_can_fake'


def _fake_verify(raw: bytes) -> tuple[bool, str, bytes]:
    data = bytes(raw or b'')
    if len(data) >= 5 and data[2] == 0x3A:
        return True, 'OK', data[:5]
    return False, 'bad', b''


@pytest.fixture
def fake_protocol(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    hooks = SimpleNamespace(
        assemble=MagicMock(return_value={'hex': 'FA KE'}),
        plugin_assemble=MagicMock(return_value={'hex': 'PL UG'}),
        build=MagicMock(return_value='frames'),
        reset=MagicMock(),
    )
    bus = types.ModuleType(_FAKE_BUS)
    bus.BINDINGS = ProtocolBindings(
        ingest=_FakeIngest,
        reset_tm=hooks.reset,
        tm_cfg_files=('FAKE-TeleMetryCfg.json',),
        assemble=hooks.assemble,
        verify_tm=_fake_verify,
        build_can_command=hooks.build,
        timed_tm=lambda tick: (0.25, {'data_code': tick}),
        node_addr=lambda _requested: 0x21,
    )
    plugin = types.ModuleType(_FAKE_TC)
    plugin.BINDINGS = ProtocolBindings(assemble=hooks.plugin_assemble)
    monkeypatch.setitem(sys.modules, _FAKE_BUS, bus)
    monkeypatch.setitem(sys.modules, _FAKE_TC, plugin)

    # 目录表只登记族名；协议模块按推导出的路径放进 sys.modules
    row = catalog.CanBusFamily(family=_FAKE_FAMILY)
    monkeypatch.setattr(catalog, 'CAN_BUS_FAMILIES', catalog.CAN_BUS_FAMILIES + (row,))
    monkeypatch.setattr(
        catalog,
        'TELECONTROL_PLUGINS',
        catalog.TELECONTROL_PLUGINS
        + (catalog.TelecontrolPlugin(cfg_file='FAKE-X-TeleControlCfg.json', protocol='fake_x', module=_FAKE_TC),),
    )
    # 存储键前缀表在导入时由目录表派生
    monkeypatch.setitem(constants._BUS_TM_PREFIX, 'FAKE', 'fake')
    return hooks


def test_fake_protocol_reached_without_framework_change(fake_protocol: SimpleNamespace) -> None:
    order = {'component': []}
    out = TeleControlCfg.from_dict({'order': {}}, cfg_id='fake-tc', protocol='can_fake').assemble_order_dict(
        order, [1], seq=3
    )
    assert out == {'hex': 'FA KE'}
    fake_protocol.assemble.assert_called_once_with(order, [1], seq=3)
    out = TeleControlCfg.from_dict({'order': {}}, cfg_id='fake-x-tc', protocol='fake_x').assemble_order_dict(order)
    assert out == {'hex': 'PL UG'}

    cls = resolve_assembler_cls('can_fake')
    assert issubclass(cls, CanFeedAssembler)
    assert (cls.FAMILY, cls.GPCAN_PROTOCOL, cls.ASSEMBLER_ID) == ('fake', 'FAKE', 'can_fake')
    assert resolve_parser('tm_can_fake') is _FakeIngest

    assert build_can_command('can_fake', object(), b'\x01', broadcast=True) == 'frames'
    fake_protocol.build.assert_called_once()
    assert timed_tm_request('fake', 7) == (0.25, {'data_code': 7})
    assert resolve_node_addr('can_fake', 0x0D) == 0x21
    assert parse_timer_op('fake.timedTm.enable', {'enable': True}) == {
        'kind': 'timed_tm',
        'enable': True,
        'family': 'fake',
    }

    spec = resolve_fileplay('FAKE:01')
    assert spec is not None and spec.parse is _FakeIngest
    assert spec.extract(b'\x00\x00\x3a\x01\x00', 'FAKE:01') == [b'\x00\x00\x3a\x01\x00']

    reset_tm_caches('other.json')
    fake_protocol.reset.assert_not_called()
    reset_tm_caches('FAKE-TeleMetryCfg.json')
    fake_protocol.reset.assert_called_once_with()
