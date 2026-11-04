"""页面清单与通用页面动作（选择器以 ruoyi-fastapi-frontend/src 源码为准）。"""
from __future__ import annotations

from pathlib import Path
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 自测时不强依赖 playwright
    from playwright.async_api import Page

# (路由, 页内特征选择器, 菜单名)。路由来自 sql/ruoyi-fastapi-*.sql 的 sys_menu（含 patches/V0001 数字转换），
# 选择器与 ruoyi-fastapi-test/payload/test_payload_pages.py 最新版一致。
PAYLOAD_PAGES: list[tuple[str, str, str]] = [
    ('/index', '.device-service-page', '首页·dashboard设备服务'),
    ('/biu/telecontrol/control', '.control-page', 'BIU·控制'),
    ('/biu/telecontrol/command', '.command-page', 'BIU·遥控'),
    ('/biu/telecontrol/sequence', 'input[placeholder="请输入序列名称"]', 'BIU·指令序列'),
    ('/xl/telecontrol/control', '.control-page', 'XL·控制'),
    ('/xl/telecontrol/command', '.command-page', 'XL·遥控'),
    ('/xl/telecontrol/sequence', 'input[placeholder="请输入序列名称"]', 'XL·指令序列'),
    ('/yj216/telecontrol/control', '.control-page', 'YJ216·控制'),
    ('/yj216/telecontrol/command', '.command-page', 'YJ216·遥控'),
    ('/yj216/telecontrol/sequence', 'input[placeholder="请输入序列名称"]', 'YJ216·指令序列'),
    ('/yj216/rs422', '.board-page', 'YJ216·RS422测试'),
    ('/telemetry/live', '.tm-page', '遥测·实时数据'),
    ('/telemetry/curve', '.curve-page', '遥测·实时曲线'),
    ('/telemetry/archive', '.curve-page', '遥测·历史CAN曲线'),
    ('/telemetry/canHistory', '.replay-page', '遥测·历史CAN数据'),
    ('/telemetry/fileHistory', '.replay-page', '遥测·历史文件数据'),
    ('/telemetry/fileCurve', '.curve-page', '遥测·历史文件曲线'),
    ('/xl/board/camera', '.camera-page', '单板·相机v1.6'),
    ('/xl/board/camera_v17', '.camera-page', '单板·相机v1.7'),
    ('/xl/board/rkdj', '.board-page', '单板·热控电机'),
    ('/xl/board/zk', '.board-page', '单板·CPA-ZK'),
    ('/xl/board/dj', '.board-page', '单板·地检板'),
    ('/xl/board/cpazx', '.board-page', '单板·CPA指向'),
    ('/xl/refactor', 'text=暂为空白页', '重构'),
    ('/debug/simulate', 'text=通用数据发送模拟', '调试·数据模拟'),
    ('/debug/xfer', '.xfer-page', '调试·数据收发'),
    ('/debug/configFile', 'text=重新载入配置', '调试·配置文件'),
    ('/debug/tmCalc', '.tm-calc-page', '调试·遥测计算'),
    ('/debug/checksum', '.checksum-page', '调试·校验计算'),
    ('/debug/numconv', '.numconv-page', '调试·数字转换'),
    ('/debug/timeconv', '.timeconv-page', '调试·时间转换'),
    ('/debug/logDownload', '.log-download-page', '调试·日志下载'),
]

# 页面上的关键按钮/文案（只检查可见，不点击）
KEY_ELEMENTS: list[tuple[str, str, str]] = [
    # 首页 = views/dashboard/index.vue
    ('/index', 'button', '新建 CAN 连接'),
    ('/index', 'button', '新建 UDP 连接'),
    ('/index', 'button', '新建串口连接'),
    ('/index', 'text', '采集设备'),
    ('/index', 'text', '设备服务'),
    ('/index', 'button', '关闭所有连接'),
    # 遥控控制：开连接 + 发送入口可见
    ('/biu/telecontrol/control', 'button', '新建CAN连接-A'),
    ('/biu/telecontrol/control', 'button', '新建CAN连接-B'),
    ('/biu/telecontrol/control', 'button', '发送遥测请求'),
    ('/biu/telecontrol/control', 'text', '目标地址'),
    ('/biu/telecontrol/control', 'text', '定时遥测'),
    ('/xl/telecontrol/control', 'button', '新建CAN连接-A'),
    ('/xl/telecontrol/control', 'button', '新建CAN连接-B'),
    ('/xl/telecontrol/control', 'button', '发送遥测请求'),
    ('/xl/telecontrol/control', 'text', '时间同步 GNSS 有效'),
    ('/xl/telecontrol/control', 'text', '定时遥测'),
    ('/yj216/telecontrol/control', 'button', '新建CAN连接-A'),
    ('/yj216/telecontrol/control', 'button', '新建CAN连接-B'),
    ('/yj216/telecontrol/control', 'button', '发送遥测请求'),
    # 遥控指令页
    ('/biu/telecontrol/command', 'button', '发送指令'),
    ('/biu/telecontrol/command', 'button', '预览组帧'),
    ('/xl/telecontrol/command', 'button', '发送指令'),
    ('/xl/telecontrol/command', 'button', '预览组帧'),
    ('/yj216/telecontrol/command', 'button', '发送指令'),
    ('/yj216/telecontrol/command', 'button', '预览组帧'),
    # 指令序列
    ('/biu/telecontrol/sequence', 'button', '新增'),
    ('/xl/telecontrol/sequence', 'button', '新增'),
    ('/yj216/telecontrol/sequence', 'button', '新增'),
    # 单板开连接
    ('/xl/board/camera', 'button', '新建控制串口连接'),
    ('/xl/board/camera', 'button', '新建图像串口连接'),
    ('/xl/board/camera_v17', 'button', '新建控制串口连接'),
    ('/xl/board/camera_v17', 'button', '新建图像串口连接'),
    ('/xl/board/rkdj', 'button', '新建串口连接'),
    ('/xl/board/zk', 'button', '新建串口连接'),
    ('/xl/board/cpazx', 'button', '新建串口连接'),
    ('/xl/board/dj', 'button', '新建 UDP 连接'),
    ('/yj216/rs422', 'button', '新建串口连接'),
    # 遥测显示入口
    ('/telemetry/live', 'text', '参数名称'),
    ('/telemetry/curve', 'button', '增加曲线'),
    ('/telemetry/archive', 'text', '再选择时间区间查询'),
    ('/telemetry/canHistory', 'text', '解析'),
    ('/telemetry/fileHistory', 'text', '解析'),
    ('/telemetry/fileCurve', 'text', '查询'),
    # 调试·数据模拟（/debug/simulate）
    ('/debug/simulate', 'text', '通用数据发送模拟'),
    ('/debug/simulate', 'text', 'BIU-CAN遥测复合帧数据模拟'),
    ('/debug/simulate', 'text', '帧组装类型'),
    ('/debug/simulate', 'text', '帧解析类型'),
    ('/debug/simulate', 'button', '开始模拟'),
    ('/debug/simulate', 'button', '填入样例'),
    ('/debug/simulate', 'button', '清空'),
    ('/debug/xfer', 'button', '刷新设备'),
    ('/debug/configFile', 'text', '重新载入配置'),
    ('/debug/configFile', 'button', '上传'),
    ('/debug/tmCalc', 'button', '计算'),
    ('/debug/checksum', 'button', '计算'),
    ('/debug/checksum', 'button', '算法选择'),
    ('/debug/numconv', 'text', '数字转 HEX'),
    ('/debug/numconv', 'button', '计算'),
    ('/debug/timeconv', 'text', '协议时间换算'),
    ('/debug/timeconv', 'button', '计算'),
    ('/debug/logDownload', 'text', '显示所有文件'),
]


TM_LIVE_PREFS_KEY = 'payload:telemetry:live:prefs:v1'  # views/payload/telemetry/table/index.vue


async def control_send_hex(page: Page, hex_text: str) -> None:
    """控制页 Hex 透传（仅调试用）。**闭环遥控禁止走此路径**，须用 send_command_order / send_order 点指令卡。"""
    box = page.locator('.control-page textarea[placeholder^="01 02 03"]').first
    await box.fill(hex_text)
    await page.locator('.control-page').get_by_role('button', name='发送遥控指令').first.click()


async def control_tm_request(page: Page) -> None:
    await page.locator('.control-page').get_by_role('button', name='发送遥测请求').first.click()


async def control_timed_tm(page: Page, on: bool) -> None:
    """Toggle 定时遥测. If already in the desired state the target button is disabled — no-op."""
    card = page.locator('.control-page .el-form-item').filter(has_text='定时遥测').first
    await card.wait_for(state='visible', timeout=15000)
    want = '打开' if on else '关闭'
    btn = card.get_by_role('button', name=want)
    await btn.wait_for(state='attached', timeout=10000)
    if await btn.is_disabled():
        return  # already on/off as requested
    await btn.click(timeout=10000)


async def send_order(page: Page, order_id: str) -> str:
    """单板/相机遥控面板（BoardTelecontrolPanel）：过滤 → 预览组帧 → 读 HEX → **点击**「发送指令」。
    禁止改成调用发送 API；HIL 闭环只认 Playwright 点击。
    返回页面显示的 HEX（发送后优先，否则预览）。
    """
    flt = page.locator('.filter-input input, .panel-search input').first
    if await flt.count():
        await flt.fill(order_id)
    card = page.locator('.order-card', has_text=order_id).first
    await card.wait_for(state='visible', timeout=15000)
    preview = card.get_by_role('button', name='预览组帧')
    if await preview.count() and await preview.first.is_enabled():
        await preview.first.click()
        await page.wait_for_timeout(500)
    shown = ''
    desc = card.locator('.order-desc-hex, .order-desc').first
    if await desc.count():
        m = re.search(r'((?:[0-9A-Fa-f]{2}\s+){3,}[0-9A-Fa-f]{2})', await desc.inner_text())
        shown = m.group(1).upper() if m else ''
    btn = card.get_by_role('button', name='发送指令')
    await btn.click()
    await page.wait_for_timeout(400)
    if await desc.count():
        m = re.search(r'((?:[0-9A-Fa-f]{2}\s+){3,}[0-9A-Fa-f]{2})', await desc.inner_text())
        if m:
            shown = m.group(1).upper()
    return shown



async def send_command_order(page: Page, order_id: str) -> str:
    """CAN 指令页（/＜fam＞/telecontrol/command）：树/搜索定位指令卡 → **点击**「发送指令」。
    禁止 API 下发。返回卡片上「指令内容」HEX（若已预览组帧）。
    """
    # 左侧树或搜索
    search = page.locator('.command-page .panel-search input, .command-page .el-input input').first
    if await search.count():
        await search.fill(str(order_id))
        await page.wait_for_timeout(300)
    # 点树节点（若可见）
    tree_node = page.locator('.command-page .el-tree-node', has_text=str(order_id)).first
    if await tree_node.count():
        await tree_node.click()
        await page.wait_for_timeout(200)
    card = page.locator('.command-page .order-card', has_text=str(order_id)).first
    await card.wait_for(state='visible', timeout=15000)
    # 可选：点预览组帧以便读到 HEX
    preview = card.get_by_role('button', name='预览组帧')
    if await preview.count():
        await preview.click()
        await page.wait_for_timeout(400)
    shown = ''
    desc = card.locator('.order-desc-hex, .order-desc').first
    if await desc.count():
        m = re.search(r'((?:[0-9A-Fa-f]{2}\s+){3,}[0-9A-Fa-f]{2})', await desc.inner_text())
        shown = m.group(1).upper() if m else ''
    await card.get_by_role('button', name='发送指令').click()
    return shown




async def read_tm_rows(page: Page, root: str = '.payload-tm-table') -> dict[str, str]:
    """读遥测表格：{编号: 当前值}。"""
    return await page.evaluate(
        """(root) => {
            const out = {};
            document.querySelectorAll(root + ' .el-table__body tr').forEach(tr => {
                const tds = tr.querySelectorAll('td');
                if (tds.length < 3) return;
                const id = tds[0].innerText.trim();
                const v = (tr.querySelector('.value-cell') || tds[2]).innerText.trim();
                if (id) out[id] = v;
            });
            return out;
        }""",
        root,
    )


async def refresh_text(page: Page, root: str = '.payload-tm-table') -> str:
    el = page.locator(f'{root} .tm-ts', has_text='刷新时间').first
    return (await el.inner_text()) if await el.count() else ''


def pick_fields(fields: list[dict], exclude: set[str] = frozenset(), n: int = 6) -> list[dict]:
    """选若干有显示值的字段用于断言。"""
    out = [f for f in fields if f.get('id') not in exclude and str(f.get('show', '')).strip() != '']
    return out[:n]


async def wait_tm_fields(page: Page, expect: list[dict], timeout_s: float, root: str = '.payload-tm-table') -> dict[str, tuple[str, str]]:
    """轮询表格直到 expect 字段的显示值全部一致；返回不一致项 {id: (期望, 实际)}。"""
    import time

    end = time.monotonic() + timeout_s
    bad: dict[str, tuple[str, str]] = {}
    while True:
        rows = await read_tm_rows(page, root)
        bad = {f['id']: (str(f['show']).strip(), rows.get(f['id'], '<无此行>'))
               for f in expect if rows.get(f['id'], '').strip() != str(f['show']).strip()}
        if not bad or time.monotonic() > end:
            return bad
        await page.wait_for_timeout(500)


# ---------------- 遥控页 CAN-A / CAN-B 连接（CanConnectToolbar + CanConnectDialog） ----------------
async def _el_select_current(item) -> str:
    """读 el-select 当前显示值。Element Plus 2.x 里第一个 .el-select__selected-item 是搜索输入框包装层（文字为空），
    选中值显示在 .el-select__placeholder（无值时带 is-transparent，是占位提示）。"""
    ph = item.locator('.el-select__placeholder').first
    if await ph.count():
        cls = await ph.get_attribute('class') or ''
        if 'is-transparent' not in cls:
            return (await ph.inner_text()).strip()
        return ''
    texts = [t.strip() for t in await item.locator('.el-select__selected-item').all_inner_texts()]
    return next((t for t in texts if t), '')


async def _el_select_pick(page: Page, dialog, label: str, pattern: str) -> str:
    """在对话框里某个 el-form-item 的 el-select 中选第一个文本匹配 pattern 的选项，返回选中文本。"""
    item = dialog.locator('.el-form-item', has=page.locator('.el-form-item__label', has_text=label)).first
    sel = item.locator('.el-select').first
    cur = await _el_select_current(item)
    if re.match(pattern, cur):
        return cur
    if 'is-disabled' in (await sel.locator('.el-select__wrapper').first.get_attribute('class') or ''):
        raise AssertionError(f'「{label}」下拉被禁用且当前值 {cur!r} 不符合 {pattern}')
    await sel.click()
    opts = page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
    await opts.first.wait_for(state='visible', timeout=10000)
    texts = [t.strip() for t in await opts.all_inner_texts()]
    for i, tx in enumerate(texts):
        if re.match(pattern, tx):
            if 'is-disabled' in (await opts.nth(i).get_attribute('class') or ''):
                raise AssertionError(f'「{label}」选项 {tx!r} 被禁用（已被其他会话占用或波特率不符）')
            await opts.nth(i).click()
            return tx
    await page.keyboard.press('Escape')
    raise AssertionError(f'「{label}」没有匹配 {pattern} 的选项；现有: {texts}')


async def can_ui_open(page: Page, cable: str, vendor: int, dev_index: int, can_index: int, submit: bool = True) -> dict:
    """点「新建CAN连接-A/B」→ 厂商/设备索引/通道号 → 打开（submit=False 时只选不提交，点「取消」，用于只读核对）。
    返回对话框里选中的文本和确认按钮文字（打开 / 使用）。"""
    ab = cable.upper()
    bar = page.locator('.can-connect-toolbar').first
    await bar.get_by_role('button', name=f'新建CAN连接-{ab}').click()
    dialog = page.locator('.can-connect-dialog:visible').first
    await dialog.wait_for(state='visible', timeout=10000)
    await dialog.get_by_text(f'新建 CAN 连接-{ab}').first.wait_for(timeout=5000)
    # 等厂商列表加载（onOpened 时 refreshVendors）
    await page.wait_for_timeout(800)
    cancel = dialog.locator('.el-form-item').last.get_by_role('button', name='取消')
    try:
        picked = {
            'vendor': await _el_select_pick(page, dialog, '厂商', rf'^\s*{vendor}\s*-\s'),
            'devIndex': await _el_select_pick(page, dialog, '设备索引号', rf'^\s*{dev_index}(\s|$)'),
            'canIndex': await _el_select_pick(page, dialog, '通道号', rf'^\s*{can_index}:CAN{can_index}'),
        }
        confirm = dialog.locator('.el-form-item').last.locator('.el-button--primary').first
        picked['confirm'] = (await confirm.inner_text()).strip()
        picked['confirmEnabled'] = await confirm.is_enabled()
    except Exception:
        if not submit:  # 只读核对：出错也只点「取消」关掉对话框，绝不点确认
            try:
                await page.keyboard.press('Escape')
                await cancel.click(timeout=3000)
            except Exception:
                pass
        raise
    if not submit:
        await cancel.click()
        await dialog.wait_for(state='hidden', timeout=5000)
        return picked
    await confirm.click()
    await bar.get_by_role('button', name=re.compile(rf'关闭CAN-{ab}')).first.wait_for(timeout=15000)
    return picked


async def can_ui_close(page: Page, cable: str) -> bool:
    ab = cable.upper()
    btn = page.locator('.can-connect-toolbar').first.get_by_role('button', name=re.compile(rf'关闭CAN-{ab}'))
    if not await btn.count():
        return False
    await btn.first.click()
    box = page.locator('.el-message-box:visible').first
    await box.wait_for(timeout=5000)
    await box.get_by_role('button', name=re.compile('确定|确认|OK')).first.click()
    await page.locator('.can-connect-toolbar').first.get_by_role('button', name=f'新建CAN连接-{ab}').wait_for(timeout=15000)
    return True



async def _confirm_close_message_box(page: Page) -> None:
    """Element Plus 关闭确认框：串口/UDP 主按钮文案为「关闭」，CAN 为「确定」。"""
    box = page.locator('.el-message-box:visible').first
    await box.wait_for(timeout=5000)
    await box.get_by_role('button', name=re.compile(r'^(关闭|确定|确认|OK)$')).first.click()


async def serial_ui_close(page: Page, port: str | None = None) -> bool:
    """板页网页关串口（优先于 close_serial API）。

    匹配：
    - BoardConnectBar：「关闭串口 · COMx」
    - 相机页：「关闭控制串口 · COMx」/「关闭图像串口 · COMx」
    确认框点「关闭」。API open 后进页会 restore 出关闭按钮；无按钮返回 False，
    由调用方 ensure_hardware_idle（内部 close API）兜底。
    """
    name_pat = re.compile(r'关闭(控制|图像)?串口')
    candidates = page.get_by_role('button', name=name_pat)
    n = await candidates.count()
    btn = None
    port_u = (port or '').upper()
    # 先尽量匹配端口号
    for i in range(n):
        b = candidates.nth(i)
        if not await b.is_visible():
            continue
        text = (await b.inner_text()).strip()
        if port_u and port_u not in text.upper():
            continue
        btn = b
        break
    if btn is None and port_u:
        for i in range(n):
            b = candidates.nth(i)
            if await b.is_visible():
                btn = b
                break
    if btn is None:
        return False
    await btn.click()
    await _confirm_close_message_box(page)
    await page.get_by_role(
        'button', name=re.compile(r'新建(控制|图像)?串口连接')
    ).first.wait_for(timeout=15000)
    return True


async def udp_ui_close(page: Page, local_port: int | None = None) -> bool:
    """板页网页关 UDP（BoardConnectBar「关闭 UDP · host:port」），优先于 close_udp API。

    确认框点「关闭」。无按钮返回 False，由 ensure_hardware_idle 兜底。
    """
    name_pat = re.compile(r'关闭\s*UDP')
    candidates = page.get_by_role('button', name=name_pat)
    n = await candidates.count()
    btn = None
    want = str(local_port) if local_port is not None else ''
    for i in range(n):
        b = candidates.nth(i)
        if not await b.is_visible():
            continue
        text = (await b.inner_text()).strip()
        if want and want not in text:
            continue
        btn = b
        break
    if btn is None and want:
        for i in range(n):
            b = candidates.nth(i)
            if await b.is_visible():
                btn = b
                break
    if btn is None:
        return False
    await btn.click()
    await _confirm_close_message_box(page)
    await page.get_by_role('button', name=re.compile(r'新建\s*UDP\s*连接')).first.wait_for(timeout=15000)
    return True


async def can_select_send(page: Page, cable: str) -> None:
    """工具栏「当前发送」选 CAN-A / CAN-B。"""
    ab = cable.upper()
    rb = page.locator('.can-connect-toolbar .el-radio-button', has_text=f'CAN-{ab}').first
    await rb.wait_for(timeout=10000)
    await rb.click()
    await page.wait_for_timeout(300)


async def home_can_open_passthrough(page: Page, vendor: int, dev_index: int, can_index: int, submit: bool = True) -> dict:
    """Homepage /index: 新建 CAN 连接, pick 透传 assembler, optional open."""
    await page.get_by_role('button', name='新建 CAN 连接').click()
    dialog = page.locator('.can-connect-dialog:visible, .el-dialog:visible').last
    await dialog.wait_for(state='visible', timeout=10000)
    await page.wait_for_timeout(600)
    picked = {
        'vendor': await _el_select_pick(page, dialog, '厂商', rf'^\s*{vendor}\s*-\s'),
        'devIndex': await _el_select_pick(page, dialog, '设备索引号', rf'^\s*{dev_index}(\s|$)'),
        'canIndex': await _el_select_pick(page, dialog, '通道号', rf'^\s*{can_index}:CAN{can_index}'),
    }
    # assembler -> 透传 / passthrough / NONE
    try:
        picked['assembler'] = await _el_select_pick(page, dialog, '组装器', r'透传|passthrough|NONE|协议\s*NONE')
    except Exception:
        picked['assembler'] = 'pick-failed'
    # clear parser if present
    parser_item = dialog.locator('.el-form-item').filter(has_text='解释器')
    if await parser_item.count():
        clear_btn = parser_item.locator('.el-select .el-icon, .el-select__caret, .el-tag__close').first
        # try clearable X
        pass
    if not submit:
        await dialog.get_by_role('button', name='取消').click()
        return picked
    confirm = dialog.locator('.el-button--primary').filter(has_text=re.compile(r'打开|使用')).first
    await confirm.click()
    await page.wait_for_timeout(800)
    return picked


async def home_serial_open_passthrough(page: Page, port: str, baud: int = 115200, submit: bool = True) -> dict:
    """Homepage /index: 新建串口连接 with default 透传."""
    await page.get_by_role('button', name='新建串口连接').click()
    dialog = page.locator('.serial-connect-dialog:visible, .el-dialog:visible').last
    await dialog.wait_for(state='visible', timeout=10000)
    await page.wait_for_timeout(600)
    picked = {'port': await _el_select_pick(page, dialog, '串口号', rf'{re.escape(port)}')}
    try:
        await _el_select_pick(page, dialog, '波特率', rf'^\s*{baud}\s*$')
    except Exception:
        pass
    if not submit:
        await dialog.get_by_role('button', name='取消').click()
        return picked
    confirm = dialog.locator('.el-button--primary').filter(has_text=re.compile(r'打开|使用')).first
    await confirm.click()
    await page.wait_for_timeout(800)
    return picked


async def xfer_select_device_and_send(page: Page, hex_data: str, can_id: str | None = None) -> None:
    """On /debug/xfer: refresh, pick first online device, enable RX if needed, send hex."""
    await page.locator('.xfer-page').wait_for(timeout=15000)
    await page.get_by_role('button', name='刷新设备').click()
    await page.wait_for_timeout(800)
    await page.locator('.xfer-page .el-select').first.click()
    dropdown = page.locator('.el-select-dropdown:visible').last
    await dropdown.wait_for(timeout=10000)
    group = dropdown.locator('.el-select-group__title', has_text='在线')
    if await group.count():
        opts = dropdown.locator('.el-select-group').filter(has_text='在线').locator('.el-select-dropdown__item')
    else:
        opts = dropdown.locator('.el-select-dropdown__item')
    assert await opts.count() > 0, 'no device after refresh'
    await opts.first.click()
    await page.wait_for_timeout(400)
    # enable IO stream via checkbox; wait for backend set-stream API
    recv_item = page.locator('.xfer-page .el-form-item').filter(has_text='数据接收').first
    if await recv_item.count():
        cb = recv_item.locator('.el-checkbox').first
        if await cb.count():
            checked = await cb.evaluate(
                "el => !!(el.classList.contains('is-checked')"
                " || el.getAttribute('aria-checked') === 'true'"
                " || el.querySelector('input')?.checked)"
            )
            if not checked:
                async with page.expect_response(
                    lambda r: r.request.method in ('PUT', 'POST', 'PATCH')
                    and 'stream' in r.url.lower(),
                    timeout=10000,
                ):
                    await cb.click()
                await page.wait_for_timeout(300)
    if can_id is not None and await page.locator('.el-form-item').filter(has_text='帧ID').count():
        await page.locator('.el-form-item').filter(has_text='帧ID').locator('input').first.fill(can_id)
        # Must match 「数据(HEX)」 only — has_text='数据' also hits 「数据接收」 checkbox.
        data_item = page.locator('.el-form-item').filter(has_text='数据(HEX)')
        data = data_item.locator('input:not([type="checkbox"])')
        if await data.count():
            await data.first.fill(hex_data)
            await data.first.blur()
    else:
        # serial/udp RawDataSendPanel defaults to text mode — force HEX before fill
        hex_cb = page.locator('.raw-send-panel .el-checkbox').filter(has_text='HEX').first
        if await hex_cb.count():
            checked = await hex_cb.evaluate(
                """el => !!(el.classList.contains('is-checked')
                    || el.getAttribute('aria-checked') === 'true'
                    || el.querySelector('input')?.checked)"""
            )
            if not checked:
                await hex_cb.click()
                await page.wait_for_timeout(200)
        area = page.locator('.xfer-page textarea, .raw-send-panel textarea').first
        if await area.count():
            await area.fill(hex_data)
    send_btn = page.get_by_role('button', name='发送').first
    await send_btn.click()
    await page.wait_for_timeout(600)

async def camera_open_image_serial(page: Page, port: str) -> dict:
    """Camera board: open image serial dialog and confirm."""
    await page.locator(".camera-page").wait_for(timeout=15000)
    close_btn = page.get_by_role("button", name=re.compile(r"关闭图像串口"))
    if await close_btn.count():
        return {"port": port, "already_open": True}
    btn = page.get_by_role("button", name=re.compile(r"新建图像串口连接"))
    assert await btn.count() > 0, "new image-serial button missing"
    await btn.first.click()
    dialog = page.locator(".serial-connect-dialog:visible, .el-dialog:visible").last
    await dialog.wait_for(state="visible", timeout=10000)
    await page.wait_for_timeout(500)
    picked = {"port": await _el_select_pick(page, dialog, "串口号", rf"{re.escape(port)}")}
    confirm = dialog.locator(".el-button--primary").filter(has_text=re.compile(r"打开|使用")).first
    await confirm.click()
    await page.get_by_role("button", name=re.compile(r"关闭图像串口")).first.wait_for(timeout=20000)
    # wait resolution control enabled (imageConnected)
    deadline = time.time() + 10
    while time.time() < deadline:
        spin = page.locator(".panel-image .el-input-number input").first
        sel = page.locator(".panel-image .image-select-compact.el-select, .panel-image .el-select.image-select-compact").first
        ready = False
        if await spin.count() and not await spin.is_disabled():
            ready = True
        if await sel.count():
            wrap = sel.locator(".el-select__wrapper").first
            cls = (await wrap.get_attribute("class")) or ""
            if "is-disabled" not in cls:
                ready = True
        if ready:
            break
        await page.wait_for_timeout(200)
    await page.wait_for_timeout(300)
    return picked


async def camera_set_resolution(page: Page, side: int, *, board: str = "camera") -> None:
    """Set image resolution after image serial is connected."""
    await page.locator(".camera-page").wait_for(timeout=10000)
    deadline = time.time() + 25
    label = f"{int(side)}×{int(side)}"
    while time.time() < deadline:
        if board == "camera-v17":
            parent = page.locator(".panel-image .image-toolbar .el-input-number, .panel-image .el-input-number").first
            if await parent.count() == 0:
                await page.wait_for_timeout(200)
                continue
            pcls = (await parent.get_attribute("class")) or ""
            spin = parent.locator("input").first
            if "is-disabled" in pcls:
                await page.wait_for_timeout(200)
                continue
            # force fill even if playwright thinks hidden/disabled
            await spin.fill(str(int(side)), force=True)
            await spin.press("Enter")
            await page.wait_for_timeout(200)
            # commit via change event
            await page.evaluate(
                """([side]) => {
                  const root = document.querySelector('.panel-image .el-input-number input');
                  if (!root) return;
                  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
                  setter?.call(root, String(side));
                  root.dispatchEvent(new Event('input', { bubbles: true }));
                  root.dispatchEvent(new Event('change', { bubbles: true }));
                  root.blur();
                }""",
                [int(side)],
            )
            await page.wait_for_timeout(300)
            return
        # v1.6 resolution select (compact class on resolution, not image-index)
        sel = page.locator(".panel-image .image-toolbar .image-select-compact").first
        if await sel.count() == 0:
            sel = page.locator(".panel-image .el-select.image-select-compact").first
        if await sel.count() == 0:
            # first select under toolbar-label 分辨率's form item
            sel = page.locator(".panel-image .image-toolbar .el-form-item .el-select").first
        if await sel.count():
            wrapper = sel.locator(".el-select__wrapper").first
            cls = (await wrapper.get_attribute("class")) or ""
            if "is-disabled" in cls:
                await page.wait_for_timeout(200)
                continue
            await sel.click()
            dropdown = page.locator(".el-select-dropdown:visible").last
            await dropdown.wait_for(timeout=8000)
            opt = dropdown.locator(".el-select-dropdown__item").filter(
                has_text=re.compile(rf"^{re.escape(label)}$")
            )
            if await opt.count() == 0:
                opt = dropdown.locator(".el-select-dropdown__item").filter(has_text=label)
            assert await opt.count() > 0, f"resolution option {side} not found (label={label})"
            await opt.first.click()
            await page.wait_for_timeout(300)
            return
        await page.wait_for_timeout(200)
    raise AssertionError(f"resolution control still disabled (board={board} side={side})")


async def camera_uncheck_auto_capture(page: Page) -> None:
    """Uncheck auto-capture via visible Element Plus checkbox (input is hidden)."""
    label_key = "自动拍照"
    cb = page.locator(".panel-image .el-checkbox").filter(has_text=re.compile(label_key)).first
    if await cb.count() == 0:
        cb = page.locator(".el-checkbox").filter(has_text=re.compile(label_key)).first
    if await cb.count() == 0:
        raise AssertionError("auto-capture checkbox not found")
    for _ in range(3):
        cls = (await cb.get_attribute("class")) or ""
        if "is-checked" not in cls:
            return
        inner = cb.locator(".el-checkbox__inner").first
        if await inner.count():
            await inner.click(force=True)
        else:
            await cb.click(force=True)
        await page.wait_for_timeout(250)
    cls = (await cb.get_attribute("class")) or ""
    assert "is-checked" not in cls, "auto-capture still checked after uncheck"


async def camera_click_refresh_once(page: Page) -> None:
    """Click image-refresh button (single capture)."""
    btn = page.get_by_role("button", name="图片刷新")
    await btn.first.wait_for(state="visible", timeout=10000)
    deadline = time.time() + 20
    while time.time() < deadline:
        if await btn.first.is_enabled():
            await btn.first.click()
            return
        await page.wait_for_timeout(200)
    raise AssertionError("image-refresh button stayed disabled")


async def camera_wait_refresh_success(page: Page, *, timeout_s: float = 100.0) -> None:
    """Wait until page shows refresh-success message (or ElMessage)."""
    ok = "图片刷新成功"
    deadline = time.time() + timeout_s
    loc = page.get_by_text(ok, exact=False)
    while time.time() < deadline:
        if await loc.count():
            return
        # also check status-ish text in panel
        await page.wait_for_timeout(300)
    # non-fatal helper — caller may rely on API instead
    raise AssertionError(f"page did not show {ok!r} within {timeout_s}s")


async def camera_read_displayed_resolution(page: Page) -> str:
    """Read page-parsed 图像分辨率 text from CameraImageView table."""
    table = page.locator(".cam-data-table, .cam-image-view .el-table").first
    await table.wait_for(state="visible", timeout=10000)
    rows = table.locator(".el-table__body tr")
    n = await rows.count()
    label_key = "图像分辨率"
    for i in range(n):
        row = rows.nth(i)
        cells = row.locator("td")
        if await cells.count() < 2:
            continue
        lab = ((await cells.nth(0).inner_text()) or "").strip()
        if label_key in lab:
            return ((await cells.nth(1).inner_text()) or "").strip()
    raise AssertionError(f"{label_key} row not found in cam-data-table (rows={n})")


async def camera_wait_displayed_resolution(page: Page, side: int, *, timeout_s: float = 30.0) -> str:
    """Wait until page shows resolution == side×side after refresh."""
    expect = f"{int(side)}×{int(side)}"
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        try:
            last = await camera_read_displayed_resolution(page)
        except AssertionError:
            last = ""
        norm = (
            last.replace("X", "x")
            .replace("×", "x")
            .replace("*", "x")
            .replace(" ", "")
            .lower()
        )
        if last == expect or norm == f"{side}x{side}":
            return last
        await page.wait_for_timeout(200)
    raise AssertionError(f"page resolution still {last!r}, expect {expect!r}")

async def camera_page_displayed_gray_array(page: Page, side: int):
    """Read page-displayed image pixels (same source drawn on canvas).

    Prefer device-image localStorage cache; fall back to walking Vue vnode tree
    for imageSrc / image-src prop (large 400px may fail cache quota).
    """
    import base64
    import io
    import numpy as np
    from PIL import Image

    js = """() => {
      const key = 'payload:camera:deviceImage:v1';
      const tryParseSrc = (raw) => {
        if (!raw) return null;
        let obj;
        try { obj = JSON.parse(raw); } catch (e) { return null; }
        let v = (obj && typeof obj === 'object' && 'v' in obj) ? obj.v : obj;
        if (typeof v === 'string') {
          try { v = JSON.parse(v); } catch (e) { return null; }
        }
        const src = (v && v.src) || '';
        if (!src.startsWith('data:image')) return null;
        return {src, width: Number(v.width)||0, height: Number(v.height)||0, via:'cache'};
      };
      const cached = tryParseSrc(localStorage.getItem(key)) || tryParseSrc(sessionStorage.getItem(key));
      if (cached) return {ok:true, ...cached};

      // Walk Vue 3 component tree for imageSrc / image-src
      const root = document.querySelector('.camera-page') || document.querySelector('#app') || document.body;
      const seen = new Set();
      const queue = [];
      const push = (c) => { if (c && !seen.has(c)) { seen.add(c); queue.push(c); } };
      // element -> component
      const walkEl = (el) => {
        if (!el) return;
        let c = el.__vueParentComponent || el._vnode?.component;
        push(c);
        // also try __vue__
        if (el.__vue__) push(el.__vue__.$ || el.__vue__);
      };
      walkEl(root);
      root.querySelectorAll('*').forEach(walkEl);
      let found = null;
      while (queue.length) {
        const c = queue.shift();
        if (!c) continue;
        const props = c.props || {};
        const setup = c.setupState || {};
        const ctx = c.ctx || {};
        const data = c.data || {};
        const candidates = [
          props.imageSrc, props['image-src'], props.image_src,
          setup.imageSrc, setup.imageSrc?.value,
          ctx.imageSrc, ctx.imageSrc?.value,
          data.imageSrc,
        ];
        for (const s of candidates) {
          const val = (s && typeof s === 'object' && 'value' in s) ? s.value : s;
          if (typeof val === 'string' && val.startsWith('data:image')) {
            found = val;
            break;
          }
        }
        if (found) break;
        if (c.subTree) {
          const st = c.subTree;
          if (st.component) push(st.component);
          const ch = st.children;
          if (Array.isArray(ch)) ch.forEach(n => n?.component && push(n.component));
        }
        if (c.children) {
          const ch = c.children;
          if (Array.isArray(ch)) ch.forEach(n => push(n.component || n));
        }
      }
      if (found) return {ok:true, src: found, width:0, height:0, via:'vue'};
      return {ok:false, err:'no imageSrc', seen: seen.size};
    }"""
    result = await page.evaluate(js)
    if not result or not result.get("ok"):
        raise AssertionError(f"page displayed image not found: {result}")
    src = result["src"]
    if "," not in src:
        raise AssertionError(f"unexpected image src format: {src[:64]!r}")
    b64 = src.split(",", 1)[1]
    raw = base64.b64decode(b64)
    im = Image.open(io.BytesIO(raw))
    if im.mode != "L":
        im = im.convert("L")
    arr = np.asarray(im, dtype=np.uint8)
    assert arr.shape == (int(side), int(side)), (
        f"page displayed shape {arr.shape} != {(side, side)}; via={result.get('via')} "
        f"cache wh=({result.get('width')},{result.get('height')})"
    )
    return arr, {k: result.get(k) for k in ("via", "width", "height")}


async def camera_canvas_gray_array(page: Page, side: int):
    """Backward-compatible alias → page displayed image pixels."""
    return await camera_page_displayed_gray_array(page, side)


# ---------------- 遥测·历史文件数据 / 历史文件曲线 ----------------

async def file_toolbar_select_tm(page: Page, needle: str, *, root: str = '') -> str:
    """顶栏遥测表下拉：按 key（如 BIU:FF）或展示文案（BIU-FF）精确匹配。

    分组顺序为 XL → BIU → YJ216，禁止用裸 localKey（如 FF）做子串匹配，
    否则会误选 XL-FF。优先输入过滤词再按前缀点选。
    """
    scope = page.locator(root) if root else page
    item = scope.locator('.el-form-item').filter(has_text='遥测表').first
    await item.locator('.el-select').click()
    dropdown = page.locator('.el-select-dropdown:visible').last
    await dropdown.wait_for(state='visible', timeout=15000)

    key = (needle or '').strip()
    forms: list[str] = []
    for n in (key, key.replace(':', '-'), key.replace('-', ':')):
        if n and n not in forms:
            forms.append(n)

    def _lab_ok(lab: str) -> bool:
        s = (lab or "").strip()
        if not s:
            return False
        for f in forms:
            # BIU-FF:… / XL-RKDJ:… — not bare FF; not D8 inside D8V17
            pat = re.escape(f) + r'(?:\b|[:\s:]|$)'
            if re.match(pat, s, re.I):
                return True
            # Labels often prefix family: XL-RKDJ when needle is RKDJ
            if re.match(r'(?:XL|BIU|YJ216)[\-:]' + pat, s, re.I):
                return True
        return False

    async def _pick(opts) -> tuple:
        chosen_i = None
        text = ''
        count = await opts.count()
        for i in range(count):
            lab = ((await opts.nth(i).inner_text()) or '').strip()
            if _lab_ok(lab):
                return opts.nth(i), lab
        return None, ''

    inp = item.locator('.el-select input').first
    # Filter first so XL group cannot steal BIU:FF
    if await inp.count():
        await inp.fill(key.replace(':', ' ').replace('-', ' '))
        await page.wait_for_timeout(350)

    opts = dropdown.locator('.el-select-dropdown__item')
    await opts.first.wait_for(state='visible', timeout=15000)
    chosen, text_out = await _pick(opts)

    if chosen is None and await inp.count():
        await inp.fill('')
        await page.wait_for_timeout(300)
        opts = dropdown.locator('.el-select-dropdown__item')
        chosen, text_out = await _pick(opts)

    if chosen is None:
        raise AssertionError(
            f'遥测表选项未找到: {needle!r} (tried {forms})'
        )
    await chosen.click()
    await page.wait_for_timeout(300)
    return text_out
async def file_browser_upload_and_pick(page: Page, local_path: str | Path, *, timeout_s: float = 120.0) -> str:
    """选择文件 → 上传 → 进入「上传文件」→ 选刚传的文件 → 确认。

    返回路径输入框最终显示文本。``.txt`` 会勾选「显示所有文件」。
    """
    from pathlib import Path as _P

    path = _P(local_path)
    assert path.is_file(), f'样本不存在: {path}'
    name = path.name
    await page.get_by_role('button', name='选择文件').click()
    dialog = page.locator('.el-dialog').filter(has_text='选择文件').last
    await dialog.wait_for(state='visible', timeout=15000)

    async with page.expect_file_chooser(timeout=15000) as fc_info:
        await dialog.get_by_role('button', name='上传').click()
    chooser = await fc_info.value
    await chooser.set_files(str(path))

    # Same-name confirm: Cancel / Overwrite -> click Overwrite
    box = page.locator('.el-message-box:visible').first
    try:
        await box.wait_for(state='visible', timeout=5000)
        body = await box.inner_text()
        if '同名' in body or '继续上传' in body or '覆盖' in body:
            btn = box.get_by_role('button', name=re.compile(r'^覆盖$'))
            if await btn.count():
                await btn.first.click()
            else:
                await box.get_by_role('button', name=re.compile(r'覆盖|继续|确定|确认|OK')).first.click()
            await page.wait_for_timeout(300)
    except Exception:
        pass

    up = page.locator('.el-dialog').filter(has_text='上传文件').last
    await up.wait_for(state='visible', timeout=15000)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        body = await up.inner_text()
        if '上传完成' in body or '100%' in body:
            break
        bar = up.locator('.el-progress-bar__inner')
        if await bar.count():
            style = await bar.first.get_attribute('style') or ''
            if '100%' in style:
                break
        await page.wait_for_timeout(400)
    else:
        raise AssertionError('上传超时')
    # Prefer footer Close; header X also matches role=button name=关闭
    footer = up.locator('.el-dialog__footer')
    close_btn = footer.get_by_role('button', name=re.compile(r'^关闭$'))
    if await close_btn.count():
        await close_btn.click()
    else:
        alt = up.get_by_role('button', name='关闭')
        if await alt.count():
            await alt.last.click()
    await page.wait_for_timeout(300)

    crumb = dialog.locator('.crumb')
    crumb_text = (await crumb.inner_text()) if await crumb.count() else ''
    if '上传文件' not in crumb_text:
        for _ in range(6):
            up_btn = dialog.get_by_role('button', name='上级')
            if await up_btn.count() and await up_btn.is_enabled():
                await up_btn.click()
                await page.wait_for_timeout(250)
            else:
                break
        home_row = dialog.locator('.el-table__body tr').filter(has_text='/上传文件').first
        await home_row.wait_for(state='visible', timeout=10000)
        await home_row.dblclick()
        await page.wait_for_timeout(500)

    if path.suffix.lower() == '.txt':
        cb = dialog.locator('.el-checkbox').filter(has_text='显示所有文件')
        if await cb.count():
            inp = cb.locator('input[type="checkbox"]')
            if await inp.count() and not await inp.is_checked():
                await cb.click()
                await page.wait_for_timeout(400)

    refresh = dialog.locator('.browser-footer-left .el-button').first
    if await refresh.count():
        await refresh.click()
        await page.wait_for_timeout(500)

    row = dialog.locator('.el-table__body tr').filter(has_text=name).first
    await row.wait_for(state='visible', timeout=20000)
    await row.click()
    await page.wait_for_timeout(200)
    await dialog.get_by_role('button', name='确认').click()
    await page.wait_for_timeout(400)

    path_input = page.locator('.file-toolbar .el-input input').first
    shown = ''
    if await path_input.count():
        shown = (await path_input.input_value()) or ''
    assert name in shown or shown, f'上传选择后路径未更新: {shown!r}'
    return shown


async def file_click_parse(page: Page) -> None:
    await page.get_by_role('button', name='解析', exact=True).click()


async def file_wait_parsed(page: Page, *, timeout_s: float = 90.0, min_frames: int = 1) -> int:
    """等回放条/曲线块滑块出现有效帧数。"""
    deadline = time.time() + timeout_s
    last = 0
    while time.time() < deadline:
        edges = page.locator('.replay-bar .slider-edge')
        if await edges.count() >= 2:
            txt = (await edges.nth(1).inner_text()).strip()
            if txt.isdigit():
                last = int(txt)
                if last >= min_frames:
                    return last
        total = page.locator('.range-slider .slider-edge-total')
        if await total.count():
            t = (await total.inner_text()).strip()
            if t.isdigit() and int(t) > 0:
                return int(t)
        nxt = page.get_by_role('button', name='下一页')
        if await nxt.count() and await nxt.first.is_enabled():
            return max(last, 2)
        await page.wait_for_timeout(500)
    raise AssertionError(f'解析超时，frameCount~{last}')


async def file_open_sessions_and_snapshot(page: Page) -> list[dict]:
    """打开「解析进程」对话框，返回表格行文本快照。"""
    await page.get_by_role('button', name='解析进程').click()
    dlg = page.locator('.el-dialog').filter(has_text='解析进程').last
    await dlg.wait_for(state='visible', timeout=15000)
    await page.wait_for_timeout(400)
    rows = dlg.locator('.el-table__body tr')
    out: list[dict] = []
    for i in range(await rows.count()):
        cells = rows.nth(i).locator('td')
        texts = [(await cells.nth(j).inner_text()).strip() for j in range(await cells.count())]
        out.append({'cells': texts, 'text': ' | '.join(texts)})
    return out


async def file_close_sessions_dialog(page: Page) -> None:
    dlg = page.locator('.el-dialog').filter(has_text='解析进程').last
    if await dlg.count() and await dlg.is_visible():
        await page.keyboard.press('Escape')
        await page.wait_for_timeout(300)


async def file_assert_process_recycled(page: Page, *, file_name: str, timeout_s: float = 90.0) -> None:
    """解析完成后确认进程已退出；必要时点「关闭进程」再回查。"""
    deadline = time.time() + timeout_s
    names = {file_name, Path(file_name).name}
    stem = Path(file_name).stem
    if stem:
        names.add(stem)
        names.add(stem.split("_")[0])
    while time.time() < deadline:
        rows = await file_open_sessions_and_snapshot(page)
        hit = [r for r in rows if any(n and n in r["text"] for n in names)]
        if not hit:
            await file_close_sessions_dialog(page)
            return
        text = hit[0]["text"]
        if any(tok in text for tok in ("已退出", "已结束", "缓存", "无进程")):
            await file_close_sessions_dialog(page)
            return
        if any(tok in text for tok in ("解析中", "扫描中", "进行中")):
            await file_close_sessions_dialog(page)
            await page.wait_for_timeout(1000)
            continue
        dlg = page.locator(".el-dialog").filter(has_text="解析进程").last
        row = dlg.locator(".el-table__body tr").filter(has_text=re.compile("|".join(map(re.escape, [n for n in names if n])))).first
        close_proc = row.get_by_role("button", name=re.compile(r"关闭进程|结束进程|关闭"))
        if await close_proc.count() and await close_proc.first.is_enabled():
            await close_proc.first.click()
            await page.wait_for_timeout(800)
            await file_close_sessions_dialog(page)
            continue
        await file_close_sessions_dialog(page)
        await page.wait_for_timeout(800)
    raise AssertionError(f"进程未回收: {file_name}")


async def file_history_exercise_frames(page: Page, *, settle_ms: int = 2500) -> dict:
    """选帧：上一页/下一页/滑块/输入回车/自动播放，并等遥测显示。

    返回实际点到的动作。调用方应断言 next 或 slider 为真，避免只有 1 帧时静默通过。
    """
    covered = {"next": False, "prev": False, "slider": False, "jump": False, "play": False}
    bar = page.locator('.replay-bar')
    await bar.wait_for(state='visible', timeout=15000)
    table = page.locator('.payload-tm-table, .table-wrap .el-table').first

    async def _rows_ok() -> bool:
        if not await table.count():
            return False
        return (await table.locator('tbody tr').count()) > 0

    nxt = bar.get_by_role('button', name='下一页')
    if await nxt.count() and await nxt.is_enabled():
        await nxt.click()
        await page.wait_for_timeout(settle_ms)
        assert await _rows_ok(), '下一页后遥测表无行'
        covered["next"] = True

    prev = bar.get_by_role('button', name='上一页')
    if await prev.count() and await prev.is_enabled():
        await prev.click()
        await page.wait_for_timeout(settle_ms)
        assert await _rows_ok(), '上一页后遥测表无行'
        covered["prev"] = True

    slider = bar.locator('.el-slider')
    if await slider.count():
        box = await slider.bounding_box()
        if box:
            await page.mouse.click(box['x'] + box['width'] * 0.6, box['y'] + box['height'] / 2)
            await page.wait_for_timeout(settle_ms)
            assert await _rows_ok(), '滑块后遥测表无行'
            covered["slider"] = True

    num = bar.locator('.replay-pager .el-input-number input, .replay-pager input').first
    # el-input-number is often aria-disabled (display-only); skip click/fill when disabled
    if await num.count() and await num.is_enabled():
        await num.click()
        await num.fill('1')
        await num.press('Enter')
        await page.wait_for_timeout(settle_ms)
        assert await _rows_ok(), '跳转帧1后遥测表无行'
        covered["jump"] = True
    elif await num.count():
        # Jump back to frame 1 via slider left edge instead
        slider = bar.locator('.el-slider')
        if await slider.count():
            box = await slider.bounding_box()
            if box:
                await page.mouse.click(box['x'] + 4, box['y'] + box['height'] / 2)
                await page.wait_for_timeout(settle_ms)
                assert await _rows_ok(), '滑块回帧1后遥测表无行'
                covered["slider"] = True

    play = bar.get_by_role('button', name=re.compile(r'自动播放|停止'))
    if await play.count() and await play.first.is_enabled():
        label = (await play.first.inner_text()).strip()
        if '自动播放' in label:
            await play.first.click()
            await page.wait_for_timeout(max(settle_ms, 3000))
            stop = bar.get_by_role('button', name='停止')
            if await stop.count() and await stop.is_enabled():
                await stop.click()
            await page.wait_for_timeout(500)
            assert await _rows_ok(), '自动播放后遥测表无行'
            covered["play"] = True
    return covered


async def file_curve_slider_edges(page: Page) -> tuple[str, int]:
    """历史文件曲线区间滑块：(范围文案如 ``0~1``, 块序号上限 sliderMax)。"""
    rng = page.locator('.range-slider .slider-edge-range').first
    total = page.locator('.range-slider .slider-edge-total').first
    await total.wait_for(state='visible', timeout=15000)
    label = ((await rng.inner_text()) if await rng.count() else '').strip()
    raw = ((await total.inner_text()) or '').strip()
    assert raw.isdigit(), f'曲线块序号上限不是整数: {raw!r} label={label!r}'
    return label, int(raw)


def _curve_points_from_payload(body) -> int:
    if not isinstance(body, dict):
        return 0
    payload = body.get("data", body)
    rows = []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        if payload.get("error") or payload.get("sessionGone"):
            return 0
        rows = payload.get("items") or []
        if not isinstance(rows, list):
            rows = []
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        cps = row.get("chunkPoints") or {}
        if isinstance(cps, dict):
            for pts in cps.values():
                if isinstance(pts, list):
                    total += len(pts)
        pts = row.get("points")
        if isinstance(pts, list):
            total += len(pts)
    return total


async def file_curve_add_fields(page: Page, count: int = 3) -> list[str]:
    """增加 2~5 条曲线。"""
    added: list[str] = []
    count = max(2, min(5, int(count)))
    for i in range(count + 4):
        if len(added) >= count:
            break
        item = page.locator('.el-form-item').filter(has_text='遥测量').first
        await item.locator('.el-select').click()
        dd = page.locator('.el-select-dropdown:visible').last
        await dd.wait_for(state='visible', timeout=10000)
        opts = dd.locator('.el-select-dropdown__item')
        n = await opts.count()
        if n == 0:
            await page.keyboard.press('Escape')
            break
        opt = opts.nth(min(i, n - 1))
        label = (await opt.inner_text()).strip()
        await opt.click()
        await page.wait_for_timeout(200)
        btn = page.get_by_role('button', name=re.compile(r'增加曲线|删除曲线'))
        await btn.first.wait_for(state='visible', timeout=10000)
        text = (await btn.first.inner_text()).strip()
        if '增加曲线' in text:
            await btn.first.click()
            await page.wait_for_timeout(600)
            added.append(label)
    assert len(added) >= 2, f'曲线条数不足: {added}'
    return added


async def file_curve_query_and_tools(page: Page, *, query_wait_s: float = 20.0) -> None:
    """滑块 → 查询（可等 10s+）→ 放大/缩小/滚轮/自适应/截取/重置。"""
    slider = page.locator('.range-slider .el-slider, .toolbar-options .el-slider').first
    if await slider.count():
        box = await slider.bounding_box()
        if box and box['width'] > 10:
            await page.mouse.click(box['x'] + box['width'] * 0.4, box['y'] + box['height'] / 2)
            await page.wait_for_timeout(300)

    query = page.get_by_role('button', name='查询', exact=True)
    await query.click()
    await page.wait_for_timeout(1000)
    deadline = time.time() + query_wait_s
    while time.time() < deadline:
        cls = await query.get_attribute('class') or ''
        if 'is-loading' in cls or not await query.is_enabled():
            await page.wait_for_timeout(400)
            continue
        break
    await page.wait_for_timeout(1500)

    for title in ('放大', '缩小', 'Y坐标轴自适应'):
        btn = page.locator(f'button[title="{title}"]')
        if await btn.count():
            await btn.first.click()
            await page.wait_for_timeout(200)

    wheels = page.locator('button.y-ctrl-btn.y-ctrl-wheel')
    n_w = await wheels.count()
    for i in range(min(n_w, 2)):
        await wheels.nth(i).click()
        await page.wait_for_timeout(100)
    chart = page.locator('.chart-wrap canvas, .chart-wrap').first
    if await chart.count():
        box = await chart.bounding_box()
        if box:
            await page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            await page.mouse.wheel(0, -200)
            await page.wait_for_timeout(200)

    crop = page.locator('.icon-tool-btn').first
    if await crop.count() and await crop.is_enabled():
        await crop.click()
        await page.wait_for_timeout(200)
        await crop.click()

    reset = page.get_by_role('button', name='重置曲线')
    if await reset.count() and await reset.is_enabled():
        await reset.click()
        await page.wait_for_timeout(400)



async def file_curve_add_field(page: Page, needle: str) -> tuple[str, int]:
    """Select one telemetry field by id/name substring and click 增加曲线 once."""
    needle = (needle or "").strip()
    assert needle, "field needle required"
    item = page.locator(".el-form-item").filter(has_text="遥测量").first
    await item.locator(".el-select").click()
    dd = page.locator(".el-select-dropdown:visible").last
    await dd.wait_for(state="visible", timeout=10000)
    opts = dd.locator(".el-select-dropdown__item")
    n = await opts.count()
    assert n > 0, "遥测量下拉为空"
    chosen = ""
    for i in range(n):
        label = (await opts.nth(i).inner_text()).strip()
        if needle in label:
            await opts.nth(i).click()
            chosen = label
            break
    else:
        await page.keyboard.press("Escape")
        raise AssertionError(f"未找到遥测量含 {needle!r}（共 {n} 项）")
    await page.wait_for_timeout(200)
    btn = page.get_by_role("button", name=re.compile(r"增加曲线|删除曲线"))
    await btn.first.wait_for(state="visible", timeout=10000)
    text_btn = (await btn.first.inner_text()).strip()
    pts = 0
    if "增加曲线" in text_btn:
        responses: list = []

        def _on_response(resp) -> None:
            try:
                if "/payload/telemetry/file/curve" in (resp.url or "") and resp.status == 200:
                    responses.append(resp)
            except Exception:
                pass

        page.on("response", _on_response)
        try:
            await btn.first.click()
            deadline = time.time() + 90.0
            while time.time() < deadline:
                cls = await btn.first.get_attribute("class") or ""
                if "is-loading" in cls:
                    await page.wait_for_timeout(400)
                    continue
                break
            await page.wait_for_timeout(800)
            pts = 0
            while responses:
                resp = responses.pop(0)
                try:
                    body = await resp.json()
                    pts = max(pts, _curve_points_from_payload(body))
                except Exception:
                    pass
            if pts:
                print(f"[HIL] add_curve API points={pts}", flush=True)
        finally:
            try:
                page.remove_listener("response", _on_response)
            except Exception:
                pass
    elif "删除曲线" in text_btn:
        # already on chart — OK for idempotent re-run
        pass
    else:
        raise AssertionError(f"曲线按钮文案异常: {text_btn!r}")
    return chosen, int(locals().get("pts") or 0)


async def file_curve_click_query(page: Page, *, query_wait_s: float = 90.0) -> int:
    """Click 查询; harvest /payload/telemetry/file/curve JSON for point counts."""
    responses: list = []

    def _on_response(resp) -> None:
        try:
            if "/payload/telemetry/file/curve" in (resp.url or "") and resp.status == 200:
                responses.append(resp)
        except Exception:
            pass

    page.on("response", _on_response)
    query = page.get_by_role("button", name="查询", exact=True)
    total = 0
    errors: list[str] = []
    try:
        await query.click()
        deadline = time.time() + query_wait_s
        idle_rounds = 0
        while time.time() < deadline:
            # drain newly captured responses
            while responses:
                resp = responses.pop(0)
                try:
                    body = await resp.json()
                except Exception as exc:  # noqa: BLE001
                    errors.append(str(exc))
                    continue
                total = max(total, _curve_points_from_payload(body))
                payload = body.get("data") if isinstance(body, dict) else None
                if isinstance(payload, dict) and payload.get("error"):
                    errors.append(str(payload.get("error")))
            cls = await query.get_attribute("class") or ""
            loading = ("is-loading" in cls) or (not await query.is_enabled())
            if loading:
                idle_rounds = 0
                await page.wait_for_timeout(400)
                continue
            idle_rounds += 1
            # after button idle, give chunk polls a moment then stop
            await page.wait_for_timeout(500)
            if idle_rounds >= 3 and not responses:
                break
        else:
            raise AssertionError("查询按钮仍在 loading")
        # final drain
        while responses:
            resp = responses.pop(0)
            try:
                body = await resp.json()
                total = max(total, _curve_points_from_payload(body))
            except Exception:
                pass
    finally:
        try:
            page.remove_listener("response", _on_response)
        except Exception:
            pass
    if total < 1 and errors:
        raise AssertionError(f"曲线查询错误: {errors[:3]}")
    return int(total)



async def file_curve_point_count(page: Page) -> int:
    """Best-effort live point count via Vue walk or echarts series."""
    js = r"""() => {
      const root = document.querySelector('.curve-page') || document.querySelector('#app');
      if (!root) return {ok:false, err:'no root'};
      const starts = [];
      if (root.__vueParentComponent) starts.push(root.__vueParentComponent);
      const app = document.querySelector('#app');
      if (app && app.__vue_app__ && app.__vue_app__._instance) starts.push(app.__vue_app__._instance);
      const q = starts.slice();
      const seen = new Set();
      while (q.length) {
        const c = q.shift();
        if (!c || seen.has(c)) continue;
        seen.add(c);
        const raw = c.setupState || c.ctx || {};
        const list = raw.curves;
        const arr = (list && typeof list === 'object' && 'value' in list) ? list.value : list;
        if (Array.isArray(arr) && arr.length && arr[0] && ('points' in arr[0] || 'field' in arr[0] || 'chunkMap' in arr[0])) {
          let total = 0;
          for (const it of arr) {
            if (Array.isArray(it.points)) total += it.points.length;
            else if (it.chunkMap && typeof it.chunkMap === 'object') {
              for (const v of Object.values(it.chunkMap)) if (Array.isArray(v)) total += v.length;
            }
          }
          return {ok:true, curves: arr.length, points: total, via:'vue'};
        }
        if (c.subTree) {
          const st = c.subTree;
          if (st.component) q.push(st.component);
          const ch = st.children;
          if (Array.isArray(ch)) ch.forEach(n => n?.component && q.push(n.component));
        }
      }
      const canvases = document.querySelectorAll('.chart-wrap canvas');
      for (const cv of canvases) {
        const get = window.echarts && window.echarts.getInstanceByDom;
        if (!get) break;
        const inst = get(cv.parentElement) || get(cv);
        if (!inst || !inst.getOption) continue;
        const opt = inst.getOption();
        const series = (opt && opt.series) || [];
        let total = 0;
        for (const s of series) {
          const d = s && s.data;
          if (Array.isArray(d)) total += d.length;
        }
        if (total > 0) return {ok:true, curves: series.length, points: total, via:'echarts'};
      }
      const msgs = Array.from(document.querySelectorAll('.el-message__content')).map(e => (e.textContent||'').trim());
      return {ok:false, err:'curves not found', seen: seen.size, msgs};
    }"""
    result = await page.evaluate(js)
    if not result or not result.get("ok"):
        raise AssertionError(f"无法读取曲线点数: {result}")
    return int(result.get("points") or 0)


async def file_curve_wait_points(page: Page, *, min_points: int = 1, timeout_s: float = 90.0, seed_points: int = 0) -> int:
    """Accept seed_points from query API; else poll Vue/echarts / empty toasts."""
    if int(seed_points or 0) >= min_points:
        return int(seed_points)
    deadline = time.time() + timeout_s
    last = int(seed_points or 0)
    last_err = ""
    while time.time() < deadline:
        try:
            last = max(last, await file_curve_point_count(page))
            if last >= min_points:
                return last
        except AssertionError as exc:
            last_err = str(exc)
        nodes = page.locator(".el-message__content")
        for i in range(await nodes.count()):
            t = (await nodes.nth(i).inner_text()).strip()
            if "暂无数据" in t or "该区间暂无" in t:
                raise AssertionError(f"查询结果为空: {t}")
        await page.wait_for_timeout(500)
    raise AssertionError(f"查询后曲线无点（points={last}）{('；' + last_err) if last_err else ''}")


async def file_curve_exercise_tools(page: Page) -> dict:
    """Crop(截取) toggle, zoom/fit, wheel toggles, optional export — after curve is visible."""
    covered: dict[str, bool] = {
        "zoom_in": False,
        "zoom_out": False,
        "y_fit": False,
        "wheel_y": False,
        "wheel_x": False,
        "crop": False,
        "export": False,
        "chart_wheel": False,
    }
    for title, key in (("放大", "zoom_in"), ("缩小", "zoom_out"), ("Y坐标轴自适应", "y_fit")):
        btn = page.locator(f'button[title="{title}"]')
        if await btn.count():
            await btn.first.click()
            await page.wait_for_timeout(200)
            covered[key] = True

    wheels = page.locator("button.y-ctrl-btn.y-ctrl-wheel")
    n_w = await wheels.count()
    if n_w >= 1:
        await wheels.nth(0).click()
        await page.wait_for_timeout(100)
        covered["wheel_y"] = True
    if n_w >= 2:
        await wheels.nth(1).click()
        await page.wait_for_timeout(100)
        covered["wheel_x"] = True

    chart = page.locator(".chart-wrap canvas, .chart-wrap").first
    if await chart.count():
        box = await chart.bounding_box()
        if box:
            await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            await page.mouse.wheel(0, -200)
            await page.wait_for_timeout(200)
            covered["chart_wheel"] = True

    # 截取/裁切：toolbar Crop icon
    crop = page.locator(".icon-tool-group .icon-tool-btn").first
    if await crop.count() and await crop.is_enabled():
        await crop.click()
        await page.wait_for_timeout(250)
        # drag a small crop window on chart if crop mode on
        if await chart.count():
            box = await chart.bounding_box()
            if box and box["width"] > 80:
                x0 = box["x"] + box["width"] * 0.3
                y0 = box["y"] + box["height"] * 0.3
                x1 = box["x"] + box["width"] * 0.6
                y1 = box["y"] + box["height"] * 0.7
                await page.mouse.move(x0, y0)
                await page.mouse.down()
                await page.mouse.move(x1, y1, steps=8)
                await page.mouse.up()
                await page.wait_for_timeout(300)
        await crop.click()  # leave crop mode
        await page.wait_for_timeout(200)
        covered["crop"] = True

    export_btn = page.locator(".icon-tool-group .icon-tool-btn").nth(1)
    if await export_btn.count() and await export_btn.is_enabled():
        # click export (may download); do not fail if browser blocks download
        try:
            async with page.expect_download(timeout=5000):
                await export_btn.click()
            covered["export"] = True
        except Exception:
            await export_btn.click()
            await page.wait_for_timeout(300)
            covered["export"] = True
    return covered


async def file_curve_move_range_slider(page: Page, *, ratio: float = 0.55) -> None:
    """Click range slider track at a ratio (0~1) to change query window."""
    slider = page.locator(".range-slider .el-slider, .toolbar-options .el-slider").first
    assert await slider.count(), "找不到区间滑块"
    box = await slider.bounding_box()
    assert box and box["width"] > 10, "滑块不可见"
    r = max(0.05, min(0.95, float(ratio)))
    await page.mouse.click(box["x"] + box["width"] * r, box["y"] + box["height"] / 2)
    await page.wait_for_timeout(400)


async def file_curve_reset(page: Page) -> None:
    reset = page.get_by_role("button", name="重置曲线")
    assert await reset.count(), "找不到重置曲线"
    assert await reset.is_enabled(), "重置曲线不可用"
    await reset.click()
    await page.wait_for_timeout(400)


# ---------------- 2026-10 产品改动：历史 / last-send / 复用辅助 ----------------

async def control_timed_sync_broadcast(page: Page, on: bool) -> None:
    """Toggle 定时同步广播. Already-in-state → no-op."""
    card = page.locator('.control-page .el-form-item').filter(has_text='定时同步广播').first
    await card.wait_for(state='visible', timeout=15000)
    want = '打开' if on else '关闭'
    btn = card.get_by_role('button', name=want)
    await btn.wait_for(state='attached', timeout=10000)
    if await btn.is_disabled():
        return
    await btn.click(timeout=10000)


async def control_read_last_send_hints(page: Page) -> dict[str, str]:
    """Read 「最近发送/最近同步」hint-inline texts on control page."""
    out = {'timed_tm': '', 'time_sync': ''}
    items = page.locator('.control-page .el-form-item')
    for i in range(await items.count()):
        item = items.nth(i)
        label = ''
        lab = item.locator('.el-form-item__label').first
        if await lab.count():
            label = (await lab.inner_text()).strip()
        hint = item.locator('.hint-inline').first
        if not await hint.count():
            continue
        text = (await hint.inner_text()).strip()
        if '定时遥测' in label or text.startswith('最近发送'):
            out['timed_tm'] = text
        if '定时同步广播' in label or text.startswith('最近同步'):
            out['time_sync'] = text
    return out


async def history_panel_items(page: Page, *, timeout_ms: int = 12000) -> list[dict]:
    """Read embedded/drawer 遥控历史 rows: hex / name / can_frames lines."""
    import time as _t
    root = page.locator('.send-history-embed, .send-history-drawer').first
    await root.wait_for(state='visible', timeout=timeout_ms)
    items = root.locator('.history-item')
    deadline = _t.monotonic() + timeout_ms / 1000
    while _t.monotonic() < deadline:
        if await items.count():
            break
        if await root.locator('.history-empty').count():
            break
        await page.wait_for_timeout(400)
    rows: list[dict] = []
    for i in range(await items.count()):
        it = items.nth(i)
        name = ''
        if await it.locator('.history-name').count():
            name = (await it.locator('.history-name').first.inner_text()).strip()
        hex_txt = ''
        if await it.locator('.history-hex').count():
            hex_txt = (await it.locator('.history-hex').first.inner_text()).strip()
        frames = []
        for fi in range(await it.locator('.history-can-frame').count()):
            frames.append((await it.locator('.history-can-frame').nth(fi).inner_text()).strip())
        rows.append({'name': name, 'hex': hex_txt, 'can_frames': frames})
    return rows


async def history_wait_can_frame(
    page: Page,
    *,
    id_hex: str,
    timeout_s: float = 12.0,
    min_frames: int | None = None,
) -> dict:
    """Wait until a history row shows can_frames containing id_hex (8-digit)."""
    import time as _t
    needle = id_hex.upper().replace('0X', '').zfill(8)
    deadline = _t.monotonic() + timeout_s
    last: list[dict] = []
    while _t.monotonic() < deadline:
        last = await history_panel_items(page, timeout_ms=2000)
        for row in last:
            frames = row.get('can_frames') or []
            if not frames:
                continue
            if min_frames is not None and len(frames) != min_frames:
                continue
            if any(needle in fr.upper() for fr in frames):
                return row
        await page.wait_for_timeout(400)
    raise AssertionError(
        f'历史未出现 can_frames 含 {needle}（min_frames={min_frames}）；最近={last[:2]!r}'
    )


async def history_name_tooltip(page: Page, row_index: int = 0) -> str:
    """Read tooltip / full name for a history row."""
    root = page.locator('.send-history-embed, .send-history-drawer').first
    name = root.locator('.history-item').nth(row_index).locator('.history-name').first
    await name.wait_for(state='visible', timeout=10000)
    await name.hover()
    await page.wait_for_timeout(400)
    tip = page.locator('.el-popper.is-pure, .el-tooltip__popper, [role="tooltip"]').last
    if await tip.count() and await tip.is_visible():
        return (await tip.inner_text()).strip()
    return (await name.inner_text()).strip()
