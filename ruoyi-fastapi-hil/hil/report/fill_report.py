# -*- coding: utf-8 -*-
"""读模板 + 解析 junit → 生成填写版报告。"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.styles import Font

from hil.report.sync_template import DEFAULT_TEMPLATE, HEADERS, SHEET
from hil.report.xlsx_layout import apply_checklist_layout, apply_simple_sheet_layout, atomic_save

RESULT_MAP = {
    "passed": "通过",
    "failed": "失败",
    "error": "失败",
    "skipped": "跳过",
}


def _parse_junit(path: Path) -> dict[str, dict[str, Any]]:
    """nodeid(classname::name) -> {outcome, message}"""
    out: dict[str, dict[str, Any]] = {}
    tree = ET.parse(path)
    root = tree.getroot()
    # pytest junit: testsuite/testcase classname='scenarios.test_ui_pages' name='test_page_opens[/index]'
    suites = root.findall(".//testsuite") or ([root] if root.tag == "testsuite" else [])
    if root.tag == "testsuites":
        suites = root.findall("testsuite")
    for suite in suites if suites else [root]:
        for tc in suite.findall("testcase"):
            classname = (tc.get("classname") or "").replace(".", "/")
            name = tc.get("name") or ""
            # classname often scenarios.test_ui_pages -> scenarios/test_ui_pages.py
            if classname.endswith("/py"):
                pass
            nodeid = None
            if classname:
                # normalize to scenarios/xxx.py::name
                parts = classname.replace("\\", "/").split("/")
                if parts and not parts[-1].endswith(".py"):
                    parts[-1] = parts[-1] + ".py"
                nodeid = "/".join(parts) + "::" + name
            else:
                nodeid = name
            outcome = "passed"
            msg = ""
            if tc.find("failure") is not None:
                outcome = "failed"
                msg = (tc.find("failure").get("message") or "")[:500]
            elif tc.find("error") is not None:
                outcome = "error"
                msg = (tc.find("error").get("message") or "")[:500]
            elif tc.find("skipped") is not None:
                outcome = "skipped"
                msg = (tc.find("skipped").get("message") or "")[:500]
            out[nodeid] = {"outcome": outcome, "message": msg, "raw_name": name}
            # also index by name alone for fuzzy
            out.setdefault(name, out[nodeid])
    return out


def _load_all_junit(run_dir: Path) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for p in sorted(run_dir.glob("junit_*.xml")):
        merged.update(_parse_junit(p))
    return merged


def _match_result(auto_id: str, results: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if auto_id in results:
        return results[auto_id]
    # try basename match
    short = auto_id.split("scenarios/")[-1] if "scenarios/" in auto_id else auto_id
    for k, v in results.items():
        if k.endswith(short) or short.endswith(k) or k == auto_id.split("::")[-1]:
            return v
        # classname style: scenarios/test_ui_pages.py::x vs scenarios/test_ui_pages.py::x
        if "::" in k and "::" in auto_id and k.split("::")[-1] == auto_id.split("::")[-1]:
            # same test name; require same file stem
            if Path(k.split("::")[0]).stem == Path(auto_id.split("::")[0]).stem:
                return v
    return None


def fill_report_from_run(
    run_dir: Path | str,
    template: Path | str | None = None,
    tester: str = "自动化测试",
    sync_first: bool = False,
) -> dict:
    run_dir = Path(run_dir)
    template = Path(template) if template else DEFAULT_TEMPLATE
    if sync_first:
        from hil.report.sync_template import sync_template

        sync_info = sync_template(template)
    else:
        sync_info = {}

    results = _load_all_junit(run_dir)
    catalog_ids = set()  # 以模板自动化ID列为准；目录校验改由 sync 负责

    wb = load_workbook(template)
    ws = wb[SHEET]
    # ensure headers
    for col, name in enumerate(HEADERS, 1):
        if ws.cell(1, col).value != name:
            ws.cell(1, col).value = name

    today = datetime.now().strftime("%Y-%m-%d")
    filled = 0
    skipped_rows = 0
    failed_rows = 0
    passed_rows = 0
    unmapped_results: list[str] = []
    template_auto_ids: set[str] = set()

    for r in range(2, ws.max_row + 1):
        auto = ws.cell(r, 9).value
        if not auto:
            continue
        auto = str(auto).strip()
        template_auto_ids.add(auto)
        hit = _match_result(auto, results)
        if not hit:
            # 本轮未跑到：留空或标「未执行」
            if ws.cell(r, 5).value in (None, ""):
                ws.cell(r, 5).value = "未执行"
            continue
        label = RESULT_MAP.get(hit["outcome"], hit["outcome"])
        ws.cell(r, 5).value = label
        if hit["message"]:
            prev = ws.cell(r, 6).value or ""
            note = hit["message"]
            ws.cell(r, 6).value = (str(prev) + " | " + note).strip(" |") if prev else note
        ws.cell(r, 7).value = tester
        ws.cell(r, 8).value = today
        filled += 1
        if label == "通过":
            passed_rows += 1
        elif label == "跳过":
            skipped_rows += 1
        elif label == "失败":
            failed_rows += 1

    # 结果里有、模板没有 → 硬规则违例列表
    result_ids = {k for k in results if k.startswith("scenarios/")}
    missing_in_template = sorted(result_ids - template_auto_ids)
    # 也对照 catalog
    missing_from_catalog = []

    # 未映射结果（fuzzy 失败）
    matched_keys = set()
    for r in range(2, ws.max_row + 1):
        auto = ws.cell(r, 9).value
        if not auto:
            continue
        hit = _match_result(str(auto).strip(), results)
        if hit:
            matched_keys.add(str(auto).strip())
    for k in sorted(result_ids):
        if not _match_result(k, {kk: results[kk] for kk in results}):
            unmapped_results.append(k)
        else:
            # if matched via template row ok
            pass
    # simpler unmapped: results not matched to any template auto_id
    unmapped_results = []
    for k in sorted(result_ids):
        found = False
        for auto in template_auto_ids:
            if _match_result(auto, {k: results[k]}) is not None and (
                auto == k
                or auto.endswith(k.split("::")[-1])
                or Path(auto.split("::")[0]).stem == Path(k.split("::")[0]).stem
                and auto.split("::")[-1] == k.split("::")[-1]
            ):
                found = True
                break
        if k not in template_auto_ids:
            # direct
            if k not in template_auto_ids:
                unmapped_results.append(k)

    unmapped_results = missing_in_template  # 硬规则：结果 nodeid 不在模板

    # 文件名带本地时区日期时间，避免固定「填写」
    # One filled report per HIL_RUN_DIR: reuse run-dir stamp, overwrite same file.
    stamp = run_dir.name if re.fullmatch(r"\d{8}_\d{6}", run_dir.name or "") else datetime.now().strftime("%Y%m%d_%H%M%S")
    out_xlsx = run_dir / f"PGT测试清单_{stamp}.xlsx"
    # 写映射诊断 sheet
    if "映射诊断" in wb.sheetnames:
        diag = wb["映射诊断"]
        diag.delete_rows(1, diag.max_row)
    else:
        diag = wb.create_sheet("映射诊断")
    diag.cell(1, 1).value = "类型"
    diag.cell(1, 2).value = "ID"
    diag.cell(1, 1).font = Font(bold=True)
    diag.cell(1, 2).font = Font(bold=True)
    rr = 2
    for x in missing_in_template:
        diag.cell(rr, 1).value = "结果有/模板无"
        diag.cell(rr, 2).value = x
        rr += 1
    for x in missing_from_catalog:
        diag.cell(rr, 1).value = "目录有/模板无"
        diag.cell(rr, 2).value = x
        rr += 1
    template_only_auto = sorted(template_auto_ids - catalog_ids)
    for x in template_only_auto:
        diag.cell(rr, 1).value = "模板有/目录无(可能已删用例)"
        diag.cell(rr, 2).value = x
        rr += 1

    apply_checklist_layout(ws)
    if "映射诊断" in wb.sheetnames:
        apply_simple_sheet_layout(wb["映射诊断"], {1: 28, 2: 80})
    atomic_save(wb, out_xlsx)

    # 文本摘要
    summary = run_dir / "template_report_summary.txt"
    lines = [
        f"template={template}",
        f"report={out_xlsx}",
        f"filled={filled} passed={passed_rows} failed={failed_rows} skipped={skipped_rows}",
        f"template_auto={len(template_auto_ids)}",
        f"missing_in_template={len(missing_in_template)}",
        f"missing_from_catalog={len(missing_from_catalog)}",
        f"sync={sync_info}",
    ]
    if missing_in_template:
        lines.append("MISSING_IN_TEMPLATE:")
        lines.extend(f"  {x}" for x in missing_in_template[:50])
    summary.write_text("\n".join(lines), encoding="utf-8")

    return {
        "report": str(out_xlsx),
        "summary": str(summary),
        "filled": filled,
        "passed": passed_rows,
        "failed": failed_rows,
        "skipped": skipped_rows,
        "missing_in_template": missing_in_template,
        "missing_from_catalog": missing_from_catalog,
        "junit_cases": len(result_ids),
        "sync": sync_info,
    }


if __name__ == "__main__":
    import json
    import os
    import sys

    run = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(os.environ.get("HIL_RUN_DIR", "artifacts"))
    print(json.dumps(fill_report_from_run(run), ensure_ascii=False, indent=2))
