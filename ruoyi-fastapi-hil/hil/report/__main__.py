# -*- coding: utf-8 -*-
"""python -m hil.report sync|fill|catalog"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hil.report")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_sync = sub.add_parser("sync", help="同步自动化目录到 PGT测试清单模板.xlsx")
    p_sync.add_argument("--template", default=None)

    p_fill = sub.add_parser("fill", help="读模板+junit 生成填写版报告")
    p_fill.add_argument("run_dir", nargs="?", default=None)
    p_fill.add_argument("--template", default=None)
    p_fill.add_argument("--sync", action="store_true", help="填报前先 sync 模板（默认不同步）")

    sub.add_parser("catalog", help="导出自动化目录 JSON")

    args = p.parse_args(argv)
    if args.cmd == "catalog":
        from hil.report.catalog import build_catalog

        cat = build_catalog()
        out = Path("artifacts/_auto_catalog.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"total": len(cat), "path": str(out)}, ensure_ascii=False))
        return 0
    if args.cmd == "sync":
        from hil.report.sync_template import sync_template

        info = sync_template(Path(args.template) if args.template else None)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if not info["missing_auto_ids"] else 2
    if args.cmd == "fill":
        from hil.report.fill_report import fill_report_from_run

        run = Path(args.run_dir or os.environ.get("HIL_RUN_DIR") or "artifacts")
        info = fill_report_from_run(
            run,
            template=Path(args.template) if args.template else None,
            sync_first=bool(args.sync),
        )
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if not info["missing_in_template"] and not info["missing_from_catalog"] else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
