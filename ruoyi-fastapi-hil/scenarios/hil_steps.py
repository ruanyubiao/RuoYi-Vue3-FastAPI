"""HIL 场景公共步骤：遥测断言（UI 为主，接口兜底给出诊断信息）。"""
from __future__ import annotations

import time

from hil.browser.pages import TM_LIVE_PREFS_KEY, pick_fields, read_tm_rows, refresh_text, wait_tm_fields
from hil.ipc_api import find_field_rows
from hil.samples import tm_fields


async def assert_tm_live(ui, api, table_key: str, golden_key: str, exclude: set[str] = frozenset(), timeout_s: float = 15):
    """实时数据页预选遥测表 → 等待字段显示值 = 黄金样本 result.fields.show。"""
    page = await ui.goto('/index')
    await ui.set_local_json(TM_LIVE_PREFS_KEY, {'tmType': table_key})
    page = await ui.goto('/telemetry/live', settle_ms=500)
    expect = pick_fields(tm_fields(golden_key), exclude)
    await assert_fields_on_page(ui, api, page, table_key, expect, timeout_s)


async def assert_fields_on_page(ui, api, page, table_key: str, expect: list[dict], timeout_s: float,
                                root: str = '.payload-tm-table'):
    bad = await wait_tm_fields(page, expect, timeout_s, root)
    if bad:
        diag = ''
        try:
            rows = find_field_rows(api.telemetry_table(table_key))
            diag = {k: rows.get(k, {}).get('show') for k in bad}
        except Exception as exc:  # noqa: BLE001
            diag = f'接口读取失败: {exc}'
        await ui.screenshot(f'tm_mismatch_{table_key}')
        raise AssertionError(f'遥测表 {table_key} 字段不符（期望, 页面）: {bad}；接口值: {diag}')


async def assert_refreshing(page, timeout_s: float, root: str = '.payload-tm-table') -> None:
    """只验证表格在刷新（刷新时间变化且有行），用于没有字段级期望值的表（RS422 全 0 / UDP 工程遥测）。"""
    first = await refresh_text(page, root)
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        await page.wait_for_timeout(1000)
        now = await refresh_text(page, root)
        rows = await read_tm_rows(page, root)
        if now and now != first and '-' != now.split(':', 1)[-1].strip() and rows:
            return
    raise AssertionError(f'遥测表 {timeout_s}s 内未刷新（刷新时间: {first!r} → {await refresh_text(page, root)!r}）')


def assert_wire_hex(got: bytes | None, expect_hex: str, *, label: str) -> None:
    """线帧逐字节对比；失败带 expect/actual hex。"""
    from hil.goldens import assert_tx_bytes
    assert_tx_bytes(got, expect_hex, label=label)


async def assert_tm_fields_diff(ui, api, page, table_key: str, golden_key: str,
                                exclude: set[str] | frozenset = frozenset(), timeout_s: float = 15,
                                root: str = '.payload-tm-table') -> None:
    """字段级黄金对比；失败打印 id → (expect, actual)。"""
    from hil.browser.pages import pick_fields, wait_tm_fields
    from hil.goldens import fields_diff
    from hil.ipc_api import find_field_rows
    from hil.samples import tm_fields
    expect = pick_fields(tm_fields(golden_key), set(exclude))
    bad = await wait_tm_fields(page, expect, timeout_s, root)
    if bad:
        try:
            rows = find_field_rows(api.telemetry_table(table_key))
            actual = {k: str(rows.get(k, {}).get('show', '')) for k in bad}
        except Exception:  # noqa: BLE001
            actual = {k: v[1] for k, v in bad.items()}
        diff = fields_diff(expect, {**{f['id']: f.get('show','') for f in expect}, **actual}, set(exclude))
        await ui.screenshot(f'tm_mismatch_{table_key}')
        raise AssertionError(f'遥测表 {table_key} 字段不匹配: {diff or bad}')
