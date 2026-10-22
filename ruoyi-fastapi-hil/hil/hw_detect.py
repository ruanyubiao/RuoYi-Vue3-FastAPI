"""本机硬件只读/安全探测（不发遥控、不测协议）。

用于决定 hil_can / hil_serial / hil_udp 默认是否启用：
检测到配置的本机资源 → 启用（可再被 HIL_*_TARGET 收窄）；
检测不到 → skip，原因写「本机未检测到 …」。
"""
from __future__ import annotations

import socket
from functools import lru_cache

from hil.config import CONFIG


@lru_cache(maxsize=1)
def detect_can_local() -> tuple[bool, str]:
    """探测 hil.local.json 配置的测试机 CAN（默认 Alyst Pro vendor=2）。

    优先 Windows PnP 枚举（VID_04D8 = Alyst/ControlCAN 常用，只读不 open）；
    PnP 无结果时再安全试开：gpcan open_can → 立刻 close_can（不发送）。
    gpcan 约定：CAN_RET_CODE_OK=1，ERR=0。
    """
    vendor = int(CONFIG.can_vendor)
    dev = int(CONFIG.can_dev_index)
    pnp = _pnp_hint_can()
    if isinstance(pnp, str) and pnp:
        return True, f'PnP 已见到本机 CAN/WinUSB：{pnp}（配置 vendor={vendor} dev={dev}）'
    # PnP 无命中或非 Windows：尝试安全 open/close
    try:
        import gpcan
        from hil.protocol.can_device import gpcan_available
        ok, err = gpcan_available()
        if not ok:
            hint = f'；PnP=无' if pnp is False else ''
            return False, f'gpcan 不可用: {err}{hint}'
        param = gpcan.CanCardParam(
            n_can_index=int(CONFIG.can_a_index),
            n_baud_rate=500,
            n_dev_index=dev,
        )
        client = gpcan.CanSdkClient(vendor, param)
        ret = int(client.open_can())
        ok_code = int(getattr(gpcan.CanRetCode, 'CAN_RET_CODE_OK', 1))
        try:
            if ret != ok_code:
                err = client.get_last_error() or f'ret={ret}（OK={ok_code}）'
                hint = f'；PnP={pnp}' if pnp is not None else ''
                return False, f'打开失败 vendor={vendor} dev={dev}: {err}{hint}'
            return True, f'已探测到 CAN vendor={vendor} dev={dev}（安全 open/close）'
        finally:
            try:
                client.close_can()
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        hint = f'；PnP={pnp}' if pnp is not None else ''
        return False, f'CAN 探测异常 vendor={vendor} dev={dev}: {exc}{hint}'


def _pnp_hint_can() -> str | bool | None:
    """Windows 下用 PowerShell 扫 PnP；非 Windows 返回 None。

    Alyst Pro / ControlCAN 常见 USB ID：VID_04D8（Microchip）+ WinUSB。
    """
    import platform
    import subprocess
    if platform.system() != 'Windows':
        return None
    try:
        ps = (
            "Get-PnpDevice -Present -ErrorAction SilentlyContinue | "
            "Where-Object { "
            "  ($_.InstanceId -match 'VID_04D8') -or "
            "  ($_.FriendlyName -match 'CAN|Alyst|USBCAN') -or "
            "  ($_.FriendlyName -eq 'WinUSB Device' -and $_.InstanceId -match 'VID_04D8') "
            "} | Select-Object FriendlyName, InstanceId | "
            "ForEach-Object { $_.FriendlyName + ' [' + $_.InstanceId + ']' }"
        )
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps],
            capture_output=True, text=True, timeout=8,
        )
        names = [ln.strip() for ln in (r.stdout or '').splitlines() if ln.strip()]
        if not names:
            return False
        return ', '.join(names[:5])
    except Exception:  # noqa: BLE001
        return None


@lru_cache(maxsize=1)
def detect_serial_local() -> tuple[bool, str]:
    """本机是否存在配置的测试机串口（默认 COM9）。"""
    port = (CONFIG.serial_port or '').strip()
    if not port:
        return False, '未配置测试机串口（hil.local.json serial.test_pc_port / HIL_SERIAL_PORT）'
    try:
        from serial.tools import list_ports
        ports = {p.device.upper(): p for p in list_ports.comports()}
    except Exception as exc:  # noqa: BLE001
        return False, f'无法枚举串口: {exc}'
    key = port.upper()
    if key in ports:
        desc = getattr(ports[key], 'description', '') or ''
        return True, f'已探测到 {port}' + (f'（{desc}）' if desc else '')
    have = ', '.join(sorted(ports)) or '无'
    return False, f'本机没有 {port}（当前: {have}）'


@lru_cache(maxsize=1)
def detect_udp_local() -> tuple[bool, str]:
    """能否绑定测试机 UDP 端口（默认 99）；能绑即认为本机 UDP 条件具备。"""
    port = int(CONFIG.udp_test_pc_port)
    ip, src = CONFIG.test_pc_ip_info()
    if not ip:
        return False, f'测试机 IP 未知（{src}）'
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('0.0.0.0', port))
        return True, f'已能绑定 0.0.0.0:{port}（对端将用 {ip}）'
    except OSError as exc:
        return False, f'无法绑定 UDP {port}: {exc}'
    finally:
        try:
            sock.close()
        except OSError:
            pass


def clear_detect_cache() -> None:
    detect_can_local.cache_clear()
    detect_serial_local.cache_clear()
    detect_udp_local.cache_clear()
