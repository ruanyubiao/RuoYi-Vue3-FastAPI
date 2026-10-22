"""HIL 配置：全部可用 HIL_* 环境变量覆盖。

命名约定：
- 「测试机」= 运行本目录脚本、接 USB CAN / USB-RS422 的电脑（扮演载荷/单板设备）
- 「工控机」= 部署正式包的机器（192.168.100.52），被测对象
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

# cfg_device_connect.json 中的设备键（= 前端会话 source）
CAN_FAMILIES = ('biu', 'xl', 'yj216')
SERIAL_KEYS = ('xl-camera', 'xl-camera-v17', 'xl-rkdj', 'xl-zk', 'xl-cpazx', 'yj216-rs422')
UDP_KEYS = ('xl_udp_dj',)

# ---------------- 运行输出目录：一次任务 = artifacts/<YYYYMMDD_HHMMSS>/ ----------------
ARTIFACTS_ROOT = HIL_ROOT / 'artifacts'
_run_dir: Path | None = None
_run_dir_lock = threading.Lock()


def run_dir() -> Path:
    """本次任务的输出目录（junit、截图、日志、summary 都写这里）。

    - 设了 HIL_RUN_DIR：直接用（相对路径按本目录解析）；run_hil.bat 在任务开始时生成一次并设置，
      所以 `run_hil.bat all` 的多个分组共用同一目录；
    - 没设（直接 python -m pytest）：首次调用时按当前时间建 artifacts/<YYYYMMDD_HHMMSS>/，
      并回写 HIL_RUN_DIR，本进程及其子进程后续都用同一个。
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
                while p.exists():  # 同一秒内重复启动时加后缀，避免混杂
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


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    return int(v, 0) if v not in (None, '') else default


def _env_addr(name: str, default: str) -> tuple[str, int]:
    host, _, port = os.getenv(name, default).rpartition(':')
    return host or '0.0.0.0', int(port)


def env_key(device_key: str) -> str:
    """xl-camera-v17 → XL_CAMERA_V17"""
    return device_key.upper().replace('-', '_')


@dataclass
class CanChannel:
    vendor: int
    dev_index: int
    can_index: int
    baud_kbps: int = 500

    def label(self) -> str:
        return f'vendor={self.vendor} dev={self.dev_index} ch={self.can_index}'


# ---------------- hil.local.json：硬件接线默认值（环境变量优先） ----------------
LOCAL_CFG_PATH = HIL_ROOT / 'hil.local.json'


@lru_cache
def local_cfg() -> dict:
    p = Path(os.getenv('HIL_LOCAL_CFG', '') or LOCAL_CFG_PATH)
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        print(f'[HIL] 读取 {p} 失败: {exc}')
        return {}


def _lc(*path, default=None):
    d = local_cfg()
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def _env_or(name: str, default):
    v = os.getenv(name)
    if v is None or v.strip() == '':
        return default
    return int(v, 0) if isinstance(default, int) and not isinstance(default, bool) else v.strip()


def detect_test_pc_ip(ipc_host: str) -> tuple[str, str]:
    """返回 (IP, 来源)。只做路由查询（UDP connect 不发包）+ 枚举本机地址，不向外发送任何数据。"""
    import socket

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
    return '', f'未探测到与 {ipc_host} 同网段的本机 IP（候选 {sorted(set(cands))}），请设 HIL_TEST_PC_IP'


@dataclass
class HILConfig:
    # ---- 浏览器 / 正式环境 ----
    frontend_url: str = field(default_factory=lambda: os.getenv('HIL_FRONTEND_URL', 'http://192.168.100.52:12580').rstrip('/'))
    api_prefix: str = field(default_factory=lambda: os.getenv('HIL_API_PREFIX', '/prod-api'))
    username: str = field(default_factory=lambda: os.getenv('HIL_USERNAME', 'admin'))
    password: str = field(default_factory=lambda: os.getenv('HIL_PASSWORD', 'admin123'))
    headed: bool = field(default_factory=lambda: env_bool('HIL_HEADED', True))
    slow_mo_ms: int = field(default_factory=lambda: _env_int('HIL_SLOW_MO_MS', 200))
    tm_wait_s: float = field(default_factory=lambda: float(os.getenv('HIL_TM_WAIT_S', '15')))

    # ---- 采集机（后端多采集机时按 X-Collector-Host 区分；空 = 自动选第一个 online）----
    collector_host_cfg: str = field(default_factory=lambda: os.getenv('HIL_IPC_HOST', '').strip()
                                    or str(_lc('ipc', 'collector_host', default='') or '').strip())
    # 目标 CAN/串口/UDP 已被占用时：默认失败；=1 时复用（测试结束不关闭非本次打开的设备）
    allow_busy: bool = field(default_factory=lambda: env_bool('HIL_ALLOW_BUSY', False))
    _collector: tuple[str, str] | None = field(default=None, repr=False)

    # ---- 被测设备选择（同一时刻物理上只接一个）----
    can_target: str = field(default_factory=lambda: os.getenv('HIL_CAN_TARGET', '').strip().lower())
    serial_target: str = field(default_factory=lambda: os.getenv('HIL_SERIAL_TARGET', '').strip().lower())

    # ---- 测试机 CAN（gpcan vendor: DEMO=0, USB_V502=1, USB_ALYST_PRO=2, PCIE ZLG=3）；A→a_index, B→b_index ----
    can_vendor: int = field(default_factory=lambda: _env_or('HIL_CAN_VENDOR', int(_lc('can', 'test_pc', 'vendor', default=2))))
    can_dev_index: int = field(default_factory=lambda: _env_or('HIL_CAN_DEV_INDEX', int(_lc('can', 'test_pc', 'dev_index', default=0))))
    can_a_index: int = field(default_factory=lambda: _env_or('HIL_CAN_A_INDEX', int(_lc('can', 'test_pc', 'a_index', default=0))))
    can_b_index: int = field(default_factory=lambda: _env_or('HIL_CAN_B_INDEX', int(_lc('can', 'test_pc', 'b_index', default=1))))
    # ---- 工控机 CAN（页面「新建CAN连接-A/B」里选的厂商/设备/通道）----
    ipc_can_vendor: int = field(default_factory=lambda: _env_or('HIL_IPC_CAN_VENDOR', int(_lc('can', 'ipc', 'vendor', default=3))))
    ipc_can_dev_index: int = field(default_factory=lambda: _env_or('HIL_IPC_CAN_DEV_INDEX', int(_lc('can', 'ipc', 'dev_index', default=0))))
    ipc_can_a_index: int = field(default_factory=lambda: _env_or('HIL_IPC_CAN_A_INDEX', int(_lc('can', 'ipc', 'a_index', default=0))))
    ipc_can_b_index: int = field(default_factory=lambda: _env_or('HIL_IPC_CAN_B_INDEX', int(_lc('can', 'ipc', 'b_index', default=1))))

    # ---- 串口：一对线，测试机 COM9 <-> 工控机 COM8 ----
    serial_port: str = field(default_factory=lambda: _env_or('HIL_SERIAL_PORT', str(_lc('serial', 'test_pc_port', default=''))))
    ipc_serial_port: str = field(default_factory=lambda: _env_or('HIL_IPC_SERIAL_PORT', str(_lc('serial', 'ipc_port', default=''))))

    # ---- UDP（地检板 xl_udp_dj）----
    udp_enable: bool = field(default_factory=lambda: env_bool('HIL_UDP_ENABLE', False))
    # 工控机 IP（UDP 对端、测试机 IP 探测用）；默认取 HIL_FRONTEND_URL 的主机名
    ipc_ip: str = field(default_factory=lambda: os.getenv('HIL_IPC_IP', '').strip()
                        or (urlparse(os.getenv('HIL_FRONTEND_URL', 'http://192.168.100.52:12580')).hostname or '192.168.100.52'))
    udp_ipc_port: int = field(default_factory=lambda: _env_or('HIL_UDP_IPC_PORT', int(_lc('udp', 'ipc_port', default=66))))
    udp_test_pc_port: int = field(default_factory=lambda: _env_or('HIL_UDP_TEST_PC_PORT', int(_lc('udp', 'test_pc_port', default=99))))
    _test_pc_ip: tuple[str, str] | None = field(default=None, repr=False)

    # ---- 周期 ----
    tm_period_s: float = field(default_factory=lambda: float(os.getenv('HIL_TM_PERIOD', '1.0')))

    # ---- 样本 / 配置路径（以仓库源码为准）----
    device_connect_cfg: Path = BACKEND_ROOT / 'assets' / 'config' / 'cfg_device_connect.json'
    assets_cfg_dir: Path = BACKEND_ROOT / 'assets' / 'config'
    tm_golden_path: Path = BACKEND_ROOT / 'assets' / 'data' / 'tm_golden_cases.json'
    tc_golden_path: Path = BACKEND_ROOT / 'tests' / 'data' / 'telecontrol_wire_goldens.json'
    can_recv_txt: Path = BACKEND_ROOT / 'tests' / 'data' / 'biu_can_a_can_0_0_0_20260907_recv.txt'
    reply_map_path: Path = HIL_ROOT / 'scenarios' / 'reply_map.json'

    # ------------------------------------------------------------------
    @property
    def artifacts_dir(self) -> Path:
        """本次任务输出目录（= run_dir()），截图等一律写这里。"""
        return run_dir()

    @property
    def api_base(self) -> str:
        return f'{self.frontend_url}{self.api_prefix}'

    @property
    def can_enable(self) -> bool:
        """选了被测 CAN 设备才算启用真实 CAN。"""
        return self.can_target in CAN_FAMILIES

    def device_entry(self, key: str) -> dict:
        return device_connect().get(key, {})

    def _can_baud(self, family: str, cable: str) -> int:
        return int(self.device_entry(f'{family}_can_{cable}').get('baudRate', 500))

    def can_channel(self, family: str, cable: str = 'a') -> CanChannel:
        """测试机 CAN 通道（所有设备共用）：A→can_a_index，B→can_b_index。"""
        idx = self.can_a_index if cable == 'a' else self.can_b_index
        return CanChannel(self.can_vendor, self.can_dev_index, idx, self._can_baud(family, cable))

    def ipc_can_channel(self, family: str, cable: str = 'a') -> CanChannel:
        """工控机 CAN 通道（页面 A/B 对话框里选的）：A→ipc_can_a_index，B→ipc_can_b_index。"""
        idx = self.ipc_can_a_index if cable == 'a' else self.ipc_can_b_index
        return CanChannel(self.ipc_can_vendor, self.ipc_can_dev_index, idx, self._can_baud(family, cable))

    def serial_port_for(self, key: str) -> str:
        """测试机串口：HIL_SERIAL_<KEY> 优先，否则共用 serial_port（COM9）。"""
        return os.getenv(f'HIL_SERIAL_{env_key(key)}', '').strip() or self.serial_port

    def ipc_serial_port_for(self, key: str) -> str:
        """工控机串口：HIL_IPC_SERIAL_<KEY> 优先，否则共用 ipc_serial_port（COM8）。"""
        return os.getenv(f'HIL_IPC_SERIAL_{env_key(key)}', '').strip() or self.ipc_serial_port

    def serial_params(self, key: str) -> dict:
        """按 cfg_device_connect.json 生成 pyserial 参数（工控机端经接口打开时用同一份配置）。"""
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
        """(测试机 IP, 来源)：HIL_TEST_PC_IP > hil.local.json udp.test_pc_ip > 自动探测。"""
        if self._test_pc_ip is None:
            env = os.getenv('HIL_TEST_PC_IP', '').strip()
            js = str(_lc('udp', 'test_pc_ip', default='') or '').strip()
            if env:
                self._test_pc_ip = (env, '环境变量 HIL_TEST_PC_IP')
            elif js:
                self._test_pc_ip = (js, 'hil.local.json udp.test_pc_ip')
            else:
                self._test_pc_ip = detect_test_pc_ip(self.ipc_ip)
        return self._test_pc_ip

    @property
    def test_pc_ip(self) -> str:
        return self.test_pc_ip_info()[0]

    def udp_addrs(self, key: str = 'xl_udp_dj') -> tuple[tuple[str, int], tuple[str, int]]:
        """(测试机绑定地址, 工控机地址)：测试机绑 0.0.0.0:99，发往 <工控机 IP>:66。HIL_UDP_BIND/PEER 可整体覆盖。"""
        bind = _env_addr('HIL_UDP_BIND', f'0.0.0.0:{self.udp_test_pc_port}')
        peer = _env_addr('HIL_UDP_PEER', f'{self.ipc_ip}:{self.udp_ipc_port}')
        return bind, peer

    # ---- 采集机 ----
    def set_collector(self, host: str, source: str) -> None:
        self._collector = (host, source)

    def collector_info(self) -> tuple[str, str]:
        """(采集机 host, 来源)；本进程还没连过工控机时 host 为空。"""
        return self._collector or ('', f'未解析（本分组未连接工控机；配置={self.collector_host_cfg or "自动"}）')

    def hw_summary(self) -> str:
        ip, src = self.test_pc_ip_info()
        ch, csrc = self.collector_info()
        a, b = self.can_channel('biu', 'a'), self.can_channel('biu', 'b')
        ia, ib = self.ipc_can_channel('biu', 'a'), self.ipc_can_channel('biu', 'b')
        return (f'采集机={ch or "-"}（{csrc}）  工控机 {self.frontend_url}\n'
                f'  CAN 被测={self.can_target or "未选"}  测试机 v{a.vendor}/d{a.dev_index} A=ch{a.can_index} B=ch{b.can_index}'
                f' <-> 工控机 v{ia.vendor}/d{ia.dev_index} A=ch{ia.can_index} B=ch{ib.can_index}\n'
                f'  串口 被测={self.serial_target or "未选"}  测试机 {self.serial_port or "-"} <-> 工控机 {self.ipc_serial_port or "-"}\n'
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
