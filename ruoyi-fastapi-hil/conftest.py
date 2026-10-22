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


_version_state: dict = {}


def ensure_app_version_match(api) -> tuple[str, str, str]:
    """会话内只核对一次：本地 backend version.py + frontend version.js ↔ 被测 /payload/device/version。"""
    if _version_state.get('done'):
        if _version_state.get('error'):
            pytest.fail(_version_state['error'])
        return _version_state['backend'], _version_state['frontend'], _version_state['dut']
    from hil.app_version import assert_local_matches_dut

    try:
        backend, frontend, dut = assert_local_matches_dut(api)
    except AssertionError as exc:
        _version_state['done'] = True
        _version_state['error'] = str(exc)
        pytest.fail(str(exc))
    except Exception as exc:  # noqa: BLE001
        msg = f'版本核对失败: {exc}'
        _version_state['done'] = True
        _version_state['error'] = msg
        pytest.fail(msg)
    _version_state.update(done=True, backend=backend, frontend=frontend, dut=dut, error=None)
    print(f'[HIL] 版本一致: backend={backend} frontend={frontend} 被测={dut}')
    return backend, frontend, dut


def _is_hw_group() -> bool:
    g = os.getenv('HIL_GROUP', '').strip().lower()
    return g.startswith(('can', 'serial', 'udp'))


@pytest.fixture(scope='session')
def api():
    reason = frontend_unreachable_reason()
    if reason:
        pytest.skip(reason)
    from hil.ipc_api import IpcApi

    a = IpcApi(CONFIG)
    a.login()
    ensure_app_version_match(a)
    if _is_hw_group():
        # 整次硬件分组开始时清场（idle=close-all+registry 兜底）
        try:
            a.ensure_hardware_idle(reason='session start', timeout_s=15.0)
        except Exception as exc:  # noqa: BLE001
            print(f'[HIL] session start ensure_idle 失败: {exc}', flush=True)
    return a


@pytest_asyncio.fixture(scope='session', loop_scope='session')
async def browser_session():
    """整个 pytest 会话共用一个有头浏览器（登录一次）。"""
    reason = frontend_unreachable_reason()
    if reason:
        pytest.skip(reason)
    from hil.browser.session import BrowserSession
    from hil.ipc_api import IpcApi

    s = BrowserSession(CONFIG)
    await s.start()
    await s.login()
    # ui 分组可能不用 api fixture；若尚未核对版本则再 login 一次做比对（与 api 共享 _version_state）
    if not _version_state.get('done'):
        a = IpcApi(CONFIG)
        a.login()
        ensure_app_version_match(a)
    yield s
    await s.close()


@pytest.fixture(autouse=True)
def _hil_close_all_before_hw(request):
    """每个会打开设备的 hil_* 用例开始前 ensure_hardware_idle（API 清场兜底；非用例显式关设备）。"""
    if not any(request.node.get_closest_marker(m) for m in ('hil_can', 'hil_serial', 'hil_udp')):
        return
    if request.node.get_closest_marker('skip'):
        return
    api = request.getfixturevalue('api')
    try:
        api.ensure_hardware_idle(reason=f'before {request.node.name}', timeout_s=12.0)
    except Exception as exc:  # noqa: BLE001
        # 不阻断收集期外的执行入口；真正占用仍由用例内 busy_can 暴露
        print(f'[HIL] 用例前 ensure_idle 失败: {exc}', flush=True)


@pytest_asyncio.fixture(loop_scope='session')
async def ui(browser_session, request):
    """每个用例拿到同一个浏览器；用例失败自动截图到本次运行目录 artifacts/<时间戳>/。"""
    browser_session.page_errors.clear()
    yield browser_session
    if _failed(request):
        await browser_session.screenshot(f'FAIL_{request.node.name}')


# ---------------- 硬件开关 → 自动 skip（默认探测本机硬件） ----------------
_hw_defaults_done = False


def _ensure_hw_defaults() -> None:
    """首次 skip 判定前：探测本机硬件并填空默认（不发遥控）。"""
    global _hw_defaults_done
    if _hw_defaults_done:
        return
    CONFIG.resolve_hw_defaults()
    _hw_defaults_done = True


def can_skip_reason(family: str | None) -> str | None:
    from hil.hw_detect import detect_can_local

    _ensure_hw_defaults()
    ok, why = detect_can_local()
    if not ok:
        return f'本机未检测到 CAN（vendor={CONFIG.can_vendor} Alyst/配置卡）：{why}'
    t = CONFIG.can_target
    if t:
        if t not in CAN_FAMILIES:
            return f'HIL_CAN_TARGET={t} 无效，应为 {"/".join(CAN_FAMILIES)}'
        if family and family != t:
            return (
                f'本轮 CAN 目标为 {t}（A/B 公用一根线，一轮只跑一个协议族；'
                f'可用 HIL_CAN_TARGET 或 run_hil.bat can <设备> 覆盖），{family} 跳过'
            )
        return None
    # 未指定：跑 default_can_targets（缺省 biu/xl/yj216 全量；all/can 无参用 round --auto 串行）
    allowed = CONFIG.default_can_targets()
    if family and family not in allowed:
        return f'本次默认 CAN 目标为 {"/".join(allowed)}（未设 HIL_CAN_TARGET），{family} 跳过'
    return None


def serial_skip_reason(key: str | None) -> str | None:
    from hil.hw_detect import detect_serial_local

    _ensure_hw_defaults()
    ok, why = detect_serial_local()
    if not ok:
        port = CONFIG.serial_port or '（未配置）'
        return f'本机未检测到串口 {port}：{why}'
    t = CONFIG.serial_target
    if t:
        if t not in SERIAL_KEYS:
            return f'HIL_SERIAL_TARGET={t} 无效，应为 {"/".join(SERIAL_KEYS)}'
        if key and key != t:
            return (
                f'本轮串口目标为 {t}（COM9↔COM8 公用，一轮只跑一个协议；'
                f'可用 HIL_SERIAL_TARGET 覆盖），{key} 跳过'
            )
    else:
        # 未指定：跑 hil.local.json serial.default_targets（缺省全部 SERIAL_KEYS）
        allowed = CONFIG.default_serial_targets()
        if key and key not in allowed:
            return f'本次默认串口目标为 {"/".join(allowed)}（未设 HIL_SERIAL_TARGET），{key} 跳过'
    if key and not CONFIG.serial_port_for(key):
        return f'未配置测试机串口（hil.local.json serial.test_pc_port 或 HIL_SERIAL_PORT）'
    if key and not CONFIG.ipc_serial_port_for(key):
        return f'未配置工控机串口（hil.local.json serial.ipc_port 或 HIL_IPC_SERIAL_PORT）'
    return None


def udp_skip_reason() -> str | None:
    from hil.hw_detect import detect_udp_local

    _ensure_hw_defaults()
    # 显式关闭
    import os as _os
    v = _os.getenv('HIL_UDP_ENABLE')
    if v is not None and v.strip() != '' and v.strip().lower() in ('0', 'false', 'no', 'off'):
        return '已关闭 UDP（HIL_UDP_ENABLE=0）'
    ok, why = detect_udp_local()
    if not ok:
        return f'本机未检测到 UDP 条件（无法绑定测试机端口 {CONFIG.udp_test_pc_port}）：{why}'
    if not CONFIG.udp_enable:
        # 探测成功但未 enable（不应发生，resolve 会打开）
        CONFIG.udp_enable = True
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



def _case_from_params(params: dict):
    """新闭环用例参数名是 case（GoldenCase）；兼容旧 family/key。"""
    case = params.get('case')
    if case is not None:
        return case
    return None


@pytest.hookimpl(trylast=True)  # 在 -m/-k 取消选择之后执行，计划里只列本次会收集的用例
def pytest_collection_modifyitems(config, items):
    """收集阶段就把未选中/未配置硬件/缺黄金的场景标成 skip，避免为了 skip 还去打开浏览器/登录工控机。"""
    plan = []
    for item in items:
        own = item.get_closest_marker('skip')
        reason = own.kwargs.get('reason', '') if own else None
        params = getattr(getattr(item, 'callspec', None), 'params', {})
        case = _case_from_params(params)
        family = params.get('family')
        key = params.get('key')
        if case is not None:
            proto = getattr(case, 'protocol', '') or ''
            if proto.startswith('can_'):
                family = proto.split('_', 1)[1]
            elif proto.startswith('serial_'):
                key = proto.split('_', 1)[1]
            # 缺黄金 / pending：收集期 skip，plan 能列出逐条
            st = getattr(case, 'status', 'ready')
            if reason is None and st != 'ready':
                reason = getattr(case, 'skip_reason', None) or f'缺黄金 status={st}'
        if reason is None and item.get_closest_marker('hil_can'):
            reason = can_skip_reason(family)
        elif reason is None and item.get_closest_marker('hil_udp'):
            reason = udp_skip_reason()
        elif reason is None and item.get_closest_marker('hil_serial'):
            reason = serial_skip_reason(key)
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
    from hil.app_version import versions_summary_line

    lines = [
        f'[{_started.get("group", "pytest")}]',
        f'  开始: {_started.get("t", "")}',
        f'  结束: {time.strftime("%Y-%m-%d %H:%M:%S")}',
        f'  通过: {cnt["passed"]}  失败: {cnt["failed"]}  错误: {cnt["error"]}  跳过: {cnt["skipped"]}  退出码: {int(exitstatus)}',
        f'  {versions_summary_line()}',
        f'  {CONFIG.hw_summary()}',
        '',
    ]
    rd = run_dir()
    with open(rd / 'summary.txt', 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    terminalreporter.write_sep('-', f'HIL 本次输出目录: {rd}')

    # 硬规则：每次测试读模板填报告（基于 junit）；collect-only 不填，避免与 catalog 子进程互相嵌套
    if getattr(config.option, 'collectonly', False) or __import__('os').environ.get('HIL_SKIP_TEMPLATE_REPORT') == '1':
        return
    try:
        from hil.report.fill_report import fill_report_from_run
        info = fill_report_from_run(rd, sync_first=False)
        miss = info.get('missing_in_template') or info.get('missing_from_catalog') or []
        terminalreporter.write_line(
            f"[HIL] 模板报告: {info.get('report')} filled={info.get('filled')} "
            f"missing_in_template={len(info.get('missing_in_template') or [])}"
        )
        if miss:
            terminalreporter.write_line('[HIL] 警告: 存在未映射到模板的自动化项，请 python -m hil.report sync')
    except Exception as exc:  # noqa: BLE001
        terminalreporter.write_line(f'[HIL] 模板报告生成失败: {exc}')

