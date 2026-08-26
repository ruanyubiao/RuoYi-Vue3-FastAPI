"""
采集进程生命周期管理器。

Windows 下 uvicorn 使用 spawn worker，不宜再嵌套 multiprocessing；
统一用 subprocess.Popen 拉起独立 Python 进程。

主进程退出时通过 Job Object / atexit / 信号尽量带走子进程（见 process_guard）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import Popen
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collectors import process_guard

_BACKEND_ROOT = Path(__file__).resolve().parents[2]  # ruoyi-fastapi-backend 根目录
_RUNNER = _BACKEND_ROOT / 'module_payload' / 'collectors' / 'runner.py'  # 子进程入口


@dataclass
class ProcessEntry:
    """一个采集子进程的登记项。"""

    device_id: str  # 进程键：串口/网口为设备 id，CAN 为卡 id
    collector_type: str  # `serial` / `can` / `net`
    process: Popen | None = None
    opened_channels: set[int] = field(default_factory=set)  # CAN 已打开通道号
    config: dict[str, Any] = field(default_factory=dict)  # 启动/热开时的配置快照


class CollectorProcessManager:
    """采集子进程生命周期：spawn、热开 CAN 通道、优雅 stop。"""

    _instance: 'CollectorProcessManager | None' = None  # 进程内单例

    def __init__(self) -> None:
        """安装退出钩子，保证主进程退出时带走子进程。"""
        self._registry: dict[str, ProcessEntry] = {}  # device_id / 卡 id -> 子进程
        # 串行化 open/close，避免 asyncio.to_thread 并发打开同一通道
        self._lifecycle_lock = threading.RLock()
        self._shutting_down = False  # True 后拒绝再 open
        process_guard.install_shutdown_hooks(self.shutdown_all)

    @classmethod
    def instance(cls) -> 'CollectorProcessManager':
        """进程内单例，供 API / lifespan 共用。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _ensure_not_shutting_down(self) -> None:
        """关闭中禁止再打开设备。"""
        if self._shutting_down:
            raise RuntimeError('服务正在关闭，无法打开设备')

    def _is_alive(self, proc: Popen | None) -> bool:
        """子进程仍在运行（poll 为 None）。"""
        return proc is not None and proc.poll() is None

    def _spawn(self, collector_type: str, device_id: str, config: dict[str, Any]) -> ProcessEntry:
        """拉起独立 Python 采集进程并登记。"""
        env = os.environ.copy()
        # 与主进程一致；切勿默认 sqlite（会加载 .env.sqlite → 本地 Redis，主进程等不到 status）
        env['APP_ENV'] = os.environ.get('APP_ENV') or 'dev'
        config_json = json.dumps(config, ensure_ascii=False)
        popen_kwargs: dict[str, Any] = {
            'args': [sys.executable, str(_RUNNER), collector_type, device_id, config_json],
            'cwd': str(_BACKEND_ROOT),
            'env': env,
        }
        if sys.platform != 'win32':
            popen_kwargs['preexec_fn'] = process_guard.unix_child_preexec
        else:
            # 独立进程组：控制台 Ctrl+C 只打到主进程，避免串口子进程半截 IO 刷堆栈
            popen_kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(**popen_kwargs)
        process_guard.assign_to_kill_job(proc)
        entry = ProcessEntry(device_id=device_id, collector_type=collector_type, process=proc, config=config)
        self._registry[device_id] = entry
        return entry

    def _push_ctrl(self, device_id: str, msg: dict[str, Any]) -> None:
        """向采集进程 Redis 控制队列推一条消息。"""
        from module_payload.collectors.redis_sync import create_sync_redis

        try:
            r = create_sync_redis()
        except Exception:
            return
        try:
            r.lpush(rk.ctrl_queue_key(device_id), json.dumps(msg, ensure_ascii=False))
        except Exception:
            pass
        finally:
            try:
                r.close()
            except Exception:
                pass

    def open_can_channel(
        self, vendor: int, dev_index: int, can_index: int, config: dict[str, Any]
    ) -> tuple[str, bool]:
        """打开 CAN 通道。返回 (channel_id, already_open)。

        同卡多通道共用一个采集进程：优先 ctrl 热开。
        热开失败时若卡上已有其它通道，只报错、不杀进程（避免把已开通道一起关掉）。
        """
        import time

        self._ensure_not_shutting_down()
        with self._lifecycle_lock:
            self._ensure_not_shutting_down()
            card_id = rk.can_card_id(vendor, dev_index)
            channel_id = rk.can_channel_id(vendor, dev_index, can_index)
            entry = self._registry.get(card_id)
            if (
                entry is not None
                and self._is_alive(entry.process)
                and can_index in entry.opened_channels
            ):
                return channel_id, True

            ch_cfg = {
                'vendor': vendor,
                'dev_index': dev_index,
                'can_index': can_index,
                **config,
            }
            # 清掉上次残留状态，避免误判 / 干扰本次等待
            self._clear_channel_status(channel_id)
            entry = self._registry.get(card_id)
            err_reuse = ''

            # 进程仍在则先尝试复用（勿用心跳误杀：open_can 阻塞期间本来就没有心跳）
            if entry is not None and self._is_alive(entry.process):
                self._push_ctrl(card_id, {'op': 'open_channel', 'can_index': can_index, 'config': ch_cfg})
                ok, err = self._wait_channel_ready(channel_id, entry.process, timeout_s=10.0)
                if ok:
                    entry.opened_channels.add(can_index)
                    self._upsert_can_channel_config(entry, ch_cfg)
                    return channel_id, False
                err_reuse = err or f'CAN{can_index} 打开失败'
                # 已有其它通道时绝不能冷启动，否则会关掉正常通道
                if entry.opened_channels:
                    raise RuntimeError(err_reuse)
                self.stop(card_id)
                time.sleep(0.5)
            elif entry is not None:
                self.stop(card_id)
                time.sleep(0.3)

            # 冷启动前清掉卡级残留 stop/status，防止新进程秒退
            self._clear_device_ipc(card_id)
            self._clear_channel_status(channel_id)
            cfg = {'vendor': vendor, 'dev_index': dev_index, 'channels': [ch_cfg]}
            entry = self._spawn('can', card_id, cfg)
            ok, err = self._wait_channel_ready(channel_id, entry.process, timeout_s=15.0)
            if not ok:
                self.stop(card_id)
                raise RuntimeError(err or err_reuse or 'CAN 通道打开失败，请检查设备是否接入')
            entry.opened_channels.add(can_index)
            self._upsert_can_channel_config(entry, ch_cfg)
            return channel_id, False

    @staticmethod
    def _upsert_can_channel_config(entry: ProcessEntry, ch_cfg: dict[str, Any]) -> None:
        """把各通道配置记入卡进程 config，供 list API 读取波特率等。"""
        cfg = entry.config if isinstance(entry.config, dict) else {}
        channels = list(cfg.get('channels') or [])
        can_index = int(ch_cfg.get('can_index', 0))
        replaced = False
        for i, old in enumerate(channels):
            if int((old or {}).get('can_index', -1)) == can_index:
                channels[i] = dict(ch_cfg)
                replaced = True
                break
        if not replaced:
            channels.append(dict(ch_cfg))
        cfg['channels'] = channels
        entry.config = cfg

    def _clear_channel_status(self, channel_id: str) -> None:
        """删通道 status，避免上次残留干扰本次等待。"""
        from module_payload.collectors.redis_sync import create_sync_redis

        r = create_sync_redis()
        try:
            r.delete(rk.status_key(channel_id))
        finally:
            r.close()

    def _clear_device_ipc(self, device_id: str) -> None:
        """清理残留 ctrl/cmd/status，避免旧 stop 指令让新进程一启动就退出。"""
        from module_payload.collectors.redis_sync import create_sync_redis

        r = create_sync_redis()
        try:
            r.delete(
                rk.status_key(device_id),
                rk.ctrl_queue_key(device_id),
                rk.cmd_queue_key(device_id),
                rk.heartbeat_key(device_id),
                f'{rk.PREFIX}:{device_id}:image:meta',
                f'{rk.PREFIX}:{device_id}:image:data',
            )
        finally:
            r.close()

    def _wait_channel_ready(
        self, channel_id: str, proc: Popen | None = None,         timeout_s: float = 15.0
    ) -> tuple[bool, str]:
        """轮询 Redis status 直到 running 或进程退出/超时。"""
        import time

        from module_payload.collectors.redis_sync import create_sync_redis, loads_json

        r = create_sync_redis()
        key = rk.status_key(channel_id)
        deadline = time.time() + timeout_s
        last_msg = ''
        last_state = ''
        try:
            while time.time() < deadline:
                if self._shutting_down:
                    return False, '服务正在关闭'
                raw = r.get(key)
                if raw:
                    data = loads_json(raw) or {}
                    state = str(data.get('state') or '')
                    last_state = state or last_state
                    last_msg = data.get('message') or last_msg
                    if state == 'running' and data.get('connected'):
                        return True, ''
                    if state == 'error':
                        return False, last_msg or '设备打开失败'
                    # stopped/closed：可能是旧进程收尾，进程仍存活时忽略
                if proc is not None and proc.poll() is not None:
                    raw = r.get(key)
                    if raw:
                        data = loads_json(raw) or {}
                        last_msg = data.get('message') or last_msg
                        last_state = str(data.get('state') or last_state)
                        if data.get('state') == 'error':
                            return False, last_msg or '设备打开失败'
                    if last_state in ('stopped', 'closed') or last_msg in ('已停止', '已关闭'):
                        return False, '采集进程异常退出（可能被残留 stop 指令关闭），请重试'
                    if last_msg:
                        return False, last_msg
                    return False, '采集进程已退出，请检查设备是否被占用或驱动异常'
                time.sleep(0.05)
            if last_msg in ('正在打开 CAN 通道…', '采集进程启动中…') or last_state == 'opening':
                return False, '设备打开超时（仍在打开中），请重试或检查 USB-CAN 是否被占用'
            return False, last_msg or '设备打开超时，请检查设备是否接入'
        finally:
            r.close()

    def close_can_channel(self, vendor: int, dev_index: int, can_index: int) -> None:
        """热关一条 CAN 通道；末通道仍保留卡进程以便下次复用。"""
        with self._lifecycle_lock:
            card_id = rk.can_card_id(vendor, dev_index)
            entry = self._registry.get(card_id)
            if not entry:
                return
            self._push_ctrl(card_id, {'op': 'close_channel', 'can_index': can_index})
            entry.opened_channels.discard(can_index)
            # 末通道关闭后保留采集进程，下次打开走 ctrl 复用，避免 3~4s 冷启动
            # 进程在 app shutdown / shutdown_all 时统一回收

    def set_can_cable(
        self,
        vendor: int,
        dev_index: int,
        can_index: int,
        *,
        node_addr_to: int | None = None,
        cable_flag: int | None = None,
    ) -> None:
        """热更新已打开通道的业务线缆参数（目标地址 / 线缆）。"""
        card_id = rk.can_card_id(vendor, dev_index)
        entry = self._registry.get(card_id)
        if entry is None or not self._is_alive(entry.process):
            raise RuntimeError('CAN 通道未打开')
        if can_index not in entry.opened_channels:
            raise RuntimeError(f'CAN 通道 {can_index} 未打开')
        msg: dict[str, Any] = {'op': 'set_cable', 'can_index': can_index}
        if node_addr_to is not None:
            msg['node_addr_to'] = int(node_addr_to)
        if cable_flag is not None:
            msg['cable_flag'] = int(cable_flag)
        self._push_ctrl(card_id, msg)

    def start_serial(self, port: str, config: dict[str, Any]) -> tuple[str, bool]:
        """打开串口。返回 (device_id, already_open)。已存活则不重启。"""
        import time

        self._ensure_not_shutting_down()
        with self._lifecycle_lock:
            self._ensure_not_shutting_down()
            device_id = rk.serial_id(port)
            entry = self._registry.get(device_id)
            if entry is not None and self._is_alive(entry.process):
                return device_id, True
            if entry is not None:
                self.stop(device_id)
                time.sleep(0.3)
            self._clear_device_ipc(device_id)
            cfg = {'port': port, **config}
            entry = self._spawn('serial', device_id, cfg)
            ok, err = self._wait_channel_ready(device_id, entry.process, timeout_s=8.0)
            if not ok:
                self.stop(device_id)
                raise RuntimeError(err or '串口打开失败，请检查端口是否被占用')
            return device_id, False

    def start_net(
        self,
        proto: str,
        local_host: str,
        local_port: int,
        config: dict[str, Any],
    ) -> tuple[str, bool]:
        """打开网络连接。返回 (device_id, already_open)。已存活则不重启。"""
        import time

        self._ensure_not_shutting_down()
        with self._lifecycle_lock:
            self._ensure_not_shutting_down()
            device_id = rk.net_id(proto, local_host, local_port)
            entry = self._registry.get(device_id)
            if entry is not None and self._is_alive(entry.process):
                return device_id, True
            if entry is not None:
                self.stop(device_id)
                time.sleep(0.3)
            self._clear_device_ipc(device_id)
            cfg = {
                'proto': proto,
                'local_host': local_host,
                'local_port': local_port,
                **config,
            }
            entry = self._spawn('net', device_id, cfg)
            ok, err = self._wait_channel_ready(device_id, entry.process, timeout_s=8.0)
            if not ok:
                self.stop(device_id)
                raise RuntimeError(err or '网络连接打开失败')
            return device_id, False

    def stop(self, device_id: str) -> None:
        """先发 `stop` 再 terminate/kill；允许被 open_* 持锁嵌套调用。"""
        # 允许被 open_* 持锁时嵌套调用（RLock）
        with self._lifecycle_lock:
            entry = self._registry.pop(device_id, None)
            if not entry:
                return
            if not self._is_alive(entry.process):
                return
            # 先礼后兵：短等优雅退出，超时立刻 terminate，避免关闭卡 2~3 秒
            try:
                self._push_ctrl(device_id, {'op': 'stop'})
            except Exception:
                pass
            try:
                entry.process.wait(timeout=0.35)
                return
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
            try:
                entry.process.terminate()
            except Exception:
                pass
            try:
                entry.process.wait(timeout=0.4)
            except subprocess.TimeoutExpired:
                try:
                    entry.process.kill()
                except Exception:
                    pass
                try:
                    entry.process.wait(timeout=0.2)
                except Exception:
                    pass
            except Exception:
                pass

    def notify_session_changed(self, device_id: str) -> None:
        """通知采集进程按最新会话重新挂载插件/绑定。"""
        self._push_ctrl(device_id, {'op': 'session_changed'})

    def apply_net_reuse_params(
        self,
        device_id: str,
        *,
        remote_host: str,
        remote_port: int,
    ) -> None:
        """复用已打开 UDP：更新登记配置与采集默认对端，并重挂本页会话（组装器/解释器）。"""
        host = str(remote_host or '').strip()
        try:
            port = int(remote_port if remote_port is not None else 0)
        except (TypeError, ValueError):
            port = 0
        with self._lifecycle_lock:
            entry = self._registry.get(device_id)
            if entry is not None:
                entry.config['remote_host'] = host
                entry.config['remote_port'] = port
        self._push_ctrl(
            device_id,
            {'op': 'session_changed', 'remote_host': host, 'remote_port': port},
        )

    def notify_reload_tm_cfg(self) -> None:
        """通知全部存活采集进程清空遥测解析器缓存（配置热重载后调用）。"""
        for device_id, entry in list(self._registry.items()):
            if not self._is_alive(entry.process):
                continue
            try:
                self._push_ctrl(device_id, {'op': 'reload_tm_cfg'})
            except Exception:
                pass

    def list_opened(self) -> list[dict[str, Any]]:
        """列出登记中的采集进程（含已死但尚未 pop 的项）。"""
        result = []
        for device_id, entry in self._registry.items():
            alive = self._is_alive(entry.process)
            result.append(
                {
                    'deviceId': device_id,
                    'type': entry.collector_type,
                    'alive': alive,
                    'channels': sorted(entry.opened_channels),
                    'config': dict(entry.config),
                }
            )
        return result

    def shutdown_all(self) -> None:
        """幂等：退出路径可能被 signal / atexit / lifespan 多次调用。"""
        self._shutting_down = True
        for device_id in list(self._registry.keys()):
            try:
                self.stop(device_id)
            except Exception:
                pass
