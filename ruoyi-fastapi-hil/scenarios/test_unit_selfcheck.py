"""本机自测（marker: unit）：不连工控机、不开硬件。

覆盖：样本/配置是否还能加载（防仓库改名改格式）、菜单与 PAGES 是否一致、
各协议模拟器对黄金样本的组帧/拆帧/应答是否自洽（CAN 用 gpcan 原生 Builder/Parser 做「工控机侧」）。
"""
from __future__ import annotations

import re
import socket

import pytest

from hil.config import BACKEND_ROOT, CAN_FAMILIES, CONFIG, SERIAL_KEYS, UDP_KEYS, device_connect
from hil.protocol import frames as F
from hil.protocol.can_device import gpcan_available
from hil.protocol.serial_device import BoardDevice, CameraDevice, CpazxDevice, Rs422Device, make_serial_device
from hil.samples import get_bytes, iter_can_frames, tc_goldens, tm_fields, tm_goldens

pytestmark = pytest.mark.unit
GPCAN_OK, GPCAN_ERR = gpcan_available()
needs_gpcan = pytest.mark.skipif(not GPCAN_OK, reason=f'gpcan 不可用: {GPCAN_ERR}')

TM_KEYS_USED = ['passthrough_cam_d8', 'passthrough_cam_d9', 'passthrough_cam_v17_d8', 'passthrough_cam_v17_d9',
                'passthrough_biu_ff_1', 'passthrough_biu_fd_1', 'passthrough_biu_fb', 'passthrough_biu_f9',
                'passthrough_biu_f7', 'passthrough_biu_fe', 'passthrough_biu_fc', 'passthrough_xlcan_ff',
                'passthrough_board_rkdj', 'passthrough_board_zk', 'passthrough_board_dj', 'eng_board_dj',
                'passthrough_cpazx', 'passthrough_yj216_ff']
TC_KEYS_USED = ['biu_k1501_defaults', 'camera_cam_a0_seq0', 'xl_rkdj_d1503_defaults', 'xl_rkdj_d1503_formula']


# ---------------- 样本 / 配置 ----------------
def test_tm_goldens_present():
    g = tm_goldens()
    missing = [k for k in TM_KEYS_USED if k not in g]
    assert not missing, f'tm_golden_cases.json 缺少: {missing}'
    for k in TM_KEYS_USED:
        assert get_bytes(k), k


def test_tc_goldens_present():
    g = tc_goldens()
    missing = [k for k in TC_KEYS_USED if k not in g]
    assert not missing, f'telecontrol_wire_goldens.json 缺少: {missing}'


def test_can_recv_txt_parses():
    frames = list(iter_can_frames())
    assert len(frames) > 10
    assert all(len(d) <= 8 for _, _, d in frames)


def test_device_connect_keys():
    d = device_connect()
    for k in [f'{f}_can_{ab}' for f in CAN_FAMILIES for ab in 'ab'] + list(SERIAL_KEYS) + list(UDP_KEYS):
        assert k in d, f'cfg_device_connect.json 缺少设备键 {k}'
    for f in CAN_FAMILIES:
        assert int(d[f'{f}_can_a'].get('baudRate', 0)) == 500


@pytest.mark.parametrize('key', SERIAL_KEYS)
def test_serial_params_from_cfg(key):
    p = CONFIG.serial_params(key)
    e = device_connect()[key]
    assert p['baudrate'] == int(e['baudrate'])
    assert p['parity'] == str(e['parity'])[0]


def test_pages_cover_sys_menu():
    """PAGES 覆盖 sqlite 初始化 SQL（+补丁）中全部地检菜单路由。"""
    from hil.browser.pages import PAYLOAD_PAGES

    sql = (BACKEND_ROOT / 'sql' / 'ruoyi-fastapi-sqlite.sql').read_text(encoding='utf-8')
    for p in (BACKEND_ROOT / 'sql' / 'patches').glob('*.sql'):
        sql += p.read_text(encoding='utf-8')
    rows = {}
    for m in re.finditer(r"sys_menu\s+values\s*\(\s*'?(\d+)'?\s*,\s*'([^']*)'\s*,\s*'?(\d+)'?\s*,\s*'?\d+'?\s*,\s*'([^']*)'\s*,\s*(NULL|null|'[^']*')", sql, re.I):
        rows[int(m.group(1))] = (m.group(2), int(m.group(3)), m.group(4), m.group(5).strip("'"))

    def full(mid):
        parts = []
        while mid in rows:
            name, parent, path, comp = rows[mid]
            parts.append(path.strip('/'))
            mid = parent
        return '/' + '/'.join(p for p in reversed(parts) if p)

    want = {full(i) for i, r in rows.items() if r[3].startswith('payload/')}
    have = {p for p, _, _ in PAYLOAD_PAGES}
    assert want, '没解析出任何地检菜单'
    assert not (want - have), f'PAGES 缺少菜单路由: {sorted(want - have)}'


# ---------------- CAN（gpcan 原生组帧/拆帧做工控机侧） ----------------
@needs_gpcan
@pytest.mark.parametrize('family,req_kw,golden', [
    ('biu', {'data_code': 0xFF}, 'passthrough_biu_ff_1'),
    ('biu', {'data_code': 0xFC}, 'passthrough_biu_fc'),
    ('xl', {'sec_header': 1}, 'passthrough_xlcan_ff'),
    ('xl', {'sec_header': 2}, 'passthrough_xlcan_ff'),
    ('yj216', {'data_code': 0xFF}, None),
])
def test_can_device_tm_roundtrip(family, req_kw, golden):
    from hil.hw.can_sim import CanSim
    from hil.protocol.can_device import ground_build, ground_parse

    sim = CanSim(family, dry_run=True)
    replies = sim.handle_frames(ground_build(family, 'tm_request', **req_kw))
    got = ground_parse(family, replies)
    assert len(got) == 1, f'{family} 遥测应答拼帧失败: {len(replies)} 帧'
    if golden:
        assert got[0] == get_bytes(golden)
    else:  # YJ216：38B，3A FF，SUM 正确，请求计数=1
        fr = got[0]
        assert len(fr) == 38 and fr[0] == 0x3A and fr[1] == 0xFF and fr[-1] == sum(fr[:-1]) & 0xFF
        assert fr[2] == 1


@needs_gpcan
@pytest.mark.parametrize('family', CAN_FAMILIES)
@pytest.mark.parametrize('payload_hex', ['0A 91 00 01 00 01 55 55', '00 0F 0F 00 11 22 33 44 55 66 77 88 99 AA BB CC DD EE'])
def test_can_device_receives_telecommand(family, payload_hex):
    from hil.hw.can_sim import CanSim
    from hil.protocol.can_device import ground_build

    data = bytes.fromhex(payload_hex)
    sim = CanSim(family, dry_run=True)
    assert sim.handle_frames(ground_build(family, 'telecommand', data)) == []
    assert sim.model.telecommands() == [data]
    assert sim.wait_for(lambda ev: ev.kind == 'telecommand' and ev.payload == data, timeout=0.1)


@needs_gpcan
def test_biu_reply_id_matches_recorded_sample():
    """模拟器 BIU 上行首帧 ID 与真实收包记录（biu_can_a_*.txt）一致：0x769 = 从节点|点对点应用|激光B|A线|首帧。"""
    from hil.protocol.can_device import CanDeviceModel, ground_build

    m = CanDeviceModel('biu')
    replies = m.feed(ground_build('biu', 'tm_request', data_code=0xFF))
    recorded = next(iter_can_frames())[1]
    assert replies[0][0] == recorded == 0x769


# ---------------- 串口设备 ----------------
def test_camera_golden_tc_frame_valid():
    p = F.camera_parse(get_bytes('camera_cam_a0_seq0'))
    assert p and p['type'] == 0xD7 and p['data'] == b'\x01'


@pytest.mark.parametrize('v17', [False, True])
def test_camera_switch_and_ack(v17):
    from hil.hw.serial_sim import SerialSim

    sim = SerialSim('xl-camera-v17' if v17 else 'xl-camera', port='', dry_run=True)
    cam: CameraDevice = sim.model
    assert cam.telemetry() == []                          # 上电默认不推
    sim.handle_bytes(get_bytes('camera_cam_a0_seq0'))     # D7 01 遥测开
    tm = cam.telemetry()
    assert F.camera_parse(tm[0])['type'] == 0xD8 and tm[1][:2] == b'\xEB\xD9'  # D9 快遥测为 20B 短帧
    replies = sim.handle_bytes(F.camera_frame(0xD0, 0, 5, bytes([0xA7, 0x01])))
    d8 = F.camera_parse(replies[0])
    assert d8 and d8['type'] == 0xD8 and d8['data'][:2] == bytes([0xA7, 0xAA])
    sim.handle_bytes(F.camera_frame(0xD7, 0, 6, b'\x00'))  # 遥测关
    assert cam.telemetry() == []


def test_camera_stream_split_two_frames_in_one_chunk():
    cam = CameraDevice()
    cam.feed(get_bytes('camera_cam_a0_seq0') + F.camera_frame(0xD0, 0, 1, b'\xA1\x01'))
    assert len(cam.received) == 2


@pytest.mark.parametrize('key', ['xl-rkdj', 'xl-zk'])
def test_board_tm_and_tc(key):
    dev = BoardDevice(key)
    assert F.board_tm_valid(dev.telemetry()[0])
    tc = get_bytes('xl_rkdj_d1503_defaults')
    assert sum(tc[2:-1]) & 0xFF == tc[-1], 'D1503 黄金样例校验（类型字节起累加）'
    dev.feed(tc + get_bytes('xl_rkdj_d1503_formula'))
    assert dev.received == [tc, get_bytes('xl_rkdj_d1503_formula')]


def test_cpazx_tm_valid():
    assert F.cpazx_tm_valid(CpazxDevice().telemetry()[0])


@pytest.mark.parametrize('cmd,table', sorted(F.RS422_CMD_TO_TABLE.items()))
def test_rs422_request_response(cmd, table):
    dev = Rs422Device()
    replies = dev.feed(F.rs422_request(cmd))
    assert len(replies) == 1 and F.rs422_response_valid(replies[0])
    n = (replies[0][3] << 8) | replies[0][4]
    assert n == dev.spans[table]


def test_eng_udp_frame_valid():
    assert F.eng_frame_valid(get_bytes('eng_board_dj'))


@pytest.mark.parametrize('key', SERIAL_KEYS)
def test_make_serial_device(key):
    assert make_serial_device(key).key == key


def test_tm_fields_have_ids():
    for k in ('passthrough_cam_d8', 'passthrough_biu_ff_1', 'passthrough_board_rkdj', 'passthrough_cpazx', 'passthrough_yj216_ff'):
        assert all('id' in f and 'show' in f for f in tm_fields(k))


# ---------------- 自定义应答表 ----------------
def test_reply_map_loads():
    from hil.hw.reply import ReplyMap

    rm = ReplyMap.load(CONFIG.reply_map_path)
    targets = set(CAN_FAMILIES) | set(SERIAL_KEYS) | set(UDP_KEYS)
    assert all(r.get('target') in targets for r in rm.rules)


# ---------------- UDP 本机回环 ----------------
def test_udp_sim_loopback():
    from hil.hw.udp_sim import UdpSim

    peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    peer.bind(('127.0.0.1', 0))
    peer.settimeout(3)
    sim = UdpSim(bind=('127.0.0.1', 0), peer=peer.getsockname())
    sim.start()
    try:
        sim.start_telemetry(0.2)
        data, _ = peer.recvfrom(4096)
        assert F.eng_frame_valid(data)
        peer.sendto(b'\xEB\x90\x01', sim.bind)
        assert sim.wait_for(lambda it: it[1] == b'\xEB\x90\x01', timeout=3)
    finally:
        sim.stop()
        peer.close()


def test_snapshot_machines_devices_only():
    """snapshot 只认 2f13aeb 的 devices[]；仅有旧 collectors[] 或缺少 devices 时必须失败。"""
    import pytest
    from hil.ipc_api import IpcApi, IpcApiError

    new = {
        'parsers': [],
        'assemblers': [],
        'devices': [
            {
                'host': 'gk3', 'online': True, 'canVendors': [{'value': 3}],
                'serialPorts': [{'port': 'COM8'}], 'registry': [],
                'can': [], 'serialOpened': [], 'netOpened': [], 'sessions': [],
            },
        ],
    }
    assert [m['host'] for m in IpcApi.machines_from_snapshot(new)] == ['gk3']
    assert IpcApi.machines_from_snapshot({'devices': []}) == []
    assert IpcApi.machines_from_snapshot({'devices': None}) == []

    old_only = {
        'parts': [],
        'collectorHost': 'local',
        'collectorOnline': False,
        'collectors': [{'host': 'gk3', 'online': True}],
    }
    with pytest.raises(IpcApiError, match=r'devices|2f13aeb'):
        IpcApi.machines_from_snapshot(old_only)
    with pytest.raises(IpcApiError, match=r'devices|2f13aeb'):
        IpcApi.machines_from_snapshot({})
    with pytest.raises(IpcApiError, match=r'devices|2f13aeb'):
        IpcApi.machines_from_snapshot(None)
    # 即使同时带 collectors，也只看 devices（且必须有该键）
    both = {**new, 'collectors': [{'host': 'stale', 'online': True}]}
    assert [m['host'] for m in IpcApi.machines_from_snapshot(both)] == ['gk3']

def test_local_app_version_file():
    """仓库 backend version.py + frontend version.js 的 appVersion 可读且同为 主.次.修订.YYYYMMDD。"""
    import re
    from hil.app_version import local_backend_version, local_frontend_version

    vb = local_backend_version()
    vf = local_frontend_version()
    assert re.fullmatch(r'\d+\.\d+\.\d+\.\d{8}', vb), vb
    assert re.fullmatch(r'\d+\.\d+\.\d+\.\d{8}', vf), vf
    assert vb == vf, f'本地 backend={vb} 与 frontend={vf} 不一致'


def test_assert_versions_match_helper():
    """三边版本比对：一致通过；不一致抛 AssertionError 且含 backend/frontend/被测。"""
    from hil import app_version as av

    class FakeApi:
        def __init__(self, v):
            self._v = v

        def version(self):
            return {'appVersion': self._v}

    backend = av.local_backend_version()
    frontend = av.local_frontend_version()
    assert backend == frontend
    assert av.assert_local_matches_dut(FakeApi(backend)) == (backend, frontend, backend)
    try:
        with pytest.raises(AssertionError, match=r'不一致|backend=|frontend='):
            av.assert_local_matches_dut(FakeApi(backend + '.mismatch'))
    finally:
        # 勿把故意制造的 mismatch 留在 CONFIG（会污染 summary.txt）
        av.record_versions(backend, frontend, None)


def test_hw_detect_helpers_callable():
    """本机硬件探测接口可调用（不要求当前一定有硬件；返回 (bool, str)）。"""
    from hil.hw_detect import detect_can_local, detect_serial_local, detect_udp_local, clear_detect_cache

    clear_detect_cache()
    for fn in (detect_can_local, detect_serial_local, detect_udp_local):
        ok, why = fn()
        assert isinstance(ok, bool), fn
        assert isinstance(why, str) and why, (fn, why)


def test_default_hw_targets_cover_all_protocols():
    """全量默认：CAN=biu/xl/yj216，串口=全部 SERIAL_KEYS，UDP=xl_udp_dj。"""
    from hil.config import CAN_FAMILIES, CONFIG, SERIAL_KEYS, UDP_KEYS

    assert CONFIG.default_can_targets() == CAN_FAMILIES
    assert set(CONFIG.default_can_targets()) == {'biu', 'xl', 'yj216'}
    assert CONFIG.default_serial_targets() == SERIAL_KEYS
    assert set(CONFIG.default_serial_targets()) == {
        'xl-camera', 'xl-camera-v17', 'xl-rkdj', 'xl-zk', 'xl-cpazx', 'yj216-rs422',
    }
    assert CONFIG.default_udp_keys() == UDP_KEYS == ('xl_udp_dj',)


def test_can_skip_allows_all_families_when_no_target(monkeypatch):
    """未设 HIL_CAN_TARGET 且探测到卡时，三个协议族均不应因「未选目标」被 skip。"""
    import conftest as cf
    from hil.config import CONFIG
    from hil import hw_detect

    monkeypatch.setattr(CONFIG, 'can_target', '')
    monkeypatch.setattr(hw_detect, 'detect_can_local', lambda: (True, 'mock'))
    # reset ensure cache
    cf._hw_defaults_done = False
    monkeypatch.setattr(CONFIG, 'resolve_hw_defaults', lambda: None)
    for fam in ('biu', 'xl', 'yj216'):
        assert cf.can_skip_reason(fam) is None, fam



def test_round_tip_no_swap_wire():
    """共用线场景：轮测提示不提换线/接入设备。"""
    from hil import round as R
    tip = R._tip('can', 'yj216')
    assert '请接入' not in tip and '未换接' not in tip and '换设备' not in tip
    assert 'yj216' in tip.lower() or 'YJ216' in tip
    tip_s = R._tip('serial', 'xl-camera')
    assert '请接入' not in tip_s and '未换接' not in tip_s and '换设备' not in tip_s


def test_ensure_hardware_idle_api_exists():
    from hil.ipc_api import IpcApi
    assert callable(getattr(IpcApi, 'ensure_hardware_idle'))
    assert callable(getattr(IpcApi, '_force_close_registry_leftovers'))


def test_goldens_manifest_loaded():
    from hil.goldens import build_and_write_goldens, load_all_cases, norm_hex, hex_diff, fields_diff
    stats = build_and_write_goldens()
    assert stats.get('can_biu', 0) >= 1
    cases = load_all_cases()
    assert cases, 'scenarios/goldens 应有用例'
    ready = [c for c in cases if c.status == 'ready']
    missing = [c for c in cases if c.status == 'missing_tx_golden']
    assert ready, '至少应有可跑闭环'
    assert missing, '大量缺黄金应标 missing_tx_golden 供 plan skip'
    # 有线帧的 ready 必须带 tx 或 tm_observe/tm_request
    for c in ready:
        if c.ui_action == 'send_order':
            assert c.tx_expect_hex and norm_hex(c.tx_expect_hex)
    assert 'expect=' in hex_diff('00 01', '00 02')
    assert fields_diff([{'id': 'A', 'show': '1'}], {'A': '2'}) == {'A': ('1', '2')}


def test_send_helpers_are_ui_click_only():
    """发遥控辅助必须是 Playwright 点击路径（源码含 click / 发送指令），禁止 IPC send API。"""
    from pathlib import Path
    src = Path('hil/browser/pages.py').read_text(encoding='utf-8')
    assert 'async def send_order' in src and '发送指令' in src
    assert 'async def send_command_order' in src
    assert 'sendTelecontrol' not in src and 'send_board' not in src.lower()
