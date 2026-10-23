"""工控机侧 HTTP 客户端：只读查询、登录、开/关 CAN/串口/UDP（走 /payload/device/*）。

接口对齐 ruoyi-fastapi-backend/module_payload/controller/payload_device_controller.py（前缀 /payload/device）。
连接的 source 与 cfg_device_connect.json 文件一致（页面据此显示「已连接」）。

多采集机（module_payload/collector_host.py + middlewares/context_middleware.py）：
- 带 X-Collector-Host 绑定「当前采集机」；open/close/sessions/can/vendors 等都只作用在该采集机。
  无该头时用后端默认（100.52 常为 local）；local 无硬件 ⇒ vendors 为空。
- GET /payload/device/snapshot?hosts=...（躬 commit 2f13aeb）返回 data.devices[]，每台含 online、canVendors、
  serialPorts、localAddrs、registry，以及嵌套 can/serialOpened/netOpened/sessions（parts 可裁剪）。本客户端只认
  devices[]，不再兼容旧版 collectors[]；hosts 筛选等价于请求头。
- 前端：utils/collectorHost.js 把选中的采集机存 localStorage（payload:collectorHost）；utils/request.js 自动加
  X-Collector-Host；没选或选的不在列表时 pickCollectorHost 取 devices[0]。
本客户端同理：login 后选采集机（HIL_IPC_HOST / hil.local.json ipc.collector_host，或第一个 online），之后请求带该头。
"""
from __future__ import annotations

import os
import time
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
        """登录；遇 429（请求过于频繁）指数退避重试，避免 --auto 连开多进程时失败。"""
        last_err = ''
        for attempt in range(8):
            r = self.s.post(
                self._url('/login'),
                data={'username': self.cfg.username, 'password': self.cfg.password},
                timeout=15,
            )
            body = r.json() if r.headers.get('content-type', '').startswith('application/json') or r.ok else {}
            try:
                body = r.json()
            except Exception:  # noqa: BLE001
                body = {}
            code = body.get('code')
            if r.status_code == 429 or code == 429:
                wait = min(2 ** attempt, 20)
                last_err = f'HTTP {r.status_code} {r.text[:200]}'
                print(f'[HIL] 登录 429，{wait}s 后重试 ({attempt + 1}/8)', flush=True)
                time.sleep(wait)
                continue
            data = body.get('data') if isinstance(body.get('data'), dict) else {}
            self.token = body.get('token') or data.get('token')
            if not self.token:
                last_err = f'HTTP {r.status_code} {r.text[:200]}'
                # 非 429 的瞬时失败也稍等再试一次
                if attempt < 2 and r.status_code >= 500:
                    time.sleep(2)
                    continue
                raise IpcApiError(f'登录失败: {last_err}')
            self.s.headers['Authorization'] = f'Bearer {self.token}'
            self.select_collector()
            return self.token
        raise IpcApiError(f'登录失败(多次 429): {last_err}')

    # ---- 采集机 ----
    @staticmethod
    def machines_from_snapshot(data: dict | None) -> list[dict]:
        """从 snapshot 的 data 取采集机列表；只要 2f13aeb 后的 devices[]，没有再做旧版 collectors[] 兜底。"""
        if not isinstance(data, dict) or 'devices' not in data:
            keys = sorted(data.keys()) if isinstance(data, dict) else type(data).__name__
            raise IpcApiError(
                'snapshot 缺少 data.devices[]（需要工控机后端 commit 2f13aeb；采集机状态只走 snapshot）。'
                f'当前 data 键={keys}'
            )
        return [m for m in (data.get('devices') or []) if isinstance(m, dict)]

    def collectors(self) -> list[dict]:
        """全部采集机摘要。hosts = 空则目录；带 hosts 时用 collector() 看单机。只认 devices[]。"""
        data = self._check(self.s.get(self._url('/payload/device/snapshot'), params={'parts': ''}, timeout=15))
        return self.machines_from_snapshot(data)

    def select_collector(self) -> str:
        want = self.cfg.collector_host_cfg
        machines = self.collectors()
        online = [m.get('host') for m in machines if m.get('online')]
        if want:
            if want not in online:
                raise IpcApiError(f'指定的采集机 {want} 不在线（在线采集机: {online or "无"}；全部: {[m.get("host") for m in machines]}）')
            host, src = want, ('环境变量 HIL_IPC_HOST' if os.getenv('HIL_IPC_HOST', '').strip() else 'hil.local.json ipc.collector_host')
        else:
            if not online:
                raise IpcApiError(f'工控机侧没有在线的采集机（全部: {[m.get("host") for m in machines]}）。请开采集机。')
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
        """registry 中已打开的目标 CAN 通道：{ch: 描述}。"""
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

    def open_can_passthrough(self, cable: str = 'a', family: str = 'biu') -> dict:
        """Homepage-style raw CAN: assembler=passthrough, parser=none (no protocol bind)."""
        ch = self.cfg.ipc_can_channel(family, cable)
        body = {
            'vendor': ch.vendor, 'devIndex': ch.dev_index, 'canIndex': ch.can_index,
            'baudRate': int(getattr(ch, 'baud_kbps', 1000) or 1000),
            'cableFlag': 0 if cable == 'a' else 1,
            'assemblerId': 'passthrough', 'parserId': 'none',
            'source': f'hil_passthrough_can_{cable}', 'fullDuplex': True,
        }
        return {'request': body, 'result': self.post('/payload/device/can/open', json=body)}

    def open_serial_passthrough(self, port: str | None = None) -> dict:
        """Homepage-style raw serial: assembler=passthrough, no parser."""
        port = port or self.cfg.ipc_serial_port
        body = {
            'port': port, 'baudrate': 115200, 'dataBits': 8,
            'stopBits': 1, 'parity': 'N', 'flowControl': 'none',
            'assemblerId': 'passthrough', 'parserId': '',
            'source': 'hil_passthrough_serial', 'fullDuplex': True,
        }
        return {'request': body, 'result': self.post('/payload/device/serial/open', json=body)}


    def close_can(self, request_body: dict) -> Any:
        return self.post('/payload/device/can/close', json=request_body)

    def open_serial(self, key: str, port: str) -> dict:
        e = self.cfg.device_entry(key)
        body = {
            'port': port, 'baudrate': int(e.get('baudrate', 115200)), 'dataBits': int(e.get('dataBits', 8)),
            'stopBits': float(e.get('stopBits', 1)), 'parity': str(e.get('parity', 'N')),
            'flowControl': str(e.get('flowControl', 'none')).lower(),
            'assemblerId': e.get('assemblerId'),
            'parserId': ('' if str(e.get('parserId') or '').strip().lower() == 'none' else e.get('parserId')),
            'source': key, 'fullDuplex': e.get('fullDuplex'),
        }
        return {'request': body, 'result': self.post('/payload/device/serial/open', json=body)}

    def start_camera(self, port: str, resolution: str, *, image_no: int = 1,
                     once: bool = True, board: str = "camera") -> dict:
        """POST /payload/camera/start (image serial must already be open)."""
        body = {
            "port": port,
            "resolution": resolution,
            "imageNo": int(image_no),
            "once": bool(once),
            "board": board,
        }
        return {"request": body, "result": self.post("/payload/camera/start", json=body)}

    def stop_camera(self, port: str) -> Any:
        return self.post("/payload/camera/stop", port=port)

    def get_camera_image(self, port: str, since: str = "") -> dict:
        """GET /payload/camera/image → data.image / data.status."""
        return self.get("/payload/camera/image", port=port, since=since or "")


    def can_sessions(self, family: str) -> dict[str, str]:
        """{source: deviceId}，只含 <family>_can_a / _b（deviceId 形如 can:<vendor>:<dev>:<ch>）。"""
        out: dict[str, str] = {}
        for s in self.sessions() or []:
            src = str(s.get('source') or '')
            if s.get('srcKind') == 'can' and src in (f'{family}_can_a', f'{family}_can_b') and s.get('srcParam'):
                out[src] = str(s['srcParam'])
        return out

    def close_can_device(self, device_id: str) -> Any:
        """API 关 CAN：仅供 idle/registry 兜底；用例显式关闭用 can_ui_close。"""
        parts = str(device_id).split(':')
        return self.close_can({'vendor': int(parts[1]), 'devIndex': int(parts[2]), 'canIndex': int(parts[3])})

    def close_serial(self, port: str) -> Any:
        """API 关串口：仅供 idle/registry 兜底；用例显式关闭用 serial_ui_close。"""
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
        """API 关 UDP：仅供 idle/registry 兜底；用例显式关闭用 udp_ui_close。"""
        return self.post('/payload/device/net/close', json=request_body)

    def _force_close_registry_leftovers(self) -> list[str]:
        """close-all 有时 sessions=[] 但 registry 仍 alive（上一用例 UI 关后幽灵占用）。按 registry 强制关。"""
        closed: list[str] = []
        for r in list(self.registry()):
            if not r.get('alive', True):
                continue
            typ = str(r.get('type') or '')
            did = str(r.get('deviceId') or '')
            cfg = r.get('config') or {}
            try:
                if typ == 'can' and did.startswith('can:'):
                    parts = did.split(':')
                    indices: list[int] = []
                    if len(parts) >= 4:
                        indices = [int(parts[3])]
                        vendor, dev = int(parts[1]), int(parts[2])
                    elif len(parts) == 3:
                        vendor, dev = int(parts[1]), int(parts[2])
                        for ch in cfg.get('channels') or []:
                            indices.append(int(ch.get('can_index', -1)))
                        for ci in r.get('channels') or []:
                            indices.append(int(ci))
                        indices = [i for i in dict.fromkeys(indices) if i >= 0]
                    else:
                        continue
                    for ci in indices:
                        self.close_can({'vendor': vendor, 'devIndex': dev, 'canIndex': ci})
                        closed.append(f'can:{vendor}:{dev}:{ci}')
                elif typ in ('serial', 'uart'):
                    port = str(cfg.get('port') or did.split(':')[-1])
                    if port:
                        self.close_serial(port)
                        closed.append(f'serial:{port}')
                elif typ in ('net', 'udp', 'tcp'):
                    proto = cfg.get('proto') or (typ if typ in ('udp', 'tcp') else 'udp')
                    body = {
                        'proto': proto,
                        'localHost': cfg.get('local_host') or cfg.get('localHost') or '0.0.0.0',
                        'localPort': int(cfg.get('local_port') or cfg.get('localPort') or 0),
                        'remoteHost': cfg.get('remote_host') or cfg.get('remoteHost') or '',
                        'remotePort': int(cfg.get('remote_port') or cfg.get('remotePort') or 0),
                    }
                    if body['localPort']:
                        self.close_udp(body)
                        closed.append(did or f"net:{body['localPort']}")
            except Exception as exc:  # noqa: BLE001
                print(f'[HIL] 强制关闭残留 {typ} {did} 失败: {exc}', flush=True)
        return closed

    

    # ---- 调试·数据模拟 /payload/telemetry/dev/* ----
    def telemetry_dev_samples(self, assembler_id: str = 'passthrough', parser_id: str = 'tm_can_biu') -> Any:
        """GET /payload/telemetry/dev/samples"""
        return self._check(
            self.s.get(
                self._url('/payload/telemetry/dev/samples'),
                params={'assemblerId': assembler_id, 'parserId': parser_id},
                timeout=15,
            )
        )

    def telemetry_dev_sample(
        self,
        *,
        key: str = '',
        assembler_id: str = '',
        parser_id: str = '',
    ) -> Any:
        """GET /payload/telemetry/dev/sample"""
        params: dict[str, str] = {}
        if key:
            params['key'] = key
        if assembler_id:
            params['assemblerId'] = assembler_id
        if parser_id:
            params['parserId'] = parser_id
        return self._check(
            self.s.get(self._url('/payload/telemetry/dev/sample'), params=params, timeout=15)
        )

    def telemetry_dev_pipeline(
        self,
        hex_text: str,
        assembler_id: str = 'passthrough',
        parser_id: str = 'tm_can_biu',
    ) -> Any:
        """POST /payload/telemetry/dev/pipeline"""
        return self._check(
            self.s.post(
                self._url('/payload/telemetry/dev/pipeline'),
                json={'hex': hex_text, 'assemblerId': assembler_id, 'parserId': parser_id},
                timeout=30,
            )
        )

    def telemetry_dev_can_yc(self, hex_text: str) -> Any:
        """POST /payload/telemetry/dev/can-yc"""
        return self._check(
            self.s.post(
                self._url('/payload/telemetry/dev/can-yc'),
                json={'hex': hex_text},
                timeout=30,
            )
        )


    # ---- 调试·配置文件 / 遥测计算 ----
    def config_files_list(self) -> list:
        data = self._check(self.s.get(self._url('/payload/config-files/list'), timeout=30))
        return data if isinstance(data, list) else (data or {}).get('list') or []

    def config_file_content(self, name: str) -> dict:
        return self._check(
            self.s.get(self._url('/payload/config-files/content'), params={'name': name}, timeout=60)
        )

    def config_files_reload(self, name: str | None = None) -> Any:
        params = {'name': name} if name else None
        return self._check(
            self.s.post(self._url('/payload/config-files/reload'), params=params, timeout=120)
        )

    def telemetry_pages(self) -> list:
        data = self._check(self.s.get(self._url('/payload/telemetry/config'), timeout=30))
        return (data or {}).get('page') or []

    def telemetry_def(self, table_type: str) -> dict:
        return self._check(
            self.s.get(self._url('/payload/telemetry/def'), params={'type': table_type}, timeout=30)
        )

    def telemetry_calc(self, *, table_type: str, field: str, hex_text: str, pad_tail: bool = True) -> Any:
        return self._check(
            self.s.post(
                self._url('/payload/telemetry/calc'),
                json={'type': table_type, 'field': field, 'hex': hex_text, 'padTail': pad_tail},
                timeout=30,
            )
        )

    def ensure_hardware_idle(self, *, reason: str = '', timeout_s: float = 8.0) -> None:
        """清场兜底（API）：close-all + 强制清 registry，轮询至 sessions 空且无 alive。

        用例主路径关设备应优先网页（can_ui_close / serial_ui_close / udp_ui_close）；
        本方法仅用于靶间/用例前后清场与幽灵占用兜底，不要当作「面向用户的关设备」步骤。
        共用 CAN/串口线场景下，每个协议测完/测下一个之前必须调用。
        """
        self.close_all(reason=reason or 'ensure idle')
        deadline = time.monotonic() + timeout_s
        last_sess: Any = None
        last_alive: list = []
        while time.monotonic() < deadline:
            try:
                last_sess = list(self.sessions() or [])
            except Exception as exc:  # noqa: BLE001
                print(f'[HIL] ensure_idle 读 sessions 失败: {exc}', flush=True)
                last_sess = None
            try:
                last_alive = [r for r in self.registry() if r.get('alive', True)]
            except Exception as exc:  # noqa: BLE001
                print(f'[HIL] ensure_idle 读 registry 失败: {exc}', flush=True)
                last_alive = [{'error': str(exc)}]
            if last_sess == [] and last_alive == []:
                print(f'[HIL] ensure_idle OK（{reason or "-"}）sessions=[] registry alive=[]', flush=True)
                return
            # 再扫一次残留
            self._force_close_registry_leftovers()
            time.sleep(0.4)
        detail = f'sessions={last_sess!r} alive={[ (r.get("type"), r.get("deviceId")) for r in last_alive ]}'
        raise IpcApiError(f'ensure_hardware_idle 超时（{timeout_s}s，{reason}）：仍未清空。{detail}')

    def close_all(self, *, reason: str = '') -> Any:
        """清场兜底 API：POST /payload/device/close-all（当前 X-Collector-Host）。

        用例显式关设备请走网页；本接口供 ensure_hardware_idle / 靶间清场调用。
        会关掉该采集机上已打开的 CAN/串口/UDP，包括用户手动打开的连接。
        若 close-all 回报空但 registry 仍有 alive，再按 registry 强制关（修 UI 关后幽灵占用）。
        404 时打日志并返回 None；其它错误打日志后抛出。
        """
        tag = f'（{reason}）' if reason else ''
        host = self.collector_host or '-'
        try:
            result = self.post('/payload/device/close-all', json={})
            print(f'[HIL] close-all{tag} 采集机={host} 结果={result}', flush=True)
        except IpcApiError as exc:
            msg = str(exc)
            if 'HTTP 404' in msg or 'code=404' in msg:
                print(f'[HIL] close-all{tag} 接口不存在(404)，跳过：采集机={host} {exc}', flush=True)
                result = None
            else:
                print(f'[HIL] close-all{tag} 失败：采集机={host} {exc}', flush=True)
                raise
        # sessions 仍非空时再逐条关
        try:
            for s in list(self.sessions() or []):
                kind = str(s.get('srcKind') or '')
                param = str(s.get('srcParam') or '')
                try:
                    if kind == 'can' and param.startswith('can:'):
                        self.close_can_device(param)
                    elif kind in ('serial', 'uart') and param:
                        port = param if not param.startswith('serial:') else param.split(':', 1)[-1]
                        self.close_serial(port)
                except Exception as exc:  # noqa: BLE001
                    print(f'[HIL] close-all 补关 session {kind}:{param} 失败: {exc}', flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f'[HIL] close-all 列举 sessions 失败: {exc}', flush=True)
        forced = self._force_close_registry_leftovers()
        if forced:
            print(f'[HIL] close-all{tag} registry 强制关闭: {forced}', flush=True)
            time.sleep(0.5)
        return result


def find_field_rows(obj: Any) -> dict[str, dict]:
    """从 /payload/telemetry/table 的返回里找出 {字段id: 行}（结构无关的宽松查找）。"""
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
