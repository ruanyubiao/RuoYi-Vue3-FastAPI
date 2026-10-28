# -*- coding: utf-8 -*-
"""P0-1 HIL：网页关 CAN 后短轮询 busy_can 归零（主断言，不靠 ensure_hardware_idle）。

ghost busy（尤其 can_xl）曾出现：UI 已关但 registry/busy_can 仍占通道。
本用例只验证关后 busy 短窗内清空；teardown 里的 ensure_hardware_idle 仅清场兜底，
不得当作本断言的绿路径。

跑法（需硬件 / 与其它 hil_can 相同）：
  cd ruoyi-fastapi-hil
  run_hil.bat can xl -k busy_clears_short_poll
  # 或：pytest scenarios/test_hil_can_busy_close.py -m hil_can -v -s
"""
from __future__ import annotations

import pytest

from conftest import can_skip_reason, require_can
from hil.config import CONFIG

pytestmark = [pytest.mark.hil_can, pytest.mark.asyncio(loop_scope='session')]

CABLES = ('a', 'b')


def _pick_family() -> str:
    """优先 xl（ghost 高发），否则 biu / yj216 / 当前 target。"""
    prefer = ('xl', 'biu', 'yj216')
    t = (CONFIG.can_target or '').strip().lower()
    order = (t,) + prefer if t else prefer
    seen: set[str] = set()
    for fam in order:
        if not fam or fam in seen:
            continue
        seen.add(fam)
        if can_skip_reason(fam) is None:
            return fam
    # 全部 skip 原因交给 require_can
    return t or 'xl'


async def test_can_ui_close_busy_clears_short_poll(ui, api):
    """打开 A/B → 网页关闭 → 短轮询 busy_can 必须空（不调用 idle 清场作绿）。"""
    family = _pick_family()
    require_can(family)

    from hil.browser.pages import can_ui_close, can_ui_open

    chs = {c: CONFIG.ipc_can_channel(family, c) for c in CABLES}
    col = api.collector()
    host = api.collector_host
    v0 = chs['a'].vendor
    indexes = [chs[c].can_index for c in CABLES]
    assert col.get('online'), f'采集机 {host} 不在线'
    busy0 = api.busy_can(v0, chs['a'].dev_index, indexes)
    if busy0 and not CONFIG.allow_busy:
        pytest.fail(f'采集机 {host} CAN 通道已占用：{busy0}')

    page = await ui.goto(f'/{family}/telecontrol/control', settle_ms=800)
    opened: list[str] = []
    try:
        for c in CABLES:
            ch = chs[c]
            await can_ui_open(page, c, ch.vendor, ch.dev_index, ch.can_index)
            opened.append(c)

        busy_open = api.busy_can(v0, chs['a'].dev_index, indexes)
        assert busy_open, f'打开后 busy_can 应非空（family={family}）'

        for c in CABLES:
            ok = await can_ui_close(page, c)
            assert ok, f'网页关闭 CAN-{c.upper()} 失败（无关闭按钮？）'
            opened = [x for x in opened if x != c]

        # 主断言：短轮询归零（禁止此处 ensure_hardware_idle）
        api.wait_busy_can_empty(
            v0,
            chs['a'].dev_index,
            indexes,
            timeout_s=5.0,
            interval_s=0.2,
            reason=f'ui-close-{family}',
        )
    finally:
        # 清场兜底：不计入本用例绿路径
        try:
            page = getattr(ui, 'page', None)
            if page is not None:
                for c in list(opened) or list(CABLES):
                    try:
                        await can_ui_close(page, c)
                    except Exception:
                        pass
            api.ensure_hardware_idle(reason='after busy_clears_short_poll', timeout_s=12.0)
        except Exception as exc:  # noqa: BLE001
            print(f'[HIL] busy_close teardown: {exc}', flush=True)
