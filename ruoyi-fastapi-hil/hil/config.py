"""HIL 配置：全部来自 HIL_* 环境变量；默认写在包根 hil.env。

命名约定：
- 「测试机」= 跑本目录脚本、接 USB CAN / USB-RS422 的电脑（模拟载荷/地面设备）
- 「工控机」= 跑正式软件的机器（地址等见 hil.env，勿在代码里写死）
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

HIL_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = HIL_ROOT.parent
BACKEND_ROOT = REPO_ROOT / 'ruoyi-fastapi-backend'
FRONTEND_ROOT = REPO_ROOT / 'ruoyi-fastapi-frontend'
HIL_ENV_PATH = HIL_ROOT / 'hil.env'

# cfg_device_connect.json 中的设备键名 = 前端会话 source。
CAN_FAMILIES = ('biu', 'xl', 'yj216')
SERIAL_KEYS = ('xl-camera', 'xl-camera-v17', 'xl-rkdj', 'xl-zk', 'xl-cpazx', 'yj216-rs422')
UDP_KEYS = ('xl_udp_dj',)


def _load_dotenv_manual(path: Path) -> None:
    """无 python-dotenv 时的等价解析：不覆盖已存在的 os.environ。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, val = line.partition('=')
        key = key.strip()
        if not key or key in os.environ:
            continue
        val = val.strip()
        if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
            val = val[1:-1]
        else:
            val = val.split('#', 1)[0].strip()
        os.environ[key] = val


def load_hil_env() -> Path:
    """加载固定路径 HIL_ROOT/hil.env；已有同名环境变量优先（override=False）。"""
    path = HIL_ENV_PATH
    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=False)
    except ImportError:
        _load_dotenv_manual(path)
    return path


load_hil_env()

# ---------------- 本次运行目录：一次运行 = artifacts/<YYYYMMDD_HHMMSS>/ ----------------
ARTIFACTS_ROOT = HIL_ROOT / 'artifacts'
_run_dir: Path | None = None
_run_dir_lock = threading.Lock()


def run_dir() -> Path:
    """本次运行产物目录（junit、截图、日志、summary 都写这里）。

    - 已有 HIL_RUN_DIR：直接用（相对路径相对本目录）。run_hil.bat 在运行开始时通常设一次，
      保证 `run_hil.bat all` 的多组套件共用同一目录。
    - 没有（直接 python -m pytest）：首次调用时按当前时刻建 artifacts/<YYYYMMDD_HHMMSS>/，
      并回写 HIL_RUN_DIR，本进程及子进程后续都进同一目录。
    """
    global _run_dir
    with _run_dir_lock:
        if _run_dir is None:
            env = os.getenv('HIL_RUN_DIR', '').strip()
            if env:
                p = Path(env)
                _run_dir = p if p.is_absolute() else HIL_ROOT / p
            else:
                ts = time.strftime('%Y%m%d_%H%M%S')
                p, n = ARTIFACTS_ROOT / ts, 1
                while p.exists():  # 同一秒内重复运行时加后缀避免互踩
                    n += 1
                    p = ARTIFACTS_ROOT / f'{ts}_{n}'
                _run_dir = p
                os.environ['HIL_RUN_DIR'] = str(p)
            _run_dir.mkdir(parents=True, exist_ok=True)
        return _run_dir


def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None or v.strip() == '':
        return default
    return v.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name: str, default: int = 0) -> int:
    v = os.getenv(name)
    return int(v, 0) if v not in (None, '') else default


def _env_float(name: str, default: float = 0.0) -> float:
    v = os.getenv(name)
    return float(v) if v not in (None, '') else default


def _env_str(name: str, default: str = '') -> str:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip()


def _env_addr(name: str, default: str) -> tuple[str, int]:
    host, _, port = (os.getenv(name) or default).rpartition(':')
    return host or '0.0.0.0', int(port)


def env_key(device_key: str) -> str:
    """xl-camera-v17 → XL_CAMERA_V17"""
    return device_key.upper().replace('-', '_')


def _csv_keys(raw: str, allowed: tuple[str, ...]) -> tuple[str, ...]:
    """逗号/空白分隔的键列表；空串 → 全部 allowed。"""
    s = (raw or '').strip()
    if not s:
        return allowed
    keys = tuple(x.strip().lower() for x in s.replace(';', ',').split(',') if x.strip())
    filtered = tuple(k for k in keys if k in allowed)
    return filtered or allowed


@dataclass
class CanChannel:
    vendor: int
    dev_index: int
    can_index: int
    baud_kbps: int = 500

    def label(self) -> str:
        return f'vendor={self.vendor} dev={self.dev_index} ch={self.can_index}'


def detect_test_pc_ip(ipc_host: str) -> tuple[str, str]:
    """返回 (IP, 来源)。只做路由查询（UDP connect 探测）+ 枚举本机地址，不会发送任何数据。"""
    import socket

    if not ipc_host:
        return '', '工控机 IP 未配置（见 hil.env HIL_IPC_IP / HIL_FRONTEND_URL）'
    prefix = '.'.join(ipc_host.split('.')[:3]) + '.'
    cands: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((ipc_host, 9))
            cands.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        cands += [ai[4][0] for ai in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    for ip in cands:
        if ip.startswith(prefix):
            return ip, f'自动探测（与 {ipc_host} 同网段 {prefix}x）'
    return '', f'未探测到与 {ipc_host} 同网段的本机 IP（候选 {sorted(set(cands))}）；请设 HIL_TEST_PC_IP'


def _frontend_hostname() -> str:
    return urlparse(_env_str('HIL_FRONTEND_URL')).hostname or ''


@dataclass
class HILConfig:
    # ---- 浏览器 / 正式系统 ----
    frontend_url: str = field(default_factory=lambda: _env_str('HIL_FRONTEND_URL').rstrip('/'))
    api_prefix: str = field(default_factory=lambda: _env_str('HIL_API_PREFIX') or '/prod-api')
    username: str = field(default_factory=lambda: _env_str('HIL_USERNAME'))
    password: str = field(default_factory=lambda: _env_str('HIL_PASSWORD'))
    headed: bool = field(default_factory=lambda: env_bool('HIL_HEADED', True))
    slow_mo_ms: int = field(default_factory=lambda: _env_int('HIL_SLOW_MO_MS', 200))
    tm_wait_s: float = field(default_factory=lambda: _env_float('HIL_TM_WAIT_S', 15.0))

    # ---- 采集机（多采集机时用 X-Collector-Host 区分）；空 = 自动选第一个 online ----
    collector_host_cfg: str = field(default_factory=lambda: _env_str('HIL_IPC_HOST'))
    # 目标 CAN/串口/UDP 已被占用时：默认失败；=1 时继续（尽量不关非本轮打开的设备）
    allow_busy: bool = field(default_factory=lambda: env_bool('HIL_ALLOW_BUSY', False))
    _collector: tuple[str, str] | None = field(default=None, repr=False)
    version_backend: str = field(default='', repr=False)
    version_frontend: str = field(default='', repr=False)
    version_dut: str | None = field(default=None, repr=False)

    # ---- 本轮设备选择（同一时刻硬件上只测一个）----
    can_target: str = field(default_factory=lambda: _env_str('HIL_CAN_TARGET').lower())
    serial_target: str = field(default_factory=lambda: _env_str('HIL_SERIAL_TARGET').lower())

    # ---- 测试机 CAN（vendor 含义见 hil.env 注释）----
    can_vendor: int = field(default_factory=lambda: _env_int('HIL_CAN_VENDOR', 0))
    can_dev_index: int = field(default_factory=lambda: _env_int('HIL_CAN_DEV_INDEX', 0))
    can_a_index: int = field(default_factory=lambda: _env_int('HIL_CAN_A_INDEX', 0))
    can_b_index: int = field(default_factory=lambda: _env_int('HIL_CAN_B_INDEX', 1))
    # ---- 工控机 CAN（页面「新建CAN连接」-A/B 里所选厂商/设备/通道）----
    ipc_can_vendor: int = field(default_factory=lambda: _env_int('HIL_IPC_CAN_VENDOR', 0))
    ipc_can_dev_index: int = field(default_factory=lambda: _env_int('HIL_IPC_CAN_DEV_INDEX', 0))
    ipc_can_a_index: int = field(default_factory=lambda: _env_int('HIL_IPC_CAN_A_INDEX', 0))
    ipc_can_b_index: int = field(default_factory=lambda: _env_int('HIL_IPC_CAN_B_INDEX', 1))

    # ---- 串口：一对线（端口名见 hil.env）----
    serial_port: str = field(default_factory=lambda: _env_str('HIL_SERIAL_PORT'))
    ipc_serial_port: str = field(default_factory=lambda: _env_str('HIL_IPC_SERIAL_PORT'))

    # ---- UDP（关键机 xl_udp_dj）----
    udp_enable: bool = field(default_factory=lambda: env_bool('HIL_UDP_ENABLE', False))
    # 工控机 IP：默认取 HIL_IPC_IP，否则从 HIL_FRONTEND_URL 主机名推导（均无硬编码）
    ipc_ip: str = field(default_factory=lambda: _env_str('HIL_IPC_IP') or _frontend_hostname())
    udp_ipc_port: int = field(default_factory=lambda: _env_int('HIL_UDP_IPC_PORT', 66))
    udp_test_pc_port: int = field(default_factory=lambda: _env_int('HIL_UDP_TEST_PC_PORT', 99))
    _test_pc_ip: tuple[str, str] | None = field(default=None, repr=False)

    # ---- 其它 ----
    tm_period_s: float = field(default_factory=lambda: _env_float('HIL_TM_PERIOD', 1.0))

    # ---- 路径 / 资产（以本仓库源码为准）----
    device_connect_cfg: Path = BACKEND_ROOT / 'assets' / 'config' / 'cfg_device_connect.json'
    assets_cfg_dir: Path = BACKEND_ROOT / 'assets' / 'config'
    tm_golden_path: Path = BACKEND_ROOT / 'assets' / 'data' / 'tm_golden_cases.json'
    tc_golden_path: Path = BACKEND_ROOT / 'tests' / 'data' / 'telecontrol_wire_goldens.json'
    can_recv_txt: Path = BACKEND_ROOT / 'tests' / 'data' / 'biu_can_a_can_0_0_0_20260907_recv.txt'
    reply_map_path: Path = HIL_ROOT / 'scenarios' / 'reply_map.json'

    # ------------------------------------------------------------------
    @property
    def artifacts_dir(self) -> Path:
        """本次运行产物目录（= run_dir()），截图等一并写这里。"""
        return run_dir()

    @property
    def api_base(self) -> str:
        return f'{self.frontend_url}{self.api_prefix}'

    @property
    def can_enable(self) -> bool:
        """选了本轮 CAN 设备，即启用真实 CAN。"""
        return self.can_target in CAN_FAMILIES

    def device_entry(self, key: str) -> dict:
        return device_connect().get(key, {})

    def _can_baud(self, family: str, cable: str) -> int:
        return int(self.device_entry(f'{family}_can_{cable}').get('baudRate', 500))

    def can_channel(self, family: str, cable: str = 'a') -> CanChannel:
        """测试机 CAN 通道（模拟设备侧）：A→can_a_index，B→can_b_index。"""
        idx = self.can_a_index if cable == 'a' else self.can_b_index
        return CanChannel(self.can_vendor, self.can_dev_index, idx, self._can_baud(family, cable))

    def ipc_can_channel(self, family: str, cable: str = 'a') -> CanChannel:
        """工控机 CAN 通道（页面 A/B 对话框所选）：A→ipc_can_a_index，B→ipc_can_b_index。"""
        idx = self.ipc_can_a_index if cable == 'a' else self.ipc_can_b_index
        return CanChannel(self.ipc_can_vendor, self.ipc_can_dev_index, idx, self._can_baud(family, cable))

    def serial_port_for(self, key: str) -> str:
        """测试机串口：HIL_SERIAL_<KEY> 优先，否则 serial_port（见 hil.env）。"""
        return _env_str(f'HIL_SERIAL_{env_key(key)}') or self.serial_port

    def ipc_serial_port_for(self, key: str) -> str:
        """工控机串口：HIL_IPC_SERIAL_<KEY> 优先，否则 ipc_serial_port（见 hil.env）。"""
        return _env_str(f'HIL_IPC_SERIAL_{env_key(key)}') or self.ipc_serial_port

    def serial_params(self, key: str) -> dict:
        """从 cfg_device_connect.json 取出 pyserial 参数（工控机侧经接口打开时用同一套配置）。"""
        import serial

        d = self.device_entry(key)
        parity = {'N': serial.PARITY_NONE, 'O': serial.PARITY_ODD, 'E': serial.PARITY_EVEN,
                  'M': serial.PARITY_MARK, 'S': serial.PARITY_SPACE}.get(str(d.get('parity', 'N'))[:1].upper(), serial.PARITY_NONE)
        stop = {1: serial.STOPBITS_ONE, 1.5: serial.STOPBITS_ONE_POINT_FIVE, 2: serial.STOPBITS_TWO}.get(float(d.get('stopBits', 1)), serial.STOPBITS_ONE)
        flow = str(d.get('flowControl', 'NONE')).lower()
        return {
            'baudrate': int(d.get('baudrate', 115200)),
            'bytesize': int(d.get('dataBits', 8)),
            'stopbits': stop,
            'parity': parity,
            'xonxoff': flow == 'xonxoff',
            'rtscts': flow == 'rtscts',
            'dsrdtr': flow == 'dsrdtr',
        }

    # ---- UDP ----
    def test_pc_ip_info(self) -> tuple[str, str]:
        """(测试机 IP, 来源)：HIL_TEST_PC_IP > 自动探测。"""
        if self._test_pc_ip is None:
            env = _env_str('HIL_TEST_PC_IP')
            if env:
                self._test_pc_ip = (env, '环境变量 HIL_TEST_PC_IP')
            else:
                self._test_pc_ip = detect_test_pc_ip(self.ipc_ip)
        return self._test_pc_ip

    @property
    def test_pc_ip(self) -> str:
        return self.test_pc_ip_info()[0]

    def udp_addrs(self, key: str = 'xl_udp_dj') -> tuple[tuple[str, int], tuple[str, int]]:
        """(测试机绑定地址, 工控机地址)。测试机绑 0.0.0.0:<port>，对端 <工控机 IP>:<port>。HIL_UDP_BIND/PEER 可整段覆盖。"""
        bind = _env_addr('HIL_UDP_BIND', f'0.0.0.0:{self.udp_test_pc_port}')
        peer = _env_addr('HIL_UDP_PEER', f'{self.ipc_ip}:{self.udp_ipc_port}')
        return bind, peer

    # ---- 采集机 ----
    def set_collector(self, host: str, source: str) -> None:
        self._collector = (host, source)

    def collector_info(self) -> tuple[str, str]:
        """(采集机 host, 来源)。本进程还没连上工控机时 host 为空。"""
        return self._collector or ('', f'未选定（登录工控机后选择；配置={self.collector_host_cfg or "自动"}）')

    def set_versions(self, backend: str, frontend: str | None = None, dut: str | None = None) -> None:
        """记录软件版本：backend / frontend / 载荷。frontend 与 dut 可为 None（未读取）。"""
        self.version_backend = backend or ''
        self.version_frontend = '' if frontend is None else str(frontend)
        self.version_dut = None if dut is None else str(dut)

    @property
    def version_local(self) -> str:
        """兼容旧字段：等同 version_backend。"""
        return self.version_backend

    def default_can_targets(self) -> tuple[str, ...]:
        """未指定 HIL_CAN_TARGET 时要轮流覆盖的协议族。

        HIL_CAN_DEFAULT_TARGETS：逗号分隔；空/未设 = 全部 CAN_FAMILIES。
        """
        return _csv_keys(_env_str('HIL_CAN_DEFAULT_TARGETS'), CAN_FAMILIES)

    def default_can_target(self) -> str:
        """兼容：返回 default_can_targets() 的第一个。"""
        return self.default_can_targets()[0]

    def default_serial_targets(self) -> tuple[str, ...]:
        """未指定 HIL_SERIAL_TARGET 时采用的设备键；空/未设 = 全部 SERIAL_KEYS。"""
        return _csv_keys(_env_str('HIL_SERIAL_DEFAULT_TARGETS'), SERIAL_KEYS)

    def default_udp_keys(self) -> tuple[str, ...]:
        """当前 hil 范围内的 UDP/关键协议键（仅 xl_udp_dj 等）。"""
        return _csv_keys(_env_str('HIL_UDP_DEFAULT_KEYS'), UDP_KEYS)

    def resolve_hw_defaults(self) -> None:
        """补充硬件探测：只补 udp_enable，不再把 can/serial 收成单一目标。

        - 已有 HIL_*_TARGET → 已收窄（单目标）
        - CAN/串口目标为空 → 交给 skip 逻辑 / default_*_targets 全覆盖
          （run_hil.bat all / can|serial 无参 或 round --auto 会轮询每个目标）
        - UDP：未显式设 HIL_UDP_ENABLE 且能绑端口 → udp_enable=True
        """
        from hil.hw_detect import detect_udp_local

        if os.getenv('HIL_UDP_ENABLE') is None or os.getenv('HIL_UDP_ENABLE', '').strip() == '':
            ok, _ = detect_udp_local()
            if ok:
                self.udp_enable = True

    def hw_summary(self) -> str:
        ip, src = self.test_pc_ip_info()
        ch, csrc = self.collector_info()
        a, b = self.can_channel('biu', 'a'), self.can_channel('biu', 'b')
        ia, ib = self.ipc_can_channel('biu', 'a'), self.ipc_can_channel('biu', 'b')
        return (f'采集机={ch or "-"}（{csrc}）  工控机 {self.frontend_url}\n'
                f'  CAN 本轮={self.can_target or ("默认全部:"+"/".join(self.default_can_targets()))}  测试机 v{a.vendor}/d{a.dev_index} A=ch{a.can_index} B=ch{b.can_index}'
                f' <-> 工控机 v{ia.vendor}/d{ia.dev_index} A=ch{ia.can_index} B=ch{ib.can_index}\n'
                f'  串口 本轮={self.serial_target or ("默认全部:" + "/".join(self.default_serial_targets()) if self.serial_port else "未选")}  测试机 {self.serial_port or "-"} <-> 工控机 {self.ipc_serial_port or "-"}\n'
                f'  UDP 启用={self.udp_enable}  测试机 IP={ip or "-"}（{src}）:{self.udp_test_pc_port} <-> 工控机 {self.ipc_ip}:{self.udp_ipc_port}')


@lru_cache
def device_connect() -> dict:
    p = BACKEND_ROOT / 'assets' / 'config' / 'cfg_device_connect.json'
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception as exc:  # noqa: BLE001
        print(f'[HIL] 读取 {p} 失败: {exc}')
        return {}


CONFIG = HILConfig()
