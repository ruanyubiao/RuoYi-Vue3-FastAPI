"""工控机后端 HTTP 客户端（只用于：登录、读路由/遥测、经 /payload/device/* 打开/关闭连接）。

接口来自 ruoyi-fastapi-backend/module_payload/controller/payload_device_controller.py（前缀 /payload/device）。
连接的 source 与 cfg_device_connect.json 的键一致，页面据此显示「已连接」。

多采集机（module_payload/collector_host.py + middlewares/context_middleware.py）：
- 后端每个请求按请求头 X-Collector-Host 绑定「当前采集机」，open/close/sessions/can/vendors 等都只作用于该采集机；
  不带头时用后端配置（100.52 上为 local，且 local 不在线 → vendors 为空）。
- GET /payload/device/snapshot?hosts=...（需含 commit 2f13aeb）：返回 data.devices[]（每台含 online、canVendors、
  serialPorts、localAddrs、registry，以及内嵌 can/serialOpened/netOpened/sessions）；parts 参数已忽略。本客户端只认
  devices[]，不再兼容旧包的 collectors[]。hosts 参数不看请求头。
- 前端：utils/collectorHost.js 把选中的采集机存 localStorage「payload:collectorHost」，utils/request.js 给所有请求带
  X-Collector-Host；没选或选的不在列表时 pickCollectorHost 取 devices[0]。
本客户端同样：login 后选定采集机（HIL_IPC_HOST / hil.local.json ipc.collector_host，空则第一个 online），所有请求带该头。
"""
from __future__ import annotations

import os
from typing import Any

import requests

from hil.config import CONFIG, HILConfig


class IpcApiError(RuntimeError):
    pass


class IpcApi:
    def __init__(self, cfg: HILConfig = CONFIG) -> None:
        self.cfg = cfg
        self.s = requests.Session()
        self.token: str | None = None
        self.collector_host: str = ''

    # ------------------------------------------------------------------
    def _url(self, path: str) -> str:
        return f'{self.cfg.api_base}{path}'

    def _check(self, r: requests.Response) -> Any:
        if r.status_code != 200:
            raise IpcApiError(f'{r.request.method} {r.url} HTTP {r.status_code}: {r.text[:200]}')
        body = r.json()
        if body.get('code') not in (200, None):
            raise IpcApiError(f'{r.request.method} {r.url} code={body.get("code")} msg={body.get("msg")}')
        return body.get('data', body)

    def login(self) -> str:
        r = self.s.post(self._url('/login'), data={'username': self.cfg.username, 'password': self.cfg.password}, timeout=15)
        body = r.json() if r.ok else {}
        data = body.get('data') if isinstance(body.get('data'), dict) else {}
        self.token = body.get('token') or data.get('token')
        if not self.token:
            raise IpcApiError(f'登录失败: HTTP {r.status_code} {r.text[:200]}')
        self.s.headers['Authorization'] = f'Bearer {self.token}'
        self.select_collector()
        return self.token

    # ---- 采集机 ----
    @staticmethod
    def machines_from_snapshot(data: dict | None) -> list[dict]:
        """从 snapshot 的 data 取出采集机列表。只认 2f13aeb 起的 devices[]；没有则抛错（旧包 collectors[] 不再兼容）。"""
        if not isinstance(data, dict) or 'devices' not in data:
            keys = sorted(data.keys()) if isinstance(data, dict) else type(data).__name__
            raise IpcApiError(
                'snapshot 缺少 data.devices[]（需要工控机部署含 commit 2f13aeb「采集机状态只走 snapshot」的包）；'
                f'当前 data 键={keys}'
            )
        return [m for m in (data.get('devices') or []) if isinstance(m, dict)]

    def collectors(self) -> list[dict]:
        """全部采集机（不带 hosts = 在线目录；带 hosts 时由 collector() 点名）。只认 devices[]。"""
        # parts 已忽略，保留空参以免个别网关挑剔
        data = self._check(self.s.get(self._url('/payload/device/snapshot'), params={'parts': ''}, timeout=15))
        return self.machines_from_snapshot(data)

    def select_collector(self) -> str:
        want = self.cfg.collector_host_cfg
        machines = self.collectors()
        online = [m.get('host') for m in machines if m.get('online')]
        if want:
            if want not in online:
                raise IpcApiError(f'指定的采集机 {want} 不在线；在线采集机: {online or "无"}（全部: {[m.get("host") for m in machines]}）')
            host, src = want, ('环境变量 HIL_IPC_HOST' if os.getenv('HIL_IPC_HOST', '').strip() else 'hil.local.json ipc.collector_host')
        else:
            if not online:
                raise IpcApiError(f'工控机后端没有在线的采集机（全部: {[m.get("host") for m in machines]}），检查采集进程')
            host, src = online[0], f'自动选第一个 online 采集机（在线: {online}）'
        self.collector_host = host
        self.s.headers['X-Collector-Host'] = host
        self.cfg.set_collector(host, src)
        return host

    def collector(self) -> dict:
        """当前采集机的快照（canVendors / serialPorts / localAddrs / registry，以及 can/sessions 等）。"""
        data = self._check(self.s.get(self._url('/payload/device/snapshot'),
                                      params={'parts': '', 'hosts': self.collector_host}, timeout=15))
        for m in self.machines_from_snapshot(data):
            if m.get('host') == self.collector_host:
                return m
        return {'host': self.collector_host, 'online': False}

    def registry(self) -> list[dict]:
        return [r for r in (self.collector().get('registry') or []) if isinstance(r, dict)]

    # ---- 占用检查（只读）----
    def busy_can(self, vendor: int, dev_index: int, channels: list[int]) -> dict[int, str]:
        """registry 里已被打开的目标 CAN 通道：{ch: 描述}。"""
        out: dict[int, str] = {}
        for r in self.registry():
            if r.get('type') != 'can' or not r.get('alive', True):
                continue
            cfg = r.get('config') or {}
            if int(cfg.get('vendor', -1)) != vendor or int(cfg.get('dev_index', -1)) != dev_index:
                continue
            for ch in cfg.get('channels') or []:
                ci = int(ch.get('can_index', -1))
                if ci in channels:
                    out[ci] = (f'{r.get("deviceId")}:{ci} assembler={ch.get("assembler_id")} '
                               f'cable_flag={ch.get("cable_flag")} node_addr_to={ch.get("node_addr_to")}')
            for ci in r.get('channels') or []:
                if int(ci) in channels and int(ci) not in out:
                    out[int(ci)] = f'{r.get("deviceId")}:{ci}'
        return out

    def busy_serial(self, port: str) -> list[str]:
        out = []
        for r in self.registry():
            if r.get('type') not in ('serial', 'uart') or not r.get('alive', True):
                continue
            cfg = r.get('config') or {}
            p = str(cfg.get('port') or str(r.get('deviceId', '')).split(':')[-1])
            if p.upper() == port.upper():
                out.append(f'{r.get("deviceId")} {cfg.get("baudrate", "")}')
        return out

    def busy_net(self, local_port: int) -> list[str]:
        out = []
        for r in self.registry():
            if r.get('type') not in ('net', 'udp', 'tcp') or not r.get('alive', True):
                continue
            cfg = r.get('config') or {}
            lp = cfg.get('local_port', cfg.get('localPort'))
            if lp is None:
                try:
                    lp = int(str(r.get('deviceId', '')).rsplit(':', 1)[-1])
                except ValueError:
                    lp = None
            if lp is not None and int(lp) == int(local_port):
                out.append(str(r.get('deviceId')))
        return out

    def get(self, path: str, **params) -> Any:
        return self._check(self.s.get(self._url(path), params=params or None, timeout=15))

    def post(self, path: str, json: dict | None = None, **params) -> Any:
        return self._check(self.s.post(self._url(path), json=json, params=params or None, timeout=30))

    # ---- 只读 ----
    def routers(self) -> list[dict]:
        return self.get('/getRouters')

    def sessions(self) -> Any:
        return self.get('/payload/device/sessions')

    def version(self) -> Any:
        return self.get('/payload/device/version')

    def telemetry_table(self, table_key: str) -> Any:
        return self.get('/payload/telemetry/table', type=table_key)

    # ---- 连接（仅在启用对应硬件开关的场景里调用）----
    def open_can(self, family: str, cable: str = 'a') -> dict:
        key = f'{family}_can_{cable}'
        entry = self.cfg.device_entry(key)
        ch = self.cfg.ipc_can_channel(family, cable)
        body = {
            'vendor': ch.vendor, 'devIndex': ch.dev_index, 'canIndex': ch.can_index,
            'baudRate': int(entry.get('baudRate', ch.baud_kbps)),
            'cableFlag': 0 if cable == 'a' else 1,
            'assemblerId': entry.get('assemblerId'), 'parserId': entry.get('parserId'),
            'source': key, 'fullDuplex': entry.get('fullDuplex'),
        }
        return {'request': body, 'result': self.post('/payload/device/can/open', json=body)}

    def close_can(self, request_body: dict) -> Any:
        return self.post('/payload/device/can/close', json=request_body)

    def open_serial(self, key: str, port: str) -> dict:
        e = self.cfg.device_entry(key)
        body = {
            'port': port, 'baudrate': int(e.get('baudrate', 115200)), 'dataBits': int(e.get('dataBits', 8)),
            'stopBits': float(e.get('stopBits', 1)), 'parity': str(e.get('parity', 'N')),
            'flowControl': str(e.get('flowControl', 'none')).lower(),
            'assemblerId': e.get('assemblerId'), 'parserId': e.get('parserId'),
            'source': key, 'fullDuplex': e.get('fullDuplex'),
        }
        return {'request': body, 'result': self.post('/payload/device/serial/open', json=body)}

    def can_sessions(self, family: str) -> dict[str, str]:
        """{source: deviceId}，只取 <family>_can_a / _b（deviceId 形如 can:<vendor>:<dev>:<ch>）。"""
        out: dict[str, str] = {}
        for s in self.sessions() or []:
            src = str(s.get('source') or '')
            if s.get('srcKind') == 'can' and src in (f'{family}_can_a', f'{family}_can_b') and s.get('srcParam'):
                out[src] = str(s['srcParam'])
        return out

    def close_can_device(self, device_id: str) -> Any:
        parts = str(device_id).split(':')
        return self.close_can({'vendor': int(parts[1]), 'devIndex': int(parts[2]), 'canIndex': int(parts[3])})

    def close_serial(self, port: str) -> Any:
        return self.post('/payload/device/serial/close', port=port)

    def open_udp(self, key: str, remote_host: str, remote_port: int, local_port: int | None = None) -> dict:
        e = self.cfg.device_entry(key)
        body = {
            'proto': 'udp', 'localHost': '0.0.0.0', 'localPort': int(local_port or e.get('localPort', 66)),
            'remoteHost': remote_host, 'remotePort': int(remote_port),
            'assemblerId': e.get('assemblerId'), 'parserId': e.get('parserId'),
            'source': key, 'fullDuplex': e.get('fullDuplex'),
        }
        return {'request': body, 'result': self.post('/payload/device/net/open', json=body)}

    def close_udp(self, request_body: dict) -> Any:
        return self.post('/payload/device/net/close', json=request_body)


def find_field_rows(obj: Any) -> dict[str, dict]:
    """在 /payload/telemetry/table 的返回里找出 {字段id: 行}（结构无关的宽松查找）。"""
    out: dict[str, dict] = {}

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            if 'id' in x and ('show' in x or 'value' in x or 'hex' in x):
                out[str(x['id'])] = x
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    return out
