# -*- coding: utf-8 -*-
r"""can_xl 幽灵占用专项复现脚本（非 pytest 正式用例）。

=============================================================================
测什么
=============================================================================
在真实 DUT（默认 http://192.168.100.52:12580，采集机 gk3）上，对 **XL CAN** 反复执行：

  网页开 CAN-A/B → 网页发送**长/复杂**遥控（默认 D1651「19根数参数包1上注」）
  → 网页关 CAN-A/B → **立刻**读 busy_can / registry
  → 再 ensure_hardware_idle → 再读 busy_can / registry

关注点不是「指令黄金是否比对通过」，而是：网页已经关掉 CAN 之后，工控机侧
registry / busy_can 是否仍短暂残留 assembler=can_xl（幽灵占用短窗口）。

=============================================================================
测试目的
=============================================================================
1. 稳定复现并量化「网页关 CAN 后立刻」vs「ensure_hardware_idle 之后」的幽灵率。
2. 用比 K1501（约 8 字节）长得多的指令（D1651 实测约 142 字节）验证该窗口与短指令无关。
3. 约束关 CAN 必须走 Playwright 点界面（关闭CAN-A/B），不把 close_can_device /
   close_all 当作用例路径上的「关 CAN」步骤；ensure_hardware_idle 仅作轮次间/收尾兜底
   （其内部可含 close API）。
4. 为正式 HIL（scenarios/test_hil_can.py）用例间清场策略提供证据：仅 UI 关不够，
   仍需 idle/轮询 busy 至空，否则同会话下一条用例会在 busy_can 断言处失败。

=============================================================================
复现背景（摘要）
=============================================================================
全量 run_hil.bat can xl 中曾出现：can_xl__K1501 通过后，同会话 can_xl__tm_request
失败，文案类似：

  采集机 gk3 CAN 通道被占用：
  {0: 'can:3:0:0 assembler=can_xl cable_flag=0 node_addr_to=13',
   1: 'can:3:0:1 assembler=can_xl cable_flag=1 node_addr_to=13'}

专项曾跑满 100 轮（短 K1501 + API close_all）：close 后立刻幽灵约 99/100，idle 后 0/100。
后改为长指令 D1651 + 网页关 CAN 再验 40 轮：网页关后立刻 40/40，idle 后 0/40。
产物目录名形如 artifacts/can_xl_ghost_busy_<时间戳>/REPRO.md。

=============================================================================
硬性约束
=============================================================================
- 只改 / 只跑 ruoyi-fastapi-hil；不改业务前后端；默认不 git commit。
- 开 CAN、发遥控、关 CAN：Playwright UI（can_ui_open / send_command_order / can_ui_close）。
- 轮次前/后可调用 ensure_hardware_idle（允许内部 close API 作兜底）。
- 缺黄金不瞎编；本脚本不依赖 wire golden 比对，只要求页面能组帧并点「发送指令」。

=============================================================================
如何运行
=============================================================================
工作目录：ruoyi-fastapi-hil 根（需能 import hil.*，与 run_hil.bat 相同）。

  cd /d E:/plat/PayloadGroundTest/ruoyi-fastapi-hil
  set PYTHONPATH=%CD%
  python -m hil.repro_scripts.ghost_busy_repro --rounds 40
  python -m hil.repro_scripts.ghost_busy_repro --rounds 40 --order D1651
  python -m hil.repro_scripts.ghost_busy_repro --rounds 20 --order B001

依赖：本机已装 Playwright 浏览器驱动、能连 DUT、hil.local.json 中 CAN IPC 映射正确；
有头浏览器（HIL_HEADED 默认开）。会真实打开工控机 XL CAN，勿与他人抢同一采集机。

=============================================================================
产物
=============================================================================
  artifacts/can_xl_ghost_busy_<yyyyMMdd_HHmmss>/
    REPRO.md       复现率、步骤、关 CAN 点击路径、与历史对比
    rounds.jsonl   每轮完整采样
    meta.json      DUT/采集机/指令元数据
    （失败时可能有截图）

本文件位于 hil/repro_scripts/（专项脚本目录，非正式 scenarios 套件）。说明见同目录 README.md。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from hil.browser.pages import can_select_send, can_ui_close, can_ui_open, send_command_order
from hil.browser.session import BrowserSession
from hil.config import CONFIG, HIL_ROOT, run_dir
from hil.ipc_api import IpcApi

FAMILY = 'xl'
CABLES = ('a', 'b')
# 比 K1501(8B) 长得多：D1651≈142B / 21 字段；B001≈119B / 29 字段
DEFAULT_ORDER = 'D1651'
ORDER_META = {
    'D1651': {'name': '19根数参数包1上注', 'note': 'XL-TeleControlCfg 长上注包，组件约21，组帧约140B+'},
    'B001': {'name': '姿轨广播', 'note': '组件约29，组帧约119B'},
    'D1652': {'name': '19根数参数包2上注', 'note': '次长上注'},
    'K1501': {'name': '通信激光器驱动禁止', 'note': '短帧对照，默认不再使用'},
}


def _ts() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _alive_can(api: IpcApi) -> list[dict[str, Any]]:
    out = []
    for r in api.registry() or []:
        if r.get('type') != 'can' or not r.get('alive', True):
            continue
        cfg = r.get('config') or {}
        channels = [
            {
                'can_index': ch.get('can_index'),
                'assembler_id': ch.get('assembler_id'),
                'cable_flag': ch.get('cable_flag'),
                'node_addr_to': ch.get('node_addr_to'),
            }
            for ch in (cfg.get('channels') or [])
            if isinstance(ch, dict) and ch.get('can_index') is not None
        ]
        if not channels and not (r.get('channels') or []):
            continue
        out.append({
            'deviceId': r.get('deviceId'),
            'vendor': cfg.get('vendor'),
            'channels': channels or [
                {'can_index': ci} for ci in (r.get('channels') or [])
            ],
        })
    return out


def _snap(api: IpcApi, label: str) -> dict[str, Any]:
    chs = {c: CONFIG.ipc_can_channel(FAMILY, c) for c in CABLES}
    v0, dev = chs['a'].vendor, chs['a'].dev_index
    indexes = [chs[c].can_index for c in CABLES]
    try:
        sessions = list(api.sessions() or [])
    except Exception as exc:  # noqa: BLE001
        sessions = [f'ERR:{exc}']
    try:
        busy = api.busy_can(v0, dev, indexes)
    except Exception as exc:  # noqa: BLE001
        busy = {'_err': str(exc)}
    try:
        reg = _alive_can(api)
    except Exception as exc:  # noqa: BLE001
        reg = [f'ERR:{exc}']
    return {
        'label': label,
        'at': _ts(),
        'sessions': sessions,
        'registry_alive_can': reg,
        'busy_can': busy,
    }


def _is_ghost(snap: dict[str, Any]) -> bool:
    busy = snap.get('busy_can') or {}
    if isinstance(busy, dict) and any(k != '_err' for k in busy):
        return True
    reg = snap.get('registry_alive_can') or []
    if any(isinstance(r, dict) for r in reg):
        return True
    return False


async def one_round(api: IpcApi, browser: BrowserSession, n: int, order_id: str) -> dict[str, Any]:
    rec: dict[str, Any] = {
        'round': n,
        'started_at': _ts(),
        'order_id': order_id,
        'order_name': ORDER_META.get(order_id, {}).get('name', ''),
        'tx_hex': '',
        'tx_hex_len_bytes': 0,
        'ui_close': {},
        'ui_close_path': 'toolbar「关闭CAN-A/B」→ MessageBox 确定 → 等待「新建CAN连接-A/B」',
        'steps': [],
        'ghost_after_ui_close': False,
        'ghost_after_ensure_idle': False,
        'ghost': False,
        'error': None,
    }
    chs = {c: CONFIG.ipc_can_channel(FAMILY, c) for c in CABLES}

    def add(label: str, **extra: Any) -> dict[str, Any]:
        s = _snap(api, label)
        s.update(extra)
        rec['steps'].append(s)
        return s

    try:
        try:
            api.ensure_hardware_idle(reason=f'round{n}-pre', timeout_s=15.0)
            rec['pre_idle'] = 'ok'
        except Exception as exc:  # noqa: BLE001
            rec['pre_idle'] = f'fail:{exc}'
        add('after_pre_idle')

        page = await browser.goto(f'/{FAMILY}/telecontrol/command', settle_ms=500)
        for c in CABLES:
            ch = chs[c]
            await can_ui_open(page, c, ch.vendor, ch.dev_index, ch.can_index)
        add('after_ui_open_ab')

        await can_select_send(page, 'a')
        hx = await send_command_order(page, order_id)
        rec['tx_hex'] = hx or ''
        rec['tx_hex_len_bytes'] = len((hx or '').replace(' ', '')) // 2
        add('after_long_order', tx_hex_preview=(hx or '')[:160])

        # —— 显式关 CAN：仅网页 —— #
        for c in CABLES:
            ok = await can_ui_close(page, c)
            rec['ui_close'][c] = bool(ok)
            if not ok:
                raise RuntimeError(f'网页关闭 CAN-{c.upper()} 失败（未找到关闭CAN-{c.upper()}）')
        snap_close = add('after_ui_close')
        rec['ghost_after_ui_close'] = _is_ghost(snap_close)

        # —— 兜底 idle（允许内部 close API）—— #
        idle_ok, idle_err = True, None
        try:
            api.ensure_hardware_idle(reason=f'round{n}-post', timeout_s=15.0)
        except Exception as exc:  # noqa: BLE001
            idle_ok, idle_err = False, str(exc)
        snap_idle = add('after_ensure_idle', idle_ok=idle_ok, idle_err=idle_err)
        rec['ghost_after_ensure_idle'] = _is_ghost(snap_idle) or (not idle_ok)
        rec['ghost'] = bool(rec['ghost_after_ui_close'] or rec['ghost_after_ensure_idle'])
    except Exception as exc:  # noqa: BLE001
        rec['error'] = repr(exc)
        try:
            await browser.screenshot(f'ghost_long_round{n:03d}_ERR')
        except Exception:
            pass
        try:
            # 异常时允许 idle 兜底清场，避免污染后续轮
            api.ensure_hardware_idle(reason=f'round{n}-error', timeout_s=15.0)
        except Exception:
            pass
    rec['finished_at'] = _ts()
    return rec


def write_repro(out: Path, rows: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    n = len(rows)
    g_ui = sum(1 for r in rows if r.get('ghost_after_ui_close'))
    g_idle = sum(1 for r in rows if r.get('ghost_after_ensure_idle'))
    g_any = sum(1 for r in rows if r.get('ghost'))
    errs = [r for r in rows if r.get('error')]
    order_id = meta.get('order_id')
    sample_hex = next((r.get('tx_hex') for r in rows if r.get('tx_hex')), '')
    sample_len = next((r.get('tx_hex_len_bytes') for r in rows if r.get('tx_hex_len_bytes')), 0)

    L: list[str] = []
    a = L.append
    a('# can_xl 幽灵占用复验报告（长指令 + 网页关 CAN）\n\n')
    a(f'- 时间（Asia/Shanghai）: {meta.get("generated_at")}\n')
    a(f'- DUT: `{meta.get("frontend")}` / 采集机 `{meta.get("collector")}` / 版本 `{meta.get("appVersion")}`\n')
    a(f'- 脚本: `python -m hil.repro_scripts.ghost_busy_repro --rounds {n} --order {order_id}`\n')
    a(f'- 长指令: **{order_id}** {ORDER_META.get(order_id, {}).get("name", "")}；'
      f'实测组帧 **{sample_len} 字节**（对照 K1501=8 字节）\n')
    a(f'- 组帧 hex 预览: `{sample_hex[:120]}…`\n' if sample_hex else '- 组帧 hex: （无）\n')
    a('- 网页关 CAN 路径: 工具栏按钮 `关闭CAN-A` / `关闭CAN-B` → `.el-message-box` 点「确定」'
      ' → 等待再次出现 `新建CAN连接-A/B`（`hil.browser.pages.can_ui_close`）\n')
    a('- 用例路径**不**调用 `close_can_device` / `close_all` 作为关 CAN；'
      '`ensure_hardware_idle` 仅作轮次后兜底采样\n')
    a(f'- 总轮次: **{n}**；脚本异常: {len(errs)}\n')
    a(f'- **网页关后立刻幽灵**: **{g_ui}/{n}（{100 * g_ui / max(n, 1):.1f}%）**\n')
    a(f'- **ensure_idle 后仍幽灵**: **{g_idle}/{n}（{100 * g_idle / max(n, 1):.1f}%）**\n')
    a(f'- 任一判定幽灵: {g_any}/{n}\n')
    a('- 对比上次（短 K1501 + API close_all）: **99/100（99%）** 在 close-all 后幽灵；'
      'idle 后 0/100\n')
    a(f'- 原始: `{out / "rounds.jsonl"}`\n\n')

    a('## 每轮步骤\n\n')
    a('1. `ensure_hardware_idle(pre)`（兜底清场）\n')
    a('2. Playwright `/xl/telecontrol/command`\n')
    a('3. UI `新建CAN连接-A/B`（IPC vendor3）\n')
    a(f'4. UI 发送 **{order_id}**（搜索/点卡/发送指令，可读预览组帧）\n')
    a('5. UI `关闭CAN-A`、`关闭CAN-B`（确认框）\n')
    a('6. 立刻采样 sessions / registry / busy_can\n')
    a('7. `ensure_hardware_idle(post)` 再采样\n\n')

    a('## 关键证据（第 1 有数据轮）\n\n')
    r0 = next((r for r in rows if r.get('steps')), rows[0] if rows else {})
    steps = {s['label']: s for s in (r0.get('steps') or [])}
    ac = steps.get('after_ui_close') or {}
    ai = steps.get('after_ensure_idle') or {}
    a('```\n')
    a(f"order={r0.get('order_id')} tx_bytes={r0.get('tx_hex_len_bytes')} ui_close={r0.get('ui_close')}\n")
    a(f"busy_after_ui_close = {json.dumps(ac.get('busy_can'), ensure_ascii=False)}\n")
    a(f"sessions            = {json.dumps(ac.get('sessions'), ensure_ascii=False)}\n")
    a(f"busy_after_idle     = {json.dumps(ai.get('busy_can'), ensure_ascii=False)} idle_ok={ai.get('idle_ok')}\n")
    a('```\n\n')

    a('## 结论\n\n')
    if g_ui:
        a(f'在长指令 + **网页关 CAN** 条件下，网页关后立刻仍有 **{g_ui}/{n}** 轮 '
          f'`busy_can` 残留 `assembler=can_xl`（与上次 API close 形态一致）。'
          f'ensure_idle 后幽灵 **{g_idle}/{n}**。'
          '因此 **仍需要** 轮次/用例间 `ensure_hardware_idle`（或等价轮询 busy 至空）作兜底；'
          '仅网页关 CAN 不能消除 registry 幽灵窗口。\n')
    else:
        a(f'网页关后立刻幽灵 **0/{n}**，问题在本条件下未再出现；仍建议保留 ensure_idle 作保险。\n')

    if rows:
        a('\n## 首轮 JSON（截断）\n\n```json\n')
        a(json.dumps(r0, ensure_ascii=False, indent=2)[:8000])
        a('\n```\n')
    (out / 'REPRO.md').write_text(''.join(L), encoding='utf-8')


async def amain(rounds: int, order_id: str) -> int:
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out = HIL_ROOT / 'artifacts' / f'can_xl_ghost_busy_{stamp}'
    out.mkdir(parents=True, exist_ok=True)
    os.environ['HIL_RUN_DIR'] = str(out)
    _ = run_dir()

    api = IpcApi(CONFIG)
    api.login()
    ver = api.version()
    col = api.collector()
    meta = {
        'generated_at': _ts(),
        'frontend': CONFIG.frontend_url,
        'collector': api.collector_host or col.get('host'),
        'appVersion': (ver or {}).get('appVersion'),
        'ipc_vendor': CONFIG.ipc_can_channel(FAMILY, 'a').vendor,
        'order_id': order_id,
        'order_meta': ORDER_META.get(order_id),
        'out': str(out),
    }
    (out / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[ghost] out={out} order={order_id} collector={meta["collector"]}', flush=True)

    api.ensure_hardware_idle(reason='ghost-long-start', timeout_s=20.0)
    browser = BrowserSession(CONFIG)
    await browser.start()
    await browser.login()

    rows: list[dict[str, Any]] = []
    jsonl = out / 'rounds.jsonl'
    try:
        for i in range(1, rounds + 1):
            print(f'\n======== ghost-long round {i}/{rounds} order={order_id} @ {_ts()} ========', flush=True)
            rec = await one_round(api, browser, i, order_id)
            rows.append(rec)
            with jsonl.open('a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            flag = 'GHOST_UI' if rec.get('ghost_after_ui_close') else (
                'GHOST_IDLE' if rec.get('ghost_after_ensure_idle') else (
                    'ERR' if rec.get('error') else 'ok'))
            print(
                f"[ghost] round {i} → {flag} tx_bytes={rec.get('tx_hex_len_bytes')} "
                f"ui_close={rec.get('ui_close')} "
                f"busy={next((s.get('busy_can') for s in reversed(rec.get('steps') or []) if s.get('label')=='after_ui_close'), None)}",
                flush=True,
            )
            time.sleep(0.6)
    finally:
        try:
            await browser.close()
        except Exception:
            pass
        try:
            api.ensure_hardware_idle(reason='ghost-long-end', timeout_s=20.0)
        except Exception as exc:  # noqa: BLE001
            print(f'[ghost] end idle fail: {exc}', flush=True)

    write_repro(out, rows, meta)
    g_ui = sum(1 for r in rows if r.get('ghost_after_ui_close'))
    print(f'\n[ghost] DONE ui_ghost={g_ui}/{len(rows)} → {out / "REPRO.md"}', flush=True)
    return 0 if g_ui == 0 else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--rounds', type=int, default=40)
    ap.add_argument('--order', default=DEFAULT_ORDER, help='XL 指令 id，默认 D1651 长包')
    args = ap.parse_args()
    raise SystemExit(asyncio.run(amain(args.rounds, args.order)))


if __name__ == '__main__':
    main()
