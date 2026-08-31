"""_try_session_ingest 热路径分段计时：定位 8ms 地板，回归优化后上限。"""

from __future__ import annotations

import time
from collections import defaultdict
from unittest.mock import MagicMock

import pytest

from module_payload.collectors.base_collector import BaseCollector
from module_payload.constants import PARSER_TM_XL_CAMERA, SRC_KIND_SERIAL
from module_payload.parsers.xl_camera_tm import D8_DATA_LEN, FRAME_HEADER, FRAME_TYPE_D8, _calc_checksum

N_WARM = 5
N_RUN = 40


class _CmdRedis:
    """记录命令次数；可选模拟本机 Redis RTT。"""

    def __init__(self, rtt_s: float = 0.0) -> None:
        self.store: dict[str, object] = {}
        self.lists: dict[str, list] = defaultdict(list)
        self.calls: list[str] = []
        self.rtt_s = rtt_s

    def _rtt(self) -> None:
        if self.rtt_s:
            time.sleep(self.rtt_s)

    def get(self, key: str) -> object | None:
        self.calls.append('GET')
        self._rtt()
        return self.store.get(key)

    def set(self, key: str, value: object, *a, **k) -> None:
        self.calls.append('SET')
        self._rtt()
        self.store[key] = value

    def lpush(self, key: str, value: object) -> None:
        self.calls.append('LPUSH')
        self._rtt()
        self.lists[key].insert(0, value)

    def ltrim(self, key: str, start: int, end: int) -> None:
        self.calls.append('LTRIM')
        self._rtt()
        self.lists[key] = self.lists[key][start : end + 1]

    def pipeline(self, transaction: bool = False) -> '_Pipe':
        return _Pipe(self)


class _Pipe:
    def __init__(self, r: _CmdRedis) -> None:
        self._r = r
        self._ops: list[tuple] = []

    def set(self, *a, **k) -> '_Pipe':
        self._ops.append(('set', a, k))
        return self

    def lpush(self, *a, **k) -> '_Pipe':
        self._ops.append(('lpush', a, k))
        return self

    def ltrim(self, *a, **k) -> '_Pipe':
        self._ops.append(('ltrim', a, k))
        return self

    def zadd(self, *a, **k) -> '_Pipe':
        self._ops.append(('zadd', a, k))
        return self

    def zremrangebyrank(self, *a, **k) -> '_Pipe':
        self._ops.append(('zremrangebyrank', a, k))
        return self

    def execute(self) -> list:
        self._r.calls.append(f'PIPE:{len(self._ops)}')
        self._r._rtt()
        for name, a, k in self._ops:
            if name == 'set':
                self._r.store[a[0]] = a[1]
            elif name == 'lpush':
                self._r.lists[a[0]].insert(0, a[1])
            elif name == 'ltrim':
                self._r.lists[a[0]] = self._r.lists[a[0]][a[1] : a[2] + 1]
        return []


def _d8_frame() -> bytes:
    data = bytes(D8_DATA_LEN)
    body = bytes(
        [
            FRAME_TYPE_D8,
            0x00,
            (D8_DATA_LEN >> 8) & 0xFF,
            D8_DATA_LEN & 0xFF,
            0x00,
            0x01,
        ]
    ) + data
    return FRAME_HEADER + body + bytes([_calc_checksum(body)])


def _collector(monkeypatch, redis, session: dict) -> BaseCollector:
    monkeypatch.setattr(
        'module_payload.collectors.base_collector.create_sync_redis',
        lambda: redis,
    )
    coll = BaseCollector('serial:COM4', {})
    coll._get_session_cached = lambda *a, **k: session  # type: ignore[method-assign]
    return coll


def _stats(samples_ms: list[float]) -> tuple[float, float, float]:
    xs = sorted(samples_ms)
    return xs[0], xs[len(xs) // 2], xs[-1]


def _run(coll: BaseCollector, payload: bytes, n: int = N_RUN) -> list[float]:
    for _ in range(N_WARM):
        coll._try_session_ingest(payload, coll.device_id, SRC_KIND_SERIAL)
    out: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter_ns()
        coll._try_session_ingest(payload, coll.device_id, SRC_KIND_SERIAL)
        out.append((time.perf_counter_ns() - t0) / 1e6)
    return out


def test_ingest_passthrough_no_parser_is_sub_ms(monkeypatch) -> None:
    redis = _CmdRedis()
    coll = _collector(monkeypatch, redis, {'assemblerId': 'passthrough', 'parserId': '', 'routes': []})
    noise = bytes(range(256)) * 16  # 4KB
    mn, med, mx = _stats(_run(coll, noise))
    print(f'\npassthrough/no-parser 4KB min/med/max ms={mn:.3f}/{med:.3f}/{mx:.3f} redis={len(redis.calls)}')
    assert mn < 1.0, f'无解释器时 4KB 不应到 8ms，实际 min={mn:.3f}ms'


def test_ingest_camera_noise_must_not_force_parse(monkeypatch) -> None:
    """噪声块若被当成 D8 数据区，会每次走 TeleMetryParser，出现 8ms 地板。"""
    redis = _CmdRedis()
    coll = _collector(
        monkeypatch,
        redis,
        {'assemblerId': 'passthrough', 'parserId': PARSER_TM_XL_CAMERA, 'routes': []},
    )
    noise = bytes([0x11]) * 4096
    samples = _run(coll, noise)
    mn, med, mx = _stats(samples)
    print(f'\ncamera/noise 4KB min/med/max ms={mn:.3f}/{med:.3f}/{mx:.3f} redis={len(redis.calls)}')
    assert mn < 0.5, f'噪声块不应当完整遥测解析，min={mn:.3f}ms'


def test_ingest_camera_100_d8_no_per_frame_stat(monkeypatch) -> None:
    redis = _CmdRedis()
    coll = _collector(
        monkeypatch,
        redis,
        {'assemblerId': 'passthrough', 'parserId': PARSER_TM_XL_CAMERA, 'routes': []},
    )
    blob = _d8_frame() * 100
    samples = _run(coll, blob, n=8)
    mn, med, mx = _stats(samples)
    print(f'\ncamera/100xD8 min/med/max ms={mn:.3f}/{med:.3f}/{mx:.3f} redis={len(redis.calls)}')
    assert med < 20.0, f'100 帧不应再每帧 stat 配置文件，med={med:.3f}ms'


def test_collect_prepared_100_d8_is_fast() -> None:
    """拆帧+准备不应再触发 _ResolvedCfg 路径探测（约 0.35ms/帧）。"""
    from module_payload.parsers.xl_camera_tm import XlCameraTmIngest, _get_cam_tm_mgr

    blob = _d8_frame() * 100
    _get_cam_tm_mgr()
    for _ in range(3):
        XlCameraTmIngest._collect_prepared(blob)
    samples: list[float] = []
    for _ in range(8):
        t0 = time.perf_counter_ns()
        XlCameraTmIngest._collect_prepared(blob)
        samples.append((time.perf_counter_ns() - t0) / 1e6)
    mn, med, mx = _stats(samples)
    print(f'\ncollect_prepared/100xD8 min/med/max ms={mn:.3f}/{med:.3f}/{mx:.3f}')
    assert med < 5.0, f'100 帧 prepare 中位 {med:.3f}ms，仍在每帧 resolve 配置'


def test_get_cam_tm_mgr_hot_path_is_microseconds() -> None:
    from module_payload.parsers.xl_camera_tm import _get_cam_tm_mgr, _cam_tm_cache

    _cam_tm_cache.clear()
    _get_cam_tm_mgr()
    samples: list[float] = []
    for _ in range(200):
        t0 = time.perf_counter_ns()
        _get_cam_tm_mgr()
        samples.append((time.perf_counter_ns() - t0) / 1e3)
    med = sorted(samples)[len(samples) // 2]
    print(f'\n_get_cam_tm_mgr hot median us={med:.3f}')
    assert med < 50.0, f'_get_cam_tm_mgr 热路径 {med:.1f}us，仍在 stringify/resolve 配置路径'


def test_ingest_camera_one_d8_frame(monkeypatch) -> None:
    redis = _CmdRedis()
    coll = _collector(
        monkeypatch,
        redis,
        {'assemblerId': 'passthrough', 'parserId': PARSER_TM_XL_CAMERA, 'routes': []},
    )
    frame = _d8_frame()
    try:
        samples = _run(coll, frame)
    except Exception as exc:
        pytest.fail(f'D8 ingest 异常: {exc}')
    mn, med, mx = _stats(samples)
    print(f'\ncamera/1xD8 min/med/max ms={mn:.3f}/{med:.3f}/{mx:.3f} redis={len(redis.calls)}')
    # 首帧可能加载 TeleMetry 配置；热路径中位应远低于 8ms
    assert med < 8.0, f'D8 热路径中位 {med:.3f}ms，仍接近 8ms 地板'


def test_ingest_stage_breakdown(monkeypatch, capsys) -> None:
    """打印各阶段耗时，便于对照 8~900ms。"""
    from module_payload.parsers import xl_camera_tm as cam

    redis = _CmdRedis()
    coll = _collector(
        monkeypatch,
        redis,
        {'assemblerId': 'passthrough', 'parserId': PARSER_TM_XL_CAMERA, 'routes': []},
    )
    noise = bytes([0x22]) * 4096
    frame = _d8_frame()
    stages = defaultdict(list)

    def wrap(name, fn):
        def inner(*a, **k):
            t0 = time.perf_counter_ns()
            try:
                return fn(*a, **k)
            finally:
                stages[name].append((time.perf_counter_ns() - t0) / 1e6)

        return inner

    coll._get_session_cached = wrap('session', coll._get_session_cached)  # type: ignore[method-assign]
    coll._store_assembled = wrap('store_assembled', coll._store_assembled)  # type: ignore[method-assign]
    coll._dispatch_payloads = wrap('dispatch', coll._dispatch_payloads)  # type: ignore[method-assign]
    orig_collect = cam.XlCameraTmIngest._collect_prepared
    orig_enqueue = cam.enqueue_prepared_many
    cam.XlCameraTmIngest._collect_prepared = wrap('collect_prepared', orig_collect)  # type: ignore[method-assign]
    monkeypatch.setattr(cam, 'enqueue_prepared_many', wrap('enqueue', orig_enqueue))

    for payload, tag in ((noise, 'noise'), (frame, 'd8')):
        stages.clear()
        redis.calls.clear()
        ms = _run(coll, payload, n=20)
        mn, med, mx = _stats(ms)
        print(f'\n=== {tag} total min/med/max={mn:.3f}/{med:.3f}/{mx:.3f} redis={len(redis.calls)}')
        for name, xs in stages.items():
            a, b, c = _stats(xs)
            print(f'  {name:18s} min/med/max={a:.3f}/{b:.3f}/{c:.3f} n={len(xs)}')
    # 不强制失败：这是诊断输出；具体上限由上面用例卡住
    assert True
