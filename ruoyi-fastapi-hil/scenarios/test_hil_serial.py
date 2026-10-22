"""串口 / RS422 硬件在环（marker: hil_serial）：相机 v1.6/v1.7、热控电机、CPA-ZK、CPA 指向、YJ216 RS422。

只有一对实体串口线：测试机（本机）COM9（USB 转串口）⇄ 工控机（被测）COM8（PCIe 串口卡），6 个设备轮流接，
一次只测 HIL_SERIAL_TARGET（run_hil.bat serial <设备键>）选中的那个，其余 skip。
端口：hil.local.json serial.test_pc_port / ipc_port（HIL_SERIAL_PORT / HIL_IPC_SERIAL_PORT 覆盖）；
串口参数两端都取 cfg_device_connect.json 该设备键（相机 2000000 8O1、RKDJ/ZK/RS422 115200、CPA 指向 921600）。
"""
from __future__ import annotations

import pytest

from conftest import require_serial
from hil.config import CONFIG
from hil.protocol import frames as F
from hil.samples import get_bytes, hex_to_bytes, tm_fields
from scenarios.hil_steps import assert_fields_on_page, assert_refreshing, assert_tm_live

pytestmark = [pytest.mark.hil_serial, pytest.mark.asyncio(loop_scope='session')]


# key, 页面, 指令 id, 期望线上帧, 遥测断言方式
# 期望线上帧：黄金样例 key；@xxx = 按协议现算（见 _expected）；None = 以页面卡片显示的 HEX 为准（注意卡片显示的是配置模板，不一定是线上帧）
# v1.7 CAM_A0 与 v1.6 配置相同 → 同一黄金帧；ZK D1503 分量与 RKDJ 相同 → 用 RKDJ 黄金帧（默认值下）
CASES = [
    ('xl-camera', '/xl/board/camera', 'CAM_A0', 'camera_cam_a0_seq0', ('live', 'D8', 'passthrough_cam_d8')),
    ('xl-camera-v17', '/xl/board/camera_v17', 'CAM_A0', 'camera_cam_a0_seq0', ('live', 'D8V17', 'passthrough_cam_v17_d8')),
    ('xl-rkdj', '/xl/board/rkdj', 'D1503', 'xl_rkdj_d1503_defaults', ('page', 'RKDJ', 'passthrough_board_rkdj')),
    ('xl-zk', '/xl/board/zk', 'D1503', 'xl_rkdj_d1503_defaults', ('page', 'ZK', 'passthrough_board_zk')),
    ('xl-cpazx', '/xl/board/cpazx', 'CP01', '@cpazx_cp01', ('page', 'CPAZX', 'passthrough_cpazx')),
    ('yj216-rs422', '/yj216/rs422', 'RS422_TM_REQ', '@rs422_req_01', ('refresh', 'LCWP20', None)),
]


def _same_camera_frame(a: bytes, b: bytes) -> bool:
    """相机帧比对忽略帧序号与校验（页面每发一次 seq+1）。"""
    pa, pb = F.camera_parse(a), F.camera_parse(b)
    return bool(pa and pb and (pa['type'], pa['id'], pa['data']) == (pb['type'], pb['id'], pb['data']))


@pytest.mark.parametrize('key,path,order_id,wire_golden,tm', CASES, ids=[c[0] for c in CASES])
async def test_serial_loop(ui, api, key, path, order_id, wire_golden, tm):
    port, ipc_port = require_serial(key)
    print(f'[HIL] {key}: 测试机 {port} <-> 工控机 {ipc_port}  {CONFIG.serial_params(key)}')
    from hil.browser.pages import send_order
    from hil.hw.serial_sim import SerialSim

    # 预检（只读）：采集机上有该串口、且未被占用
    col = api.collector()
    ports = [str(p.get('port')) for p in col.get('serialPorts') or []]
    assert ipc_port in ports, f'采集机 {api.collector_host} 没有串口 {ipc_port}：{ports}'
    busy = api.busy_serial(ipc_port)
    if busy:
        pytest.fail(f'采集机 {api.collector_host} 上 {ipc_port} 已被打开（不是本次测试打开的，测试不会替你关闭）：{busy}，请在页面关闭后重跑')

    sim = SerialSim(key, port=port, cfg=CONFIG, dry_run=False)
    sim.start()
    sim.start_telemetry()
    opened = False
    try:
        api.open_serial(key, ipc_port)
        opened = True
        page = await ui.goto(path, settle_ms=800)

        # 1) 页面发指令 → 模拟器收到期望帧
        shown = await send_order(page, order_id)
        if wire_golden == '@rs422_req_01':
            expect = F.rs422_request(0x01)            # YJ216 RS422 遥测请求 01(LCWP20)，无数据
        elif wire_golden == '@cpazx_cp01':
            body = b'\xEB\x90\xFF' + bytes(8)        # CP01 取消使能：命令字 FF，数据段 8B 全 0
            expect = body + bytes([F.sum8(body)])     # 校验含 EB90（xl/cpazx/tc.py）
        elif wire_golden:
            expect = get_bytes(wire_golden)
        else:
            assert shown, f'{key}: 页面未显示 {order_id} 的 HEX，无法确定期望帧'
            expect = hex_to_bytes(shown)
        is_cam = key.startswith('xl-camera')
        got = sim.wait_for(lambda fr: _same_camera_frame(fr, expect) if is_cam else fr == expect, timeout=10)
        assert got, f'{key}: 10s 内未收到期望帧 {expect.hex(" ")}；最近收到: {[x.hex(" ") for x in sim.rx_items[-3:]]}'

        # 2) 遥测
        mode, table_key, golden = tm
        if mode == 'live':
            exclude = {'CAM001', 'CAM002'}  # 被模拟器改写为最后一条指令码/执行情况
            await assert_tm_live(ui, api, table_key, golden, exclude, CONFIG.tm_wait_s)
        elif mode == 'page':
            from hil.browser.pages import pick_fields

            await assert_fields_on_page(ui, api, page, table_key, pick_fields(tm_fields(golden)), CONFIG.tm_wait_s,
                                        root='.panel-tm .payload-tm-table')
        else:
            await assert_refreshing(page, CONFIG.tm_wait_s, root='.panel-tm .payload-tm-table')
    finally:
        if opened:
            try:
                api.close_serial(ipc_port)
            except Exception as exc:  # noqa: BLE001
                print(f'[HIL] 关闭工控机串口失败: {exc}')
        sim.stop()


PENDING_REPLY = [
    ('xl-rkdj', '热控电机 D15xx 复合帧指令的应答帧格式未定义（目前只靠周期遥测体现）'),
    ('xl-zk', 'CPA-ZK D15xx 指令应答格式未定义（同热控电机）'),
    ('xl-cpazx', 'CPA 指向 12B 遥控的应答格式未定义（目前只周期推 29B 遥测）'),
]


@pytest.mark.parametrize('key,why', PENDING_REPLY, ids=[c[0] for c in PENDING_REPLY])
async def test_serial_tc_reply_pending(key, why):
    """指令应答（暂不测）：协议确认后在 reply_map.json custom_rules 补 reply_hex 并改为断言。"""
    pytest.skip(f'待确认：{why}，见 TODO.md #1')
