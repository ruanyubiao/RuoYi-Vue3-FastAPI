"""轮测：同一条物理线串行多个协议；每个协议单独一次 pytest，产物进同一 artifacts/<时间戳>/。

用法（run_hil.bat round / all / can|serial 无参 会走到这里）：
  python -m hil.round can                     交互：依次 biu → xl → yj216（测前全关硬件）
  python -m hil.round serial xl-camera xl-zk  交互：只跑这两项
  python -m hil.round can --auto              非交互全自动（跑配置的全部目标；all/默认用）
  python -m hil.round can --plan              不提示、不开硬件，只打印每个设备会 RUN/SKIP 及原因
交互模式每个设备开始前提示；回车继续，s 跳过该设备，q 结束轮测。
--auto / all：每个 target 之间强制 close-all + 确认 sessions/registry 清空后再开下一个。
接线：CAN A/B 公用一根；串口 COM9↔COM8 公用一对。不是换设备换线——测完一个协议必须全关再测下一个。
失败请看协议收发/黄金样例对比，不要理解成「未换线」。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time

from hil.config import CAN_FAMILIES, CONFIG, HIL_ROOT, SERIAL_KEYS, device_connect, run_dir

LABEL = {'biu': 'BIU（CAN-A/B）', 'xl': 'XL（CAN-A/B）', 'yj216': 'YJ216（CAN-A/B）'}
KIND = {
    'can': ('hil_can', 'HIL_CAN_TARGET', CAN_FAMILIES),
    'serial': ('hil_serial', 'HIL_SERIAL_TARGET', SERIAL_KEYS),
}


def _label(kind: str, t: str) -> str:
    if kind == 'can':
        return LABEL.get(t, t)
    e = device_connect().get(t, {})
    return f'{e.get("label", t)}（{t}，{e.get("baudrate")} {e.get("dataBits", 8)}{str(e.get("parity", "N"))[:1]}{e.get("stopBits", 1)}）'


def _default_targets(kind: str) -> tuple[str, ...]:
    if kind == 'can':
        return CONFIG.default_can_targets()
    return CONFIG.default_serial_targets()


def _tip(kind: str, t: str) -> str:
    """共用线场景：提示测哪个协议，不提换线。"""
    return (
        f'开始测 {_label(kind, t)}'
        f'（CAN A/B 或串口 COM 公用；测前会全关硬件。'
        f'失败请看协议收发与黄金样例对比）'
    )


def _ensure_idle_between(reason: str) -> None:
    """每个 target 之间：登录 → close-all → 确认空。失败抛错打断轮测（环境级）。"""
    from hil.ipc_api import IpcApi, IpcApiError
    api = IpcApi(CONFIG)
    try:
        api.login()
        api.ensure_hardware_idle(reason=reason, timeout_s=10.0)
    except IpcApiError as exc:
        print(f'[HIL] 目标间隙清场失败（视为环境级，中断轮测）: {exc}', flush=True)
        raise


def main(argv: list[str]) -> int:
    plan = '--plan' in argv
    auto = '--auto' in argv
    args = [a for a in argv if a not in ('--plan', '--auto')]
    if not args or args[0] not in KIND:
        print(__doc__)
        return 2
    kind, extra_targets = args[0], [a for a in args[1:] if not a.startswith('-')]
    passthru = [a for a in args[1:] if a.startswith('-')]
    marker, env_name, allowed = KIND[kind]
    targets = extra_targets or list(_default_targets(kind))
    bad = [t for t in targets if t not in allowed]
    if bad:
        print(f'未知设备 {bad}，可选: {", ".join(allowed)}')
        return 2

    rd = run_dir()  # 同时写回 HIL_RUN_DIR，子进程继承
    html = importlib.util.find_spec('pytest_html') is not None
    rc = 0
    results: list[str] = []
    mode = '计划' if plan else ('自动轮测' if auto else '交互轮测')
    print(f'[HIL] {mode} {kind} 目标={",".join(targets)} → {rd}', flush=True)

    if not plan:
        # 首个 target 前也清场（与 pytest 内 close-all 双保险）
        try:
            _ensure_idle_between(f'before first {kind} target')
        except Exception as exc:  # noqa: BLE001
            print(f'[HIL] 首靶前清场失败: {exc}', flush=True)
            return 1

    for i, t in enumerate(targets, 1):
        group = f'{kind}_{t}'
        tip = _tip(kind, t)
        if plan:
            pass
        elif auto:
            print(f'\n[{i}/{len(targets)}] （自动）{tip}', flush=True)
            with open(rd / 'summary.txt', 'a', encoding='utf-8') as f:
                f.write(f'[{group}]\n  提示: {tip}\n')
        else:
            ans = input(f'\n[{i}/{len(targets)}] {tip} 回车继续，s=跳过，q=结束：').strip().lower()
            if ans == 'q':
                results.append(f'{group}: 用户结束轮测，未跑')
                break
            if ans == 's':
                results.append(f'{group}: 用户跳过')
                with open(rd / 'summary.txt', 'a', encoding='utf-8') as f:
                    f.write(f'[{group}]\n  用户跳过（{time.strftime("%Y-%m-%d %H:%M:%S")}）\n\n')
                continue
        env = dict(os.environ, **{env_name: t, 'HIL_GROUP': group, 'HIL_RUN_DIR': str(rd)})
        # 盖掉父进程可能带的「全量」目标号；每个子进程只认当前 target
        cmd = [sys.executable, '-m', 'pytest', '-m', marker, '-v', '-s']
        if plan:
            cmd += ['--hil-plan']
        else:
            cmd += [
                f'--junitxml={rd / f"junit_{group}.xml"}',
                f'--log-file={rd / f"pytest_{group}.log"}',
                '--log-file-level=INFO',
            ]
            if html:
                cmd += [f'--html={rd / f"report_{group}.html"}', '--self-contained-html']
        cmd += passthru
        print(f'\n===================== [HIL] 轮次 {group} =====================', flush=True)
        r = subprocess.call(cmd, cwd=str(HIL_ROOT), env=env)
        results.append(f'{group}: 退出码 {r}')
        if r not in (0, 5):
            rc = r
        # 每个 target 结束后清场；下一个开始前再确认（auto/交互都做；plan 不做）
        if not plan and i < len(targets):
            try:
                _ensure_idle_between(f'after {group} before next')
            except Exception as exc:  # noqa: BLE001
                print(f'[HIL] 目标间隙清场失败，中断: {exc}', flush=True)
                results.append(f'清场失败 after {group}: {exc}')
                return 1
            time.sleep(2)  # 顺带降低连续 login 429
    # 全部结束后再清一次
    if not plan:
        try:
            _ensure_idle_between(f'after last {kind} target')
        except Exception as exc:  # noqa: BLE001
            print(f'[HIL] 收尾清场失败: {exc}', flush=True)
            rc = rc or 1
    print('\n[HIL] 轮测完: ' + '; '.join(results))
    print(f'[HIL] 产物输出目录: {rd}')
    return rc


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
