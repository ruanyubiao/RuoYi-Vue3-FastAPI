# -*- coding: utf-8 -*-
"""自动化目录：以 pytest --collect-only 为真源，保证与实跑 nodeid 一一对应。"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


_U_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")


def _unescape_pytest_id(s: str) -> str:
    """pytest 会把 parametrize id 里的非 ASCII 写成 \\uXXXX；仅解码这类序列供模板展示。"""
    if not s or "\\u" not in s:
        return s
    return _U_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), s)





def collect_nodeids() -> list[str]:
    import os
    cached = os.environ.get("HIL_CATALOG_NODEIDS_FILE")
    if cached and Path(cached).exists():
        return [ln.strip().lstrip("\ufeff") for ln in Path(cached).read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
    cache_path = ROOT / "artifacts" / "_collect_nodeids.txt"
    # 子进程收集时关闭报告填充，打断 collect↔fill 嵌套
    env = {**os.environ, "PYTHONPATH": str(ROOT), "HIL_SKIP_TEMPLATE_REPORT": "1"}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    lines = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("scenarios/") and "::" in line:
            lines.append(line)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("\n".join(lines), encoding="utf-8")
    return lines



def _meta_for(nodeid: str) -> dict:
    """从 nodeid 推导模板字段。"""
    auto_id = nodeid  # 硬规则：模板自动化ID = 完整 pytest nodeid
    suite = "other"
    module = "其他自动化"
    page = nodeid
    content = f"自动化用例：{nodeid}"

    if "test_unit_selfcheck.py" in nodeid:
        suite, module, page = "unit", "自检·单元", "本机自检（不连工控机）"
        name = nodeid.split("::", 1)[1]
        content = f"单元自检：{name}"
    elif "test_ui_pages.py" in nodeid:
        suite, module = "ui_only", "UI冒烟"
        name = nodeid.split("::", 1)[1]
        if name.startswith("test_page_opens["):
            path = name[len("test_page_opens[") : -1]
            page = f"页面 {path}"
            content = f"打开页面 {path}：URL 正确、特征元素可见、无 JS 异常、非 404"
        elif name.startswith("test_key_element_visible["):
            key = name[len("test_key_element_visible[") : -1]
            page = f"关键元素 {key}"
            content = f"关键元素可见：{key}"
        elif "sequence_add" in name:
            page = "BIU·指令序列"
            content = "指令序列「新增」进入编辑页（不保存）"
        elif "can_dialog_readonly" in name:
            page = "CAN 新建对话框"
            content = f"CAN 对话框只读检查：{name}"
        else:
            content = f"UI 冒烟：{name}"
    elif "test_hil_can.py" in nodeid:
        suite, module, page = "hil_can", "HIL·CAN", "CAN 硬件在环"
        name = nodeid.split("::", 1)[1]
        content = f"CAN HIL：{name}（发送/线帧/遥测显示闭环；缺黄金则 skip）"
    elif "test_hil_camera_image.py" in nodeid:
        suite, module, page = "hil_serial", "HIL·串口", "单板·相机图像串口"
        name = nodeid.split("::", 1)[1]
        content = f"相机图像 HIL：{name}（取消自动拍照→图片刷新；页面分辨率/元数据与发送一致；线侧TX vs 工控RX/页面画布像素一致）"
    elif "test_hil_history_file.py" in nodeid:
        suite, module = "ui_only", "遥测·深测"
        name = nodeid.split("::", 1)[1]
        if "file_curve" in name or "curve_deep" in name:
            page = "遥测 · 历史文件曲线"
            content = (
                f"历史文件曲线深测：{name}；选表→上传样本→解析/解析进程→"
                "加2~5条曲线→滑块查询(可分段等待)→轴控/滚轮/截取/重置→确认进程回收；"
                "无合格样本则 skip。"
            )
        elif "unpack_smoke" in name:
            page = "遥测 · 历史文件样本包"
            content = f"历史文件样本 zip 解压冒烟：{name}"
        else:
            page = "遥测 · 历史文件数据"
            content = (
                f"历史文件数据深测：{name}；选表→上传样本→解析/解析进程→"
                "选帧(上/下页/滑块/输入/自动播放)→确认进程回收；无合格样本则 skip。"
            )
    elif "test_tm_deep.py" in nodeid:
        suite, module = "ui_only", "遥测·深测"
        name = nodeid.split("::", 1)[1]
        page = "遥测/单板深测"
        content = f"遥测深测：{name}"
    elif "test_hil_serial.py" in nodeid:
        suite, module, page = "hil_serial", "HIL·串口", "串口/RS422 硬件在环"
        name = nodeid.split("::", 1)[1]
        content = f"串口 HIL：{name}（发送/接收/显示闭环；缺黄金则 skip）"
    elif "test_hil_udp.py" in nodeid:
        suite, module, page = "hil_udp", "HIL·UDP", "UDP 硬件在环"
        name = nodeid.split("::", 1)[1]
        content = f"UDP HIL：{name}（推送/字段显示；缺黄金则 skip）"
    elif "test_debug_" in nodeid:
        suite, module = "ui_only", "调试·深测"
        name = nodeid.split("::", 1)[1]
        if "checksum" in nodeid:
            page = "调试 → 校验计算"
        elif "numconv" in nodeid:
            page = "调试 → 数字转换"
        elif "timeconv" in nodeid:
            page = "调试 → 时间转换"
            if "protocol_to_unix" in name:
                content = (
                    f"时间转换·协议换算：{name}"
                    "（纪元+周/周内秒/毫秒→日期框 Unix ms + 结果表 ISO UTC/Unix）"
                )
            elif "date_parse" in name:
                content = (
                    f"时间转换·日期解析：{name}"
                    "（日期字符串/Unix→结果表 ISO UTC/Unix ms）"
                )
        elif "tmcalc" in nodeid:
            page = "调试 → 遥测计算"
        elif "config" in nodeid:
            page = "调试 → 配置文件"
        elif "xfer" in nodeid:
            page = "调试 → 数据收发"
        elif "simulate" in nodeid:
            page, module = "调试 → 数据模拟", "调试·数据模拟"
        else:
            page = "调试"
        # timeconv 分支已写好 content，勿覆盖
        if "timeconv" not in nodeid:
            content = f"调试深测：{name}"
    elif "test_db_schema.py" in nodeid:
        suite, module, page = "db_schema", "数据库·结构", "DUT MySQL schema"
        name = nodeid.split("::", 1)[1]
        content = f"数据库结构对照：{name}"

    return {
        "auto_id": auto_id,  # 保持 pytest 原始 nodeid（含 \uXXXX），供 fill 对齐
        "suite": suite,
        "module": module,
        "page": _unescape_pytest_id(page),
        "content": _unescape_pytest_id(content),
        "nodeid": nodeid,
    }


def build_catalog(include_db_placeholders: bool = True) -> list[dict]:
    nodeids = collect_nodeids()
    items = [_meta_for(n) for n in nodeids]
    if include_db_placeholders:
        # 若尚未收集到 db 测试（文件未落地），仍预留 3 条，便于先同步模板
        have_db = any("test_db_schema.py" in it["nodeid"] for it in items)
        if not have_db:
            for name, content in [
                (
                    "test_schema_tables_present",
                    "目标库表集合与本地 ruoyi-fastapi-my.sql（+patches）一致：无缺表",
                ),
                (
                    "test_schema_columns_match",
                    "目标库各表字段名与本地 SQL 定义一致：无缺字段",
                ),
                (
                    "test_schema_payload_tables",
                    "payload_cmd_sequence / payload_tm_frame / payload_tx_log 字段与本地 SQL 对齐",
                ),
            ]:
                nid = f"scenarios/test_db_schema.py::{name}"
                items.append(
                    {
                        "auto_id": nid,
                        "suite": "db_schema",
                        "module": "数据库·结构",
                        "page": "DUT MySQL schema",
                        "content": content,
                        "nodeid": nid,
                    }
                )
    return items


def main() -> None:
    cat = build_catalog()
    out = ROOT / "artifacts" / "_auto_catalog.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")
    from collections import Counter

    print("total", len(cat))
    print(dict(Counter(x["suite"] for x in cat)))


if __name__ == "__main__":
    main()
