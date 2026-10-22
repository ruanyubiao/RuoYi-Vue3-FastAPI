"""HIL 公共 fixture：路径、失败截图钩子、浏览器/接口会话、硬件开关自动 skip。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import os  # noqa: E402
import time  # noqa: E402

from hil.config import CAN_FAMILIES, CONFIG, SERIAL_KEYS, run_dir  # noqa: E402


# ---------------- 失败截图：把每个阶段的报告挂到 item 上 ----------------
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f'rep_{rep.when}', rep)


def _failed(request) -> bool:
    rep = getattr(request.node, 'rep_call', None)
    return bool(rep and rep.failed)


# ---------------- 工控机可达性（会话级缓存） ----------------
_reach: dict[str, str | None] = {}


def frontend_unreachable_reason() -> str | None:
    if 'r' not in _reach:
        from hil.browser.session import FrontendUnreachable, check_reachable

        try:
            check_reachable(CONFIG.frontend_url, timeout=3)
            _reach['r'] = None
        except FrontendUnreachable as exc:
            _reach['r'] = str(exc)
    return _reach['r']


@pytest.fixture(scope='session')
def cfg():
    return CONFIG


@pytest.fixture(scope='session')
def api():
    reason = frontend_unreachable_reason()
    if reason:
        pytest.skip(reason)
    from hil.ipc_api import IpcApi

    a = IpcApi(CONFIG)
    a.login()
    return a


@pytest_asyncio.fixture(scope='session', loop_scope='session')
async def browser_session():
    """整个 pytest 会话共用一个有头浏览器（登录一次）。"""
    reason = frontend_unreachable_reason()
    if reason:
        pytest.skip(reason)
    from hil.browser.session import BrowserSession

    s = BrowserSession(CONFIG)
    await s.start()
    await s.login()
    yield s
    await s.close()


@pytest_asyncio.fixture(loop_scope='session')
async def ui(browser_session, request):
    """每个用例拿到同一个浏览器；用例失败自动截图到本次运行目录 artifacts/<时间戳>/。"""
    browser_session.page_errors.clear()
    yield browser_session
    if _failed(request):
        await browser_session.screenshot(f'FAIL_{request.node.name}')


# ---------------- 硬件开关 → 自动 skip ----------------
def can_skip_reason(family: str | None) -> str | None:
    t = CONFIG.can_target
    if not t:
        return '未选择被测 CAN 设备（run_hil.bat can biu|xl|yj216 或 HIL_CAN_TARGET），不打开 CAN 硬件'
    if t not in CAN_FAMILIES:
        return f'HIL_CAN_TARGET={t} 无效，应为 {"/".join(CAN_FAMILIES)}'
    if family and family != t:
        return f'本次被测 CAN 设备为 {t}（同一对 CAN 线同一时刻只接一个设备），{family} 跳过'
    return None


def serial_skip_reason(key: str | None) -> str | None:
    t = CONFIG.serial_target
    if not t:
        return '未选择被测串口设备（run_hil.bat serial <设备键> 或 HIL_SERIAL_TARGET），不打开串口'
    if t not in SERIAL_KEYS:
        return f'HIL_SERIAL_TARGET={t} 无效，应为 {"/".join(SERIAL_KEYS)}'
    if key and key != t:
        return f'本次被测串口设备为 {t}（只有一对串口线 COM9<->COM8），{key} 跳过'
    if key and not CONFIG.serial_port_for(key):
        return f'未配置测试机串口（hil.local.json serial.test_pc_port 或 HIL_SERIAL_PORT）'
    if key and not CONFIG.ipc_serial_port_for(key):
        return f'未配置工控机串口（hil.local.json serial.ipc_port 或 HIL_IPC_SERIAL_PORT）'
    return None


def udp_skip_reason() -> str | None:
    if not CONFIG.udp_enable:
        return '未启用 UDP（run_hil.bat udp 或 HIL_UDP_ENABLE=1），不打开 UDP'
    if not CONFIG.test_pc_ip:
        return CONFIG.test_pc_ip_info()[1]
    return None


def require_can(family: str):
    r = can_skip_reason(family)
    if r:
        pytest.skip(r)


def require_serial(key: str) -> tuple[str, str]:
    r = serial_skip_reason(key)
    if r:
        pytest.skip(r)
    return CONFIG.serial_port_for(key), CONFIG.ipc_serial_port_for(key)


def require_udp():
    r = udp_skip_reason()
    if r:
        pytest.skip(r)


def pytest_report_header(config):
    return ['HIL frontend=' + CONFIG.frontend_url + f' headed={CONFIG.headed}', 'HIL ' + CONFIG.hw_summary()]


def pytest_addoption(parser):
    parser.addoption('--hil-plan', action='store_true',
                     help='只列出每个用例在当前目标下会 RUN 还是 SKIP（及原因），不执行任何用例、不碰硬件')


@pytest.hookimpl(trylast=True)  # 在 -m/-k 取消选择之后执行，计划里只列本次会收集的用例
def pytest_collection_modifyitems(config, items):
    """收集阶段就把未选中/未配置硬件的场景标成 skip，避免为了 skip 还去打开浏览器/登录工控机。"""
    plan = []
    for item in items:
        own = item.get_closest_marker('skip')
        reason = own.kwargs.get('reason', '') if own else None
        params = getattr(getattr(item, 'callspec', None), 'params', {})
        if reason is None and item.get_closest_marker('hil_can'):
            reason = can_skip_reason(params.get('family'))
        elif reason is None and item.get_closest_marker('hil_udp'):
            reason = udp_skip_reason()
        elif reason is None and item.get_closest_marker('hil_serial'):
            reason = serial_skip_reason(params.get('key'))
            if reason is None and 'pending' in item.name:
                reason = '待确认应答格式（见 TODO.md）'
        if reason and not own:
            item.add_marker(pytest.mark.skip(reason=reason))
        plan.append((item.nodeid, reason))
    if config.getoption('--hil-plan'):
        tr = config.pluginmanager.get_plugin('terminalreporter')
        lines = ['', f'HIL 执行计划（{CONFIG.hw_summary()}）']
        lines += [f'  {"SKIP" if r else "RUN "}  {nid}' + (f'  —— {r}' if r else '') for nid, r in plan]
        text = '\n'.join(lines)
        if tr:
            tr.write_line(text)
        else:
            print(text)
        with open(run_dir() / 'plan.txt', 'a', encoding='utf-8') as f:
            f.write(text + '\n')
        config.hook.pytest_deselected(items=list(items))
        items[:] = []


# ---------------- 运行目录：junit / pytest 日志 / summary ----------------
_GROUP_BY_MARK = {'unit': 'unit', 'ui_only': 'ui', 'hil_can': 'can', 'hil_serial': 'serial', 'hil_udp': 'udp'}
_started = {}


def _group_name(config) -> str:
    g = os.getenv('HIL_GROUP', '').strip()
    if g:
        return g
    m = (config.getoption('markexpr', '') or '').strip()
    return _GROUP_BY_MARK.get(m, re.sub(r'\W+', '_', m) or 'pytest')


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """直接 python -m pytest 时也自动落到 artifacts/<时间戳>/：未指定 --junitxml / --log-file 就补上。"""
    rd = run_dir()
    group = _group_name(config)
    if config.getoption('--hil-plan', False):  # 只看计划：不出 junit/log/summary，只写 plan.txt
        _started['plan'] = True
        return
    _started['t'] = time.strftime('%Y-%m-%d %H:%M:%S')
    _started['group'] = group
    if hasattr(config.option, 'xmlpath') and not config.option.xmlpath:
        config.option.xmlpath = str(rd / f'junit_{group}.xml')
    if hasattr(config.option, 'log_file') and not config.option.log_file:
        config.option.log_file = str(rd / f'pytest_{group}.log')
        if not getattr(config.option, 'log_file_level', None):
            config.option.log_file_level = 'INFO'


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """在运行目录追加 summary.txt（每个分组一段），并打印目录路径。"""
    if _started.get('plan'):
        terminalreporter.write_sep('-', f'HIL 计划已写入: {run_dir() / "plan.txt"}')
        return
    st = terminalreporter.stats
    cnt = {k: len([r for r in st.get(k, []) if getattr(r, 'when', 'call') in ('call', 'setup', 'teardown')])
           for k in ('passed', 'failed', 'skipped', 'error')}
    cnt['passed'] = len([r for r in st.get('passed', []) if r.when == 'call'])
    lines = [
        f'[{_started.get("group", "pytest")}]',
        f'  开始: {_started.get("t", "")}',
        f'  结束: {time.strftime("%Y-%m-%d %H:%M:%S")}',
        f'  通过: {cnt["passed"]}  失败: {cnt["failed"]}  错误: {cnt["error"]}  跳过: {cnt["skipped"]}  退出码: {int(exitstatus)}',
        f'  {CONFIG.hw_summary()}',
        '',
    ]
    rd = run_dir()
    with open(rd / 'summary.txt', 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    terminalreporter.write_sep('-', f'HIL 本次输出目录: {rd}')
