"""UDP 硬件在环（marker: hil_udp）：地检板 xl_udp_dj 工程遥测。

需要：HIL_UDP_ENABLE=1（run_hil.bat udp 自动设置）。测试机 IP 自动探测与工控机同网段的本机地址（HIL_TEST_PC_IP 覆盖）。
端口固定（hil.local.json udp）：工控机（被测）绑 0.0.0.0:66，对端 = 测试机（本机）<IP>:99。
流程：模拟器绑 0.0.0.0:99 并周期推 eng_board_dj（844B）到 工控机:66 → 经接口在工控机打开 UDP
     （source=xl_udp_dj，remoteHost 填测试机 IP / remotePort 99）→ 地检板页表格刷新。
注意：页面「新建UDP连接」对话框按 cfg_device_connect.json 锁定本机/远程为 127.0.0.1，无法填测试机 IP，所以这里走接口（见 TODO.md）。
"""
from __future__ import annotations

import pytest

from conftest import require_udp
from hil.config import CONFIG
from scenarios.hil_steps import assert_refreshing

pytestmark = [pytest.mark.hil_udp, pytest.mark.asyncio(loop_scope='session')]


async def test_udp_dj_loop(ui, api):
    require_udp()
    from hil.hw.udp_sim import UdpSim

    busy = api.busy_net(CONFIG.udp_ipc_port)
    if busy:
        pytest.fail(f'采集机 {api.collector_host} 上 UDP 端口 {CONFIG.udp_ipc_port} 已被打开（不是本次测试打开的）：{busy}，请在页面关闭后重跑')
    sim = UdpSim('xl_udp_dj', CONFIG)
    sim.start()
    sim.start_telemetry()
    opened = None
    try:
        ip, src = CONFIG.test_pc_ip_info()
        print(f'[HIL] UDP 测试机 IP={ip}（{src}） bind={sim.bind} -> 工控机 {sim.peer}')
        opened = api.open_udp('xl_udp_dj', remote_host=ip, remote_port=CONFIG.udp_test_pc_port, local_port=CONFIG.udp_ipc_port)
        assert opened['request']['remoteHost'] == ip
        page = await ui.goto('/xl/board/dj', settle_ms=800)
        await assert_refreshing(page, CONFIG.tm_wait_s, root='.panel-tm .payload-tm-table')
        assert sim.tx_count > 0
    finally:
        if opened:
            try:
                api.close_udp(opened['request'])
            except Exception as exc:  # noqa: BLE001
                print(f'[HIL] 关闭工控机 UDP 失败: {exc}')
        sim.stop()
