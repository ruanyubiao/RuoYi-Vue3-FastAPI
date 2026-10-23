# -*- coding: utf-8 -*-
"""重建 PGT测试清单模板：业务全量（菜单+自动化），排除若依 system/monitor/tool。不写 bak。"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from hil.report.xlsx_layout import (
    apply_checklist_layout,
    apply_simple_sheet_layout,
    atomic_save,
)

from hil.browser.pages import PAYLOAD_PAGES
from hil.report.catalog import build_catalog

REPO = Path(__file__).resolve().parents[3]
DEFAULT_TEMPLATE = REPO / "doc" / "PGT测试清单模板.xlsx"
SHEET = "功能测试清单"
SUMMARY = "按模块汇总"
DIAG = "映射说明"

HEADERS = [
    "序号", "模块", "页面标题", "测试内容", "测试结果",
    "缺陷编号/备注", "测试人", "测试日期", "自动化ID", "套件",
]

# 若依框架菜单前缀 / 组件：不进业务清单
RUOYI_EXCLUDE_PREFIXES = (
    "/system/",
    "/monitor/",
    "/tool/",
    "/user/profile",
    "/login",
    "/register",
)

# HIL 里仍冒烟但挂在 monitor 下的项：模板不收，回报里问用户
UNCERTAIN_KEEP_OUT = {
    "/monitor/transportCrypto",
}


def _is_ruoyi_path(path: str) -> bool:
    p = path if path.startswith("/") else "/" + path
    return any(p.startswith(x) or p == x.rstrip("/") for x in RUOYI_EXCLUDE_PREFIXES)


def _business_pages() -> list[tuple[str, str, str]]:
    """现网业务页 = HIL PAYLOAD_PAGES 去掉若依系统路径。"""
    out = []
    for path, sel, title in PAYLOAD_PAGES:
        if _is_ruoyi_path(path) or path in UNCERTAIN_KEEP_OUT:
            continue
        out.append((path, sel, title))
    return out


def _page_function_rows() -> list[dict]:
    """深自动化待办（发送/接收闭环等）。浅层「打开+关键控件/开连接入口」已由 UI冒烟 KEY_ELEMENTS 覆盖。"""
    rows: list[dict] = []
    deep = [
        # 首页更深：真正打开连接并出现在列表（需硬件/采集在线）
        ("首页", "首页·dashboard设备服务 /index", "新建 CAN/UDP/串口成功并出现在设备列表；关闭连接后列表更新（开连接闭环）", ""),
        # 遥控发送/遥测请求真发
        ("遥控-BIU", "BIU·控制", "已开 CAN 后发送遥测请求/定时遥测；控制页 HEX 发送成功（发送闭环）", ""),
        ("遥控-BIU", "BIU·遥控", "选指令改参后发送；发送历史出现记录（发送/显示闭环）", ""),
        ("遥控-BIU", "BIU·指令序列", "执行序列选设备并完成至少一条发送（发送闭环）", ""),
        ("遥控-XL", "XL·控制", "已开 CAN 后遥测请求/定时遥测/GNSS 广播发送成功（发送闭环）", ""),
        ("遥控-XL", "XL·遥控", "选指令发送并写入发送历史（发送/显示闭环）", ""),
        ("遥控-XL", "XL·指令序列", "执行序列至少一条发送成功（发送闭环）", ""),
        ("遥控-YJ216", "YJ216·控制", "已开 CAN 后遥测请求发送成功（发送闭环）", ""),
        ("遥控-YJ216", "YJ216·遥控", "选指令发送并写入发送历史（发送/显示闭环）", ""),
        ("遥控-YJ216", "YJ216·指令序列", "执行序列至少一条发送成功（发送闭环）", ""),
        ("单板·YJ216", "YJ216·RS422", "开串口后遥测请求回包且表字段刷新（发送/接收/显示闭环）", ""),
        ("遥测", "实时数据", "有实时源时表字段轮询刷新当前值（接收/显示）", ""),
        ("遥测", "实时曲线", "添加曲线后实时刷新并可导出 CSV（接收/显示）", ""),
        ("遥测", "历史CAN数据", "选表+时间解析后回放切帧表格变化（接收/显示）", ""),
        ("遥测", "历史CAN曲线", "查询历史曲线绘制成功（接收/显示）", ""),
        ("遥测", "历史文件数据", "上传或选文件解析后回放可用（接收/显示）", ""),
        ("遥测", "历史文件曲线", "对已解析文件选量绘图（接收/显示）", ""),
        ("单板", "相机v1.6/v1.7", "控制口发指令+图像口出图并可保存（发送/接收/显示闭环）", ""),
        ("单板", "热控电机/CPA-ZK/CPA指向", "开串口发指令后遥测或传输信息有收发（发送/接收/显示）", ""),
        ("单板", "地检板", "开 UDP 后工程遥测字段刷新（接收/显示）", ""),
        ("调试", "数据模拟", "注入后在「遥测」菜单确认字段刷新（跨页接收/显示闭环；页面/dev API 冒烟已自动化）", ""),
        ("调试", "数据收发", "更复杂双端回环/多设备类型矩阵（基础开设备+网页发送已专项自动化）", ""),
        ("调试", "配置文件", "热重载后业务页配置生效验证（列表/对照/按钮点击已专项自动化）", ""),
        ("调试", "遥测计算/校验/数转", "全表全字段穷尽与边界（抽样 golden 对比已专项自动化）", ""),
    ]
    for mod, page, content, _aid in deep:
        rows.append(
            {
                "module": mod,
                "page": page,
                "content": f"[待深自动化] {content}",
                "auto_id": "",
                "suite": "manual_page",
            }
        )
    return rows



def _filter_catalog(catalog: list[dict]) -> list[dict]:
    """自动化目录：丢掉明显若依系统页的 UI 冒烟；HIL/unit/db 全留。"""
    out = []
    for it in catalog:
        nid = it.get("nodeid") or it.get("auto_id") or ""
        page = it.get("page") or ""
        # ui page_opens / key_element for monitor/system/tool
        if "test_ui_pages.py" in nid:
            # extract path from nodeid [...] 
            if "/monitor/" in nid or "/system/" in nid or "/tool/" in nid:
                continue
            if "/monitor/" in page or "系统监控" in (it.get("module") or ""):
                # transportCrypto 等
                continue
        out.append(it)
    return out


def sync_template(template: Path | None = None, keep_manual: bool = True) -> dict:
    path = Path(template) if template else DEFAULT_TEMPLATE
    path.parent.mkdir(parents=True, exist_ok=True)

    catalog = _filter_catalog(build_catalog(include_db_placeholders=True))
    page_rows = _page_function_rows() if keep_manual else []

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    for col, name in enumerate(HEADERS, 1):
        ws.cell(1, col, name).font = Font(bold=True)

    r = 2
    for it in catalog:
        ws.cell(r, 1, r - 1)
        ws.cell(r, 2, it["module"])
        ws.cell(r, 3, it["page"])
        ws.cell(r, 4, it["content"])
        ws.cell(r, 9, it["auto_id"])
        ws.cell(r, 10, it["suite"])
        for c in range(1, 11):
            ws.cell(r, c).alignment = Alignment(wrap_text=True, vertical="top")
        r += 1
    auto_count = len(catalog)

    for it in page_rows:
        ws.cell(r, 1, r - 1)
        ws.cell(r, 2, it["module"])
        ws.cell(r, 3, it["page"])
        ws.cell(r, 4, it["content"])
        ws.cell(r, 9, None)
        ws.cell(r, 10, it.get("suite") or "manual_page")
        for c in range(1, 11):
            ws.cell(r, c).alignment = Alignment(wrap_text=True, vertical="top")
        r += 1

    mods = Counter()
    for rr in range(2, r):
        mods[str(ws.cell(rr, 2).value or "未分类")] += 1

    ws2 = wb.create_sheet(SUMMARY)
    for c, h in enumerate(["模块", "用例数", "建议测试人", "完成数", "通过数", "备注"], 1):
        ws2.cell(1, c, h).font = Font(bold=True)
    rr = 2
    for mod, n in sorted(mods.items(), key=lambda x: (-x[1], x[0])):
        ws2.cell(rr, 1, mod)
        ws2.cell(rr, 2, n)
        rr += 1
    ws2.cell(rr, 1, "合计")
    ws2.cell(rr, 2, sum(mods.values()))

    ws3 = wb.create_sheet(DIAG)
    ws3.cell(1, 1, "说明").font = Font(bold=True)
    ws3.cell(
        2,
        1,
        "由 python -m hil.report sync 重建：以 pytest 实采自动化 + 现网业务页（排除若依 system/monitor/tool）为准；"
        "旧清单不作权威。自动化ID=pytest nodeid；空=页面功能待补自动化。填报：python -m hil.report fill <run_dir>。"
        "禁止生成 .bak。",
    )

    apply_checklist_layout(ws)
    apply_simple_sheet_layout(ws2)
    apply_simple_sheet_layout(ws3, {1: 100})

    atomic_save(wb, path)

    present = {
        str(ws.cell(rr, 9).value).strip()
        for rr in range(2, ws.max_row + 1)
        if ws.cell(rr, 9).value
    }
    missing = [it["auto_id"] for it in catalog if it["auto_id"] not in present]

    return {
        "template": str(path),
        "backup": None,
        "rows_total": ws.max_row - 1,
        "auto_rows": auto_count,
        "page_rows": len(page_rows),
        "catalog": len(catalog),
        "missing_auto_ids": missing,
        "modules": dict(mods),
        "excluded_ruoyi_note": "system/monitor/tool；transportCrypto 按结论保持不测",
    }


if __name__ == "__main__":
    import json

    print(json.dumps(sync_template(), ensure_ascii=False, indent=2))
