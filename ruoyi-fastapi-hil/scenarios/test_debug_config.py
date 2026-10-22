# -*- coding: utf-8 -*-
"""调试·配置文件：与本地 assets/config 对照；页面按钮点击（重载/预览/下载/编辑开关键）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from hil.config import BACKEND_ROOT
from scenarios.debug_ui_helpers import load_json

pytestmark = [pytest.mark.ui_only]

LOCAL_DIR = BACKEND_ROOT / "assets" / "config"
MANIFEST = load_json("config_local_manifest.json")


def _norm_json(text: str):
    return json.loads(text)


def test_config_list_matches_local_names(api):
    remote = api.config_files_list()
    names = sorted({(x.get("name") if isinstance(x, dict) else str(x)) for x in remote})
    local = sorted(MANIFEST["names"])
    # DUT 可能多补丁文件；本地集合必须都能在 DUT 找到
    missing = [n for n in local if n not in names]
    assert not missing, f"DUT 缺本地配置: {missing}; DUT={names}"


@pytest.mark.parametrize("name", MANIFEST["names"][:8], ids=MANIFEST["names"][:8])
def test_config_content_matches_local(api, name):
    local_path = LOCAL_DIR / name
    assert local_path.exists(), local_path
    local_obj = json.loads(local_path.read_text(encoding="utf-8"))
    data = api.config_file_content(name)
    # content 字段或整包
    raw = data.get("content") if isinstance(data, dict) else None
    if raw is None and isinstance(data, dict) and "name" in data:
        # 有的实现直接返回解析后对象
        remote_obj = {k: v for k, v in data.items() if k not in ("name", "path", "layer", "datetime", "mtime", "size", "index")}
        if "content" in data:
            raw = data["content"]
        elif len(remote_obj) > 2:
            # fallback: fetch failed shape
            pass
    if isinstance(raw, (dict, list)):
        remote_obj = raw
    else:
        assert isinstance(raw, str) and raw.strip(), data
        remote_obj = json.loads(raw)
    assert remote_obj == local_obj, f"{name} 与本地不一致（键级或内容）"


@pytest.mark.asyncio(loop_scope="session")
async def test_config_page_buttons(ui, api):
    page = await ui.goto("/debug/configFile")
    await page.get_by_role("button", name="重新载入配置").wait_for(timeout=15000)
    # 列表有行
    await page.locator(".el-table tbody tr").first.wait_for(timeout=20000)
    # 上传按钮可见（不真传）
    await page.get_by_role("button", name="上传").wait_for(state="visible")
    # 重新载入全部
    async with page.expect_response(lambda r: "/payload/config-files/reload" in r.url, timeout=120000) as ri:
        await page.get_by_role("button", name="重新载入配置").click()
    resp = await ri.value
    assert resp.ok
    # 点第一行「预览」
    first_data = page.locator(".el-table tbody tr").filter(has=page.get_by_role("button", name="预览")).first
    await first_data.get_by_role("button", name="预览").click()
    dlg = page.locator(".el-dialog:visible, .el-overlay-dialog:visible").last
    await dlg.wait_for(timeout=15000)
    await dlg.locator("footer").get_by_role("button", name="关闭").click()
    # 下载（可能触发浏览器下载，只点）
    async with page.expect_response(lambda r: "/payload/config-files/content" in r.url, timeout=60000) as di:
        await first_data.get_by_role("button", name="下载").click()
    assert (await di.value).ok
    # 编辑打开再关闭（不保存）
    if await first_data.get_by_role("button", name="编辑").count():
        await first_data.get_by_role("button", name="编辑").click()
        dlg = page.locator(".el-dialog:visible").last
        await dlg.wait_for(timeout=15000)
        await dlg.locator("footer").get_by_role("button", name="关闭").click()
    # 单行重新载入（若有）
    reload_one = first_data.get_by_role("button", name="重新载入")
    if await reload_one.count():
        async with page.expect_response(lambda r: "/payload/config-files/reload" in r.url, timeout=120000):
            await reload_one.click()
    assert not ui.page_errors, ui.page_errors[:3]
