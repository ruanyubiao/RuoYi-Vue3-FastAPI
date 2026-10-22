"""一组模拟器的生命周期管理（with 语句里启动，退出自动停止）。"""
from __future__ import annotations

from hil.hw.base import DeviceSim


class SimManager:
    def __init__(self) -> None:
        self.sims: dict[str, DeviceSim] = {}
        self._post_start: list = []

    def add(self, name: str, sim: DeviceSim, after_start=None) -> DeviceSim:
        self.sims[name] = sim
        if after_start:
            self._post_start.append(after_start)
        return sim

    def start(self) -> None:
        for sim in self.sims.values():
            sim.start()
        for fn in self._post_start:
            fn()

    def stop(self) -> None:
        for sim in self.sims.values():
            try:
                sim.stop()
            except Exception as exc:  # noqa: BLE001
                print(f'[HIL] stop {sim.name} 失败: {exc}')

    def __getitem__(self, name: str) -> DeviceSim:
        return self.sims[name]

    def __enter__(self) -> 'SimManager':
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
