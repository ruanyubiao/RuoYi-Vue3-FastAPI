"""模拟器抽象：start/stop、on_rx 回调、定时遥测、收包等待。"""
from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

RxCallback = Callable[['DeviceSim', Any], None]
_log_lock = threading.Lock()


def sim_log_write(line: str) -> None:
    """模拟器收发日志追加到 <运行目录>/sim_io.log。"""
    from hil.config import run_dir

    try:
        with _log_lock, open(run_dir() / 'sim_io.log', 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


class DeviceSim(ABC):
    name = 'device'

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._rx_callbacks: list[RxCallback] = []
        self._rx_cond = threading.Condition()
        self.rx_items: list[Any] = []
        self.rx_count = 0
        self.tx_count = 0
        self.started = False

    def log(self, msg: str) -> None:
        line = f'[{time.strftime("%H:%M:%S")}][{self.name}] {msg}'
        print(line, flush=True)
        sim_log_write(line)

    def on_rx(self, cb: RxCallback) -> None:
        self._rx_callbacks.append(cb)

    def _emit_rx(self, item: Any) -> None:
        with self._rx_cond:
            self.rx_count += 1
            self.rx_items.append(item)
            self._rx_cond.notify_all()
        for cb in self._rx_callbacks:
            try:
                cb(self, item)
            except Exception as exc:  # noqa: BLE001
                self.log(f'on_rx 回调异常: {exc}')

    def wait_for(self, pred: Callable[[Any], bool], timeout: float = 10.0) -> Any | None:
        """等待一条满足 pred 的已收条目（含历史），超时返回 None。"""
        deadline = time.monotonic() + timeout
        seen = 0
        with self._rx_cond:
            while True:
                for item in self.rx_items[seen:]:
                    if pred(item):
                        return item
                seen = len(self.rx_items)
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self._rx_cond.wait(left)

    def _spawn(self, target: Callable[[], None], name: str) -> None:
        t = threading.Thread(target=target, name=f'{self.name}-{name}', daemon=True)
        t.start()
        self._threads.append(t)

    def schedule_telemetry(self, period_s: float, frames: list[Any] | Callable[[], list[Any]]) -> None:
        """后台线程按周期发送；frames 可为固定列表或每周期调用一次的函数。"""

        def loop() -> None:
            while not self._stop.is_set():
                batch = frames() if callable(frames) else frames
                for fr in batch or []:
                    if self._stop.is_set():
                        return
                    try:
                        self.send_frame(fr)
                        self.tx_count += 1
                    except Exception as exc:  # noqa: BLE001
                        self.log(f'遥测发送失败: {exc}')
                self._stop.wait(period_s)

        self._spawn(loop, 'tm')

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def send_frame(self, frame: Any) -> None: ...

    def rx_loop(self) -> None:  # 子类覆写
        return

    def start(self) -> None:
        self._stop.clear()
        self.open()
        self._spawn(self.rx_loop, 'rx')
        self.started = True
        self.log('started')

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)
        self._threads.clear()
        try:
            self.close()
        finally:
            self.started = False
            self.log(f'stopped (rx={self.rx_count}, tx={self.tx_count})')
