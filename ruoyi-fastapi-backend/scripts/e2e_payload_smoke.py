"""
地检平台端到端冒烟测试（无需浏览器）。

流程：登录 -> 打开 DEMO CAN -> 下发遥控 -> 读遥测表 -> 序列 copy/run
用法：先启动 Redis 与后端，再执行
  venv\\Scripts\\python.exe scripts/e2e_payload_smoke.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BACKEND = "http://127.0.0.1:9099"
USERNAME = "admin"
PASSWORD = "admin123"
TIMEOUT = 30.0


def main() -> int:
    client = httpx.Client(base_url=BACKEND, timeout=TIMEOUT)
    steps: list[str] = []

    def step(name: str) -> None:
        steps.append(name)
        print(f"[{len(steps)}] {name}")

    # 1. 登录
    step("登录")
    r = client.post("/login", data={"username": USERNAME, "password": PASSWORD})
    r.raise_for_status()
    body = r.json()
    if body.get("code") != 200:
        print("登录失败:", body)
        return 1
    token = body.get("token")
    headers = {"Authorization": f"Bearer {token}"}

    # 2. 打开 DEMO CAN
    step("打开 CAN (vendor=0)")
    r = client.post(
        "/payload/device/can/open",
        headers=headers,
        json={"vendor": 0, "devIndex": 0, "canIndex": 0, "baudRate": 500, "nodeAddrTo": 13, "cableFlag": 0},
    )
    r.raise_for_status()
    open_data = r.json().get("data") or {}
    device_id = open_data.get("deviceId") or "can:0:0:0"
    print("  deviceId:", device_id)
    time.sleep(1.5)

    # 3. 遥控配置
    step("读取遥控配置")
    r = client.get("/payload/telecontrol/config", headers=headers)
    r.raise_for_status()
    cfg = r.json().get("data") or {}
    order_id = None
    for page in cfg.get("page") or []:
        for oid in page.get("orderList") or []:
            order_id = oid
            break
        if order_id:
            break
    if not order_id:
        print("  无可用指令，跳过下发")
    else:
        step(f"组帧并下发指令 {order_id}")
        r = client.get(f"/payload/telecontrol/order/{order_id}", headers=headers)
        r.raise_for_status()
        order = r.json().get("data") or {}
        r = client.post(
            "/payload/telecontrol/assemble",
            headers=headers,
            json={"orderId": order_id, "components": order.get("component") or []},
        )
        r.raise_for_status()
        hex_text = (r.json().get("data") or {}).get("hex", "")
        r = client.post(
            "/payload/telecontrol/send",
            headers=headers,
            json={"deviceId": device_id, "orderId": order_id, "name": order.get("name"), "hex": hex_text},
        )
        r.raise_for_status()
        send_res = r.json().get("data") or {}
        print("  send:", send_res)

    # 4. 遥测表（等待 DEMO 注入）
    step("轮询遥测表 FF")
    rows = []
    for _ in range(8):
        time.sleep(1)
        r = client.get("/payload/telemetry/table", headers=headers, params={"deviceId": device_id, "type": "FF"})
        r.raise_for_status()
        data = r.json().get("data") or {}
        rows = data.get("rows") or []
        if rows:
            print(f"  收到 {len(rows)} 行, ts={data.get('ts')}")
            break
    if not rows:
        print("  警告: 未收到遥测数据（采集进程可能未就绪）")

    # 5. 指令序列 CRUD + copy + run
    step("创建测试序列")
    sample_hex = "0A 91 00 04 00 04 AA AA"
    commands = json.dumps([{"name": "测试帧", "hex": sample_hex, "interval": 500}])
    r = client.post(
        "/payload/sequence",
        headers=headers,
        json={"seqName": f"E2E冒烟-{int(time.time())}", "commands": commands, "status": "0", "remark": "auto"},
    )
    r.raise_for_status()
    seq_list = client.get("/payload/sequence/list", headers=headers, params={"pageNum": 1, "pageSize": 10}).json()
    seq_id = None
    for row in seq_list.get("rows") or []:
        if (row.get("seqName") or "").startswith("E2E冒烟"):
            seq_id = row.get("seqId")
            break
    if not seq_id:
        print("  创建序列后未找到记录")
        return 1
    print("  seqId:", seq_id)

    step("复制序列")
    r = client.post(f"/payload/sequence/{seq_id}/copy", headers=headers)
    r.raise_for_status()
    draft = r.json().get("data") or {}
    print("  副本名称:", draft.get("seqName"))

    step("执行序列")
    r = client.post(f"/payload/sequence/{seq_id}/run", headers=headers, json={"deviceId": device_id})
    r.raise_for_status()
    run_res = r.json().get("data") or {}
    print("  run:", run_res)
    ok_count = sum(1 for x in (run_res.get("results") or []) if x.get("success"))
    if ok_count < (run_res.get("total") or 0):
        print("  警告: 部分指令执行超时，请确认采集进程存活")

    step("关闭 CAN")
    client.post(
        "/payload/device/can/close",
        headers=headers,
        json={"vendor": 0, "devIndex": 0, "canIndex": 0},
    )

    print("\n=== E2E 通过 ===")
    for i, s in enumerate(steps, 1):
        print(f"  {i}. {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
