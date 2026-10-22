"""交互式轮测：同一对线缆上依次换接设备，每个设备跑一次 pytest，结果都进同一个 artifacts/<时间戳>/。

用法（run_hil.bat round can|serial [设备...] 会调用这里）：
  python -m hil.round can                     依次 biu → xl → yj216
  python -m hil.round serial xl-camera xl-zk  只轮这两个
  python -m hil.round can --plan              不提示、不碰硬件，只打印每个设备下会 RUN/SKIP 的用例
每个设备开跑前提示「请接入 XXX 后按回车」；输入 s 跳过该设备，q 结束轮测。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time

from hil.config import CAN_FAMILIES, HIL_ROOT, SERIAL_KEYS, device_connect, run_dir

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


def main(argv: list[str]) -> int:
    plan = '--plan' in argv
    args = [a for a in argv if a != '--plan']
    if not args or args[0] not in KIND:
        print(__doc__)
        return 2
    kind, extra_targets = args[0], [a for a in args[1:] if not a.startswith('-')]
    passthru = [a for a in args[1:] if a.startswith('-')]
    marker, env_name, allowed = KIND[kind]
    targets = extra_targets or list(allowed)
    bad = [t for t in targets if t not in allowed]
    if bad:
        print(f'未知设备 {bad}，可选: {", ".join(allowed)}')
        return 2

    rd = run_dir()  # 同时回写 HIL_RUN_DIR，子进程沿用
    html = importlib.util.find_spec('pytest_html') is not None
    rc = 0
    results: list[str] = []
    for i, t in enumerate(targets, 1):
        group = f'{kind}_{t}'
        if not plan:
            ans = input(f'\n[{i}/{len(targets)}] 请接入 {_label(kind, t)} 后按回车（s=跳过，q=结束）: ').strip().lower()
            if ans == 'q':
                results.append(f'{group}: 用户结束轮测，未跑')
                break
            if ans == 's':
                results.append(f'{group}: 用户跳过')
                with open(rd / 'summary.txt', 'a', encoding='utf-8') as f:
                    f.write(f'[{group}]\n  用户跳过（{time.strftime("%Y-%m-%d %H:%M:%S")}）\n\n')
                continue
        env = dict(os.environ, **{env_name: t, 'HIL_GROUP': group, 'HIL_RUN_DIR': str(rd)})
        cmd = [sys.executable, '-m', 'pytest', '-m', marker, '-v', '-s']
        if plan:
            cmd += ['--hil-plan']
        else:
            cmd += [f'--junitxml={rd / f"junit_{group}.xml"}', f'--log-file={rd / f"pytest_{group}.log"}', '--log-file-level=INFO']
            if html:
                cmd += [f'--html={rd / f"report_{group}.html"}', '--self-contained-html']
        cmd += passthru
        print(f'\n===================== [HIL] 轮测 {group} =====================', flush=True)
        r = subprocess.call(cmd, cwd=str(HIL_ROOT), env=env)
        results.append(f'{group}: 退出码 {r}')
        if r not in (0, 5):
            rc = r
    print('\n[HIL] 轮测结果: ' + '; '.join(results))
    print(f'[HIL] 本次输出目录: {rd}')
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
