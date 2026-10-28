# -*- coding: utf-8 -*-
"""CAN 协议族 already_open 复用 + 遥控历史 can_frames（marker: hil_can）。

对齐联调 bug / backend DEMO：
- XL 开通道 → BIU 页 already_open（不关通道）→ 发 K1501 → 线帧应为单帧 00000368
- 对称 BIU → XL → 三帧 000002FB
- 历史面板：业务 HEX + can_frames 分帧 + 名称 tooltip

黄金：hil/testdata/can_assembler_reuse_k1501.json（与 backend tests/data 同源单文件）

单独跑（勿设单一 HIL_CAN_TARGET）：
  pytest scenarios/test_hil_can_reuse.py -m hil_can
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from conftest import can_skip_reason
from hil.config import CONFIG, HIL_ROOT
from scenarios.hil_steps import assert_wire_hex

pytestmark = [pytest.mark.hil_can, pytest.mark.asyncio(loop_scope='session')]

_GOLDEN = HIL_ROOT / 'hil' / 'testdata' / 'can_assembler_reuse_k1501.json'
CABLE = 'a'
ORDER_ID = 'K1501'


def _load_golden() -> dict:
    return json.loads(_GOLDEN.read_text(encoding='utf-8'))


def _case(golden: dict, case_id: str) -> dict:
    for c in golden['cases']:
        if c['id'] == case_id:
            return c
    raise KeyError(case_id)


def _require_cross_family() -> None:
    """复用需跨 XL/BIU；单 target 轮次跳过。"""
    r_hw = can_skip_reason(None)
    if r_hw:
        pytest.skip(r_hw)
    if CONFIG.can_target and CONFIG.can_target not in ('xl', 'biu'):
        # yj216-only round
        pytest.skip(f'协议族复用需 XL/BIU，当前 HIL_CAN_TARGET={CONFIG.can_target}')
    # 若指定了单一 target，另一族会 skip —— 复用必须两边都能开
    for fam in ('xl', 'biu'):
        r = can_skip_reason(fam)
        if r:
            pytest.skip(
                f'协议族复用需同时覆盖 xl 与 biu；{r}。'
                f'请无 HIL_CAN_TARGET 单独跑本文件。'
            )


def _expect_ids(case: dict) -> list[int]:
    return [int(fr['id']) & 0x1FFFFFFF for fr in case['expected_frames']]


def _frames_match(raw: list[tuple[int, bytes]], expect_ids: list[int], since: int) -> list[tuple[int, bytes]]:
    got = [(cid & 0x1FFFFFFF, data) for cid, data in raw[since:]]
    # 取末尾 len(expect) 帧（中间可能有其它噪声时尽量对齐末尾）
    if len(got) < len(expect_ids):
        return got
    return got[-len(expect_ids):]


async def _open_family_can(ui, family: str, cable: str, ch) -> dict:
    from hil.browser.pages import can_ui_open
    page = await ui.goto(f'/{family}/telecontrol/control', settle_ms=800)
    picked = await can_ui_open(page, cable, ch.vendor, ch.dev_index, ch.can_index)
    return picked


async def _reuse_open(ui, family: str, cable: str, ch) -> dict:
    """在目标族页面再次打开同通道（already_open → 确认键「使用」）。"""
    from hil.browser.pages import can_ui_open
    page = await ui.goto(f'/{family}/telecontrol/command', settle_ms=800)
    # 若工具栏已是「关闭CAN」说明会话已映射到本页，仍走对话框复用更贴 already_open
    bar = page.locator('.can-connect-toolbar').first
    if await bar.get_by_role('button', name=f'关闭CAN-{cable.upper()}').count():
        # 已显示关闭：仍点新建会走「使用」；若点不开则直接返回
        pass
    picked = await can_ui_open(page, cable, ch.vendor, ch.dev_index, ch.can_index)
    return picked


@pytest.mark.parametrize('case_id', ['xl_to_biu', 'biu_to_xl'], ids=['xl_to_biu', 'biu_to_xl'])
async def test_can_family_reuse_k1501_wire_and_history(ui, api, case_id: str):
    _require_cross_family()
    golden = _load_golden()
    case = _case(golden, case_id)
    first = str(case['first'])
    reuse = str(case['reuse'])
    payload_hex = str(golden['payload_hex'])
    expect_ids = _expect_ids(case)
    expect_id_hex = str(case['expected_frames'][0].get('id_hex') or f'{expect_ids[0]:08X}')

    from hil.browser.pages import (
        can_select_send,
        can_ui_close,
        history_name_tooltip,
        history_wait_can_frame,
        send_command_order,
    )
    from hil.hw.can_sim import CanSim
    from hil.samples import hex_to_bytes

    ch = CONFIG.ipc_can_channel(first, CABLE)  # 同物理通道
    col = api.collector()
    assert col.get('online'), f'采集机 {api.collector_host} 不在线'
    busy = api.busy_can(ch.vendor, ch.dev_index, [ch.can_index])
    if busy and not CONFIG.allow_busy:
        pytest.fail(f'CAN 通道被占用：{busy}')

    # 模拟器按 reuse 族解析业务帧；线帧断言用 raw_frames
    sim = CanSim(reuse, CONFIG, dry_run=False, cable=CABLE)
    sim.start()
    raw0 = len(sim.raw_frames)
    source = f'{reuse}_can_{CABLE}'
    try:
        try:
            api.clear_telecontrol_history(source)
        except Exception as exc:  # noqa: BLE001
            print(f'[HIL] clear history 跳过: {exc}', flush=True)

        picked1 = await _open_family_can(ui, first, CABLE, ch)
        print(f'[HIL] first open {first}: {picked1}', flush=True)

        picked2 = await _reuse_open(ui, reuse, CABLE, ch)
        print(f'[HIL] reuse open {reuse}: {picked2}', flush=True)
        # already_open 路径确认键应为「使用」（若首次映射则也可能「打开」）
        if picked2.get('confirm') not in ('打开', '使用'):
            pytest.fail(f'复用打开确认键异常: {picked2}')

        page = await ui.goto(f'/{reuse}/telecontrol/command', settle_ms=600)
        await can_select_send(page, CABLE)
        t_send = time.monotonic()
        await send_command_order(page, ORDER_ID)

        # --- E: 发送即时 flush：历史/线帧应很快出现（短超时）---
        expect_payload = hex_to_bytes(payload_hex)
        got_ev = sim.wait_for(
            lambda ev: getattr(ev, 'kind', None) == 'telecommand' and getattr(ev, 'payload', None) == expect_payload,
            timeout=8,
        )
        # 业务层：reuse 族应能正确拆出 K1501 载荷
        if got_ev is None:
            # 仍检查 raw 线帧 id，避免 parser 族差异掩盖组帧错误
            print('[HIL] telecommand 事件未匹配，继续用 raw_frames 断言', flush=True)
        else:
            assert_wire_hex(got_ev.payload, payload_hex, label=f'{case_id} 业务 HEX')

        # 等 raw 帧到位
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and len(sim.raw_frames) < raw0 + len(expect_ids):
            time.sleep(0.05)
        got_raw = _frames_match(sim.raw_frames, expect_ids, raw0)
        got_ids = [cid for cid, _ in got_raw]
        assert got_ids == expect_ids, (
            f'{case_id}: 线帧 id 不符（already_open 组帧错误？）'
            f' got={got_ids} expect={expect_ids} raw_tail={sim.raw_frames[raw0:]!r}'
        )
        # XL 三帧误用时 id 全是 0x2FB；BIU 单帧应为 0x368
        if case_id == 'xl_to_biu':
            assert len(got_ids) == 1 and got_ids[0] == 872, 'XL→BIU 必须是单帧 00000368'

        # --- B: 历史 can_frames + HEX + tooltip ---
        row = await history_wait_can_frame(
            page, id_hex=expect_id_hex, timeout_s=10, min_frames=len(expect_ids)
        )
        hex_norm = row['hex'].upper().replace(' ', '')
        expect_norm = payload_hex.upper().replace(' ', '')
        assert expect_norm in hex_norm or hex_norm in expect_norm, (
            f'历史业务 HEX 不符: {row["hex"]!r} expect {payload_hex!r}'
        )
        assert len(row['can_frames']) == len(expect_ids), (
            f'历史分帧数不符: {row["can_frames"]!r} expect {len(expect_ids)} 帧'
        )
        tip = await history_name_tooltip(page, 0)
        assert tip, '历史名称 tooltip/名称为空'
        # 名称不应长期停在 *.protocolBuild
        assert 'protocolBuild' not in tip and 'protocolbuild' not in tip.lower(), tip

        # API 侧 flush：短时间内 history 有 can_frames
        flush_ok = False
        while time.monotonic() - t_send < 5.0:
            hist = api.telecontrol_history(source, limit=10)
            if hist and isinstance(hist[0], dict) and hist[0].get('can_frames'):
                flush_ok = True
                break
            time.sleep(0.2)
        assert flush_ok, f'发送后 5s 内 history API 未见 can_frames（即时 flush？）source={source}'

        # 关通道（在 reuse 页）
        page = await ui.goto(f'/{reuse}/telecontrol/control', settle_ms=400)
        await can_ui_close(page, CABLE)
    finally:
        try:
            page = getattr(ui, 'page', None)
            if page is not None:
                from hil.browser.pages import can_ui_close
                try:
                    await can_ui_close(page, CABLE)
                except Exception:
                    pass
            api.ensure_hardware_idle(reason=f'after reuse {case_id}', timeout_s=12.0)
        except Exception as exc:  # noqa: BLE001
            print(f'[HIL] reuse teardown: {exc}', flush=True)
        sim.stop()


async def test_send_history_flush_after_tm_request(ui, api):
    """E 加深：开 CAN 后点「发送遥测请求」，history 名称应为中文「遥测请求」，且较快入历史。"""
    _require_cross_family()
    # 只测 BIU 即可（与 xl 共用线；本条不切族）
    r = can_skip_reason('biu')
    if r:
        pytest.skip(r)

    from hil.browser.pages import can_select_send, can_ui_close, can_ui_open, control_tm_request, history_panel_items
    from hil.hw.can_sim import CanSim

    family = 'biu'
    ch = CONFIG.ipc_can_channel(family, CABLE)
    busy = api.busy_can(ch.vendor, ch.dev_index, [ch.can_index])
    if busy and not CONFIG.allow_busy:
        pytest.fail(f'CAN 占用：{busy}')

    sim = CanSim(family, CONFIG, dry_run=False, cable=CABLE)
    sim.start()
    source = f'{family}_can_{CABLE}'
    try:
        try:
            api.clear_telecontrol_history(source)
        except Exception:
            pass
        page = await ui.goto(f'/{family}/telecontrol/control', settle_ms=800)
        await can_ui_open(page, CABLE, ch.vendor, ch.dev_index, ch.can_index)
        await can_select_send(page, CABLE)
        t0 = time.monotonic()
        await control_tm_request(page)
        # D: history_label
        deadline = time.monotonic() + 8
        names = []
        while time.monotonic() < deadline:
            hist = api.telecontrol_history(source, limit=5)
            names = [str(h.get('name') or '') for h in hist]
            if any('遥测请求' in n for n in names):
                break
            if any(n and 'protocolBuild' not in n for n in names):
                # 也可能是其它中文
                break
            time.sleep(0.25)
        assert any('遥测请求' in n for n in names), (
            f'history_label 未收成「遥测请求」: {names!r}（耗时 {time.monotonic()-t0:.2f}s）'
        )
        assert time.monotonic() - t0 < 5.0, '遥测请求写入历史过慢（即时 flush？）'
        # 历史 UI 在指令页嵌入；控制页无面板，转到 command 再扫一眼
        page = await ui.goto(f'/{family}/telecontrol/command', settle_ms=600)
        rows = await history_panel_items(page, timeout_ms=8000)
        if rows:
            assert 'protocolBuild' not in (rows[0].get('name') or '')
            assert any('遥测请求' in (r.get('name') or '') for r in rows), rows[:3]
        page = await ui.goto(f'/{family}/telecontrol/control', settle_ms=400)
        await can_ui_close(page, CABLE)
    finally:
        try:
            api.ensure_hardware_idle(reason='after tm_request history', timeout_s=12.0)
        except Exception:
            pass
        sim.stop()