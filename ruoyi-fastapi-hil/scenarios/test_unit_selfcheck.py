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


