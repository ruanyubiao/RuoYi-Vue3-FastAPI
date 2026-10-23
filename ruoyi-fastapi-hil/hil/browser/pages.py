"""页面清单与通用页面动作（选择器以 ruoyi-fastapi-frontend/src 源码为准）。"""
from __future__ import annotations

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
    opts = dropdown.locator('.el-select-dropdown__item')
    assert await opts.count() > 0, 'no device after refresh'
    await opts.first.click()
    await page.wait_for_timeout(400)
    # enable receive if toggle/checkbox exists
    for label in ('启用数据接收', '数据接收', '接收'):
        loc = page.get_by_text(label)
        if await loc.count():
            try:
                await loc.first.click(timeout=2000)
            except Exception:
                pass
            break
    if can_id is not None and await page.locator('.el-form-item').filter(has_text='帧ID').count():
        await page.locator('.el-form-item').filter(has_text='帧ID').locator('input').first.fill(can_id)
        data = page.locator('.el-form-item').filter(has_text='数据').locator('textarea, input')
        if await data.count():
            await data.first.fill(hex_data)
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

