"""采集 Redis 封装：2ms/20 缓冲、积压倒空、定时裁剪、读绕过写队列；helper 纯函数。"""

from __future__ import annotations

import json
import time
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collectors import redis_cmd_helper as h
from module_payload.collectors.collector_redis import CollectorRedis
from module_payload.constants import (
    CURVE_MAX_POINTS,
    ERROR_LOG_MAX,
    HISTORY_MAX,
    IO_LOG_MAX,
    REDIS_FLUSH_COUNT,
    REDIS_FLUSH_FORCE,
    REDIS_FLUSH_INTERVAL_MS,
    TM_FPS_TTL_S,
)


class FakePipeline:
    """记录命令，``execute`` 时并入客户端；``fail`` 时抛错模拟 Redis 断开。"""

    def __init__(self, client: 'FakeRedis') -> None:
        self._client = client
        self._ops: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str):
        def _call(*args: Any, **_kwargs: Any) -> 'FakePipeline':
            self._ops.append((name, args))
            return self

        return _call

    def execute(self) -> list[Any]:
        if self._client.fail:
            raise RuntimeError('redis down')
        self._client.batches.append(list(self._ops))
        self._client.executed.extend(self._ops)
        self._ops = []
        return []


class FakeRedis:
    """只实现封装用到的接口。"""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.batches: list[list[tuple[str, tuple[Any, ...]]]] = []
        self.fail = False
        self.closed = False
        self.reads: list[tuple[str, tuple[Any, ...]]] = []

    def pipeline(self, transaction: bool = False) -> FakePipeline:
        return FakePipeline(self)

    def get(self, key: str) -> Any:
        self.reads.append(('get', (key,)))
        return 'v'

    def lpop(self, key: str) -> Any:
        self.reads.append(('lpop', (key,)))
        return None

    def incr(self, key: str) -> int:
        self.reads.append(('incr', (key,)))
        return len([r for r in self.reads if r[0] == 'incr'])

    def close(self) -> None:
        self.closed = True


def _client(**kwargs) -> tuple[CollectorRedis, FakeRedis]:
    fake = FakeRedis()
    kwargs.setdefault('start_worker', False)
    return CollectorRedis(fake, **kwargs), fake


def _ops(n: int, key: str = 'payload:serial:COM3:io') -> list[h.RedisOp]:
    return [h.RedisOp('lpush', (key, f'e{i}')) for i in range(n)]


# ---- 缓冲与刷出 ----


def test_write_batch_buffers_until_flush() -> None:
    """业务线程只入队：未到节拍/未满批不打 Redis。"""
    c, fake = _client()
    c.write_batch(_ops(5))
    assert fake.executed == []
    assert c.pending_count == 5
    assert c.flush() is True
    assert len(fake.executed) == 5
    assert c.pending_count == 0


def test_flush_interval_and_count_defaults() -> None:
    assert REDIS_FLUSH_INTERVAL_MS == 2
    assert REDIS_FLUSH_COUNT == 20
    assert REDIS_FLUSH_FORCE == 100


def test_worker_flushes_on_full_batch() -> None:
    """满 20 条唤醒刷写线程，不必等业务再调。"""
    fake = FakeRedis()
    c = CollectorRedis(fake)
    try:
        c.write_batch(_ops(REDIS_FLUSH_COUNT))
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and len(fake.executed) < REDIS_FLUSH_COUNT:
            time.sleep(0.005)
        assert len(fake.executed) == REDIS_FLUSH_COUNT
    finally:
        c.close()


def test_worker_flushes_small_batch_on_interval() -> None:
    """不满批也在 2ms 节拍刷出，避免采图过程中 Redis 空着。"""
    fake = FakeRedis()
    c = CollectorRedis(fake)
    try:
        c.write_batch(_ops(3))
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and len(fake.executed) < 3:
            time.sleep(0.005)
        assert len(fake.executed) == 3
    finally:
        c.close()


def test_backlog_over_force_drains_whole_buffer_at_once() -> None:
    """积压超过 100：一次把整个缓冲写出，不是每 100 条一批。"""
    c, fake = _client()
    c.write_batch(_ops(REDIS_FLUSH_FORCE + 150))
    c.flush()
    assert len(fake.batches) == 1
    assert len(fake.executed) == REDIS_FLUSH_FORCE + 150


def test_pipe_max_ops_chunks_huge_batch() -> None:
    """单次 pipeline 命令数有上限，字段极多的曲线不会撑爆。"""
    c, fake = _client(pipe_max_ops=2)
    c.write_batch(_ops(5))
    c.flush()
    assert [len(b) for b in fake.batches] == [2, 2, 1]


def test_multi_key_multi_device_in_one_pipeline() -> None:
    """一次交互混合多设备多 key。"""
    c, fake = _client()
    c.write_batch(
        [
            h.RedisOp('lpush', ('payload:serial:COM3:io', 'a')),
            h.RedisOp('setex', ('payload:can:0:0:heartbeat', 15, 't')),
            h.RedisOp('set', ('payload:tm:FF:latest', '{}')),
        ]
    )
    c.flush()
    assert len(fake.batches) == 1
    assert [op[0] for op in fake.executed] == ['lpush', 'setex', 'set']


def test_empty_batch_is_noop() -> None:
    c, fake = _client()
    c.write_batch([])
    assert c.flush() is True
    assert fake.executed == []


# ---- 失败与积压保护 ----


def test_failed_execute_requeues_and_retries() -> None:
    """Redis 断开：命令留在缓冲，下个节拍重试，不丢不抛。"""
    c, fake = _client()
    fake.fail = True
    c.write_batch(_ops(4))
    assert c.flush() is False
    assert c.pending_count == 4
    fake.fail = False
    assert c.flush() is True
    assert len(fake.executed) == 4


def test_failed_chunk_does_not_duplicate_written_ops() -> None:
    """前一段已写出后失败：只把未写出的放回，避免重复行。"""
    c, fake = _client(pipe_max_ops=2)
    orig = fake.pipeline
    calls = {'n': 0}

    def flaky(transaction: bool = False) -> FakePipeline:
        calls['n'] += 1
        if calls['n'] == 2:
            fake.fail = True
        else:
            fake.fail = False
        return orig(transaction)

    fake.pipeline = flaky  # type: ignore[method-assign]
    c.write_batch(_ops(4))
    assert c.flush() is False
    assert len(fake.executed) == 2
    fake.pipeline = orig  # type: ignore[method-assign]
    fake.fail = False
    c.flush()
    assert [args[1] for _cmd, args in fake.executed] == ['e0', 'e1', 'e2', 'e3']


def test_max_pending_drops_oldest() -> None:
    """Redis 长时间不可用时内存有硬顶，丢最旧而不是撑爆采集进程。"""
    c, fake = _client(max_pending=3)
    fake.fail = True
    c.write_batch(_ops(5))
    assert c.pending_count == 3
    assert c.dropped_count == 2


# ---- 定时裁剪 ----


def test_trim_uses_cap_for_written_lists_only() -> None:
    """写过的有上限 List 才裁；队列不裁。"""
    c, fake = _client(trim_interval_s=0.0)
    c.write_batch(
        [
            h.RedisOp('lpush', (rk.io_log_key('serial:COM3'), 'a')),
            h.RedisOp('lpush', (rk.history_key('serial:COM3'), 'b')),
            h.RedisOp('lpush', (rk.tx_queue_key(), 'c')),
        ]
    )
    c.flush()
    c._trim_due(force=True)
    trims = {args[0]: args[2] for cmd, args in fake.executed if cmd == 'ltrim'}
    assert trims == {
        rk.io_log_key('serial:COM3'): IO_LOG_MAX - 1,
        rk.history_key('serial:COM3'): HISTORY_MAX - 1,
    }


def test_write_path_never_checks_length() -> None:
    """写入不 LLEN、不每次 LTRIM / ZREMRANGEBYRANK。"""
    c, fake = _client()
    c.write_batch(_ops(30, rk.io_log_key('serial:COM3')))
    c.flush()
    assert [cmd for cmd, _ in fake.executed] == ['lpush'] * 30


def test_curve_zadd_trim_is_deferred_to_timer() -> None:
    """曲线写入只有 ZADD；1s 定时才 ZREMRANGEBYRANK。"""
    c, fake = _client(trim_interval_s=0.0)
    c.write_batch(h.curves([('D9V17', {'CAMF001': 1.0}, 1000)]))
    c.flush()
    assert [cmd for cmd, _ in fake.executed] == ['zadd']
    c._trim_due(force=True)
    zremrank = [args for cmd, args in fake.executed if cmd == 'zremrangebyrank']
    zremscore = [args for cmd, args in fake.executed if cmd == 'zremrangebyscore']
    assert zremrank == [(rk.curve_latest_key('D9V17', 'CAMF001'), 0, -(CURVE_MAX_POINTS + 1))]
    assert len(zremscore) == 1
    assert zremscore[0][0] == rk.curve_latest_key('D9V17', 'CAMF001')
    assert zremscore[0][2] == '+inf'


def test_trim_respects_interval() -> None:
    c, fake = _client(trim_interval_s=60.0)
    c.write_batch([h.RedisOp('lpush', (rk.io_log_key('serial:COM3'), 'a'))])
    c.flush()
    c._trim_due()
    assert [cmd for cmd, _ in fake.executed] == ['lpush']


def test_trim_failure_keeps_key_dirty() -> None:
    c, fake = _client(trim_interval_s=0.0)
    c.write_batch([h.RedisOp('lpush', (rk.io_log_key('serial:COM3'), 'a'))])
    c.flush()
    fake.fail = True
    c._trim_due(force=True)
    fake.fail = False
    c._trim_due(force=True)
    assert any(cmd == 'ltrim' for cmd, _ in fake.executed)


# ---- 读路径 ----


def test_reads_bypass_write_buffer() -> None:
    """读立刻执行，不排在肥 LPUSH 后面。"""
    c, fake = _client()
    c.write_batch(_ops(50))
    assert c.get('payload:serial:COM3:status') == 'v'
    assert c.lpop('payload:serial:COM3:ctrl') is None
    assert c.incr('payload:serial:COM3:io:seq') == 1
    assert [r[0] for r in fake.reads] == ['get', 'lpop', 'incr']
    assert fake.executed == []


def test_verb_compat_methods_go_through_buffer() -> None:
    """兼容动词也进缓冲，仍是一次 pipeline。"""
    c, fake = _client()
    c.set('k', 'v')
    c.setex('h', 15, 't')
    c.lpush('payload:serial:COM3:io', 'e')
    c.delete('a', '')
    assert fake.executed == []
    c.flush()
    assert [cmd for cmd, _ in fake.executed] == ['set', 'setex', 'lpush', 'delete']
    assert len(fake.batches) == 1


def test_delete_keeps_fifo_order_with_writes() -> None:
    """删图与随后的写图同队列，不会被插队成先写后删。"""
    c, fake = _client()
    c.delete('payload:serial:COM4:image:meta')
    c.write_batch(h.image_meta('serial:COM4', {'phase': 'ready'}))
    c.flush()
    assert [cmd for cmd, _ in fake.executed] == ['delete', 'set']


def test_close_flushes_and_closes_client() -> None:
    fake = FakeRedis()
    c = CollectorRedis(fake, start_worker=False)
    c.write_batch(_ops(2))
    c.close()
    assert [cmd for cmd, _ in fake.executed] == ['lpush', 'lpush', 'ltrim']
    assert fake.closed is True
    c.write_batch(_ops(2))
    assert c.pending_count == 0


# ---- helper：纯函数 ----


def test_helper_curves_merges_same_field() -> None:
    ops = h.curves([
        ('FF', {'J1': 1.5, 'J2': 2}, 1234),
        ('FF', {'J1': 1.6}, 1235),
    ])
    assert [op.cmd for op in ops] == ['zadd', 'zadd']
    by_key = {op.args[0]: op.args[1] for op in ops}
    assert by_key[rk.curve_latest_key('FF', 'J1')] == {'1234|1.5': 1234, '1235|1.6': 1235}
    assert by_key[rk.curve_latest_key('FF', 'J2')] == {'1234|2': 1234}


def test_helper_curves_skips_empty_points() -> None:
    assert h.curves([('FF', {}, 1)]) == []
    assert h.curves([]) == []


def test_helper_dumps_callback_used_for_dict_only() -> None:
    seen: list[Any] = []

    def dumps(obj: Any) -> str:
        seen.append(obj)
        return 'ENCODED'

    ops = h.io_log('serial:COM3', [{'seq': 1}], dumps=dumps)
    assert ops[0].args == (rk.io_log_key('serial:COM3'), 'ENCODED')
    assert seen == [{'seq': 1}]
    # 已是字符串则不再编码
    plain = h.io_log('serial:COM3', ['raw'], dumps=dumps)  # type: ignore[list-item]
    assert plain[0].args[1] == 'raw'
    assert len(seen) == 1


def test_helper_default_dumps_is_json() -> None:
    ops = h.status('serial:COM3', {'state': 'running', 'msg': '采集中'})
    payload = json.loads(ops[0].args[1])
    assert payload['msg'] == '采集中'
    assert ops[0].args[0] == rk.status_key('serial:COM3')


def test_helper_io_stream_updates_seq() -> None:
    ops = h.io_stream('serial:COM3', [{'seq': 7}], last_seq=7)
    assert [op.cmd for op in ops] == ['lpush', 'set']
    assert ops[1].args == (rk.io_stream_seq_key('serial:COM3'), '7')


def test_helper_error_adds_device_compat_key_for_assembler() -> None:
    ops = h.error('assembler', {'message': 'x'}, device_id='serial:COM3')
    assert [op.args[0] for op in ops] == [
        rk.error_type_latest_key('assembler'),
        rk.error_type_key('assembler'),
        rk.assembled_error_key('serial:COM3'),
    ]
    assert len(h.error('tm', {'message': 'x'}, device_id='serial:COM3')) == 2


def test_helper_assembled_latest_and_log() -> None:
    ops = h.assembled('serial:COM3', {'len': 3})
    assert [op.cmd for op in ops] == ['set', 'lpush']


def test_helper_heartbeat_and_cmd_result_ttl() -> None:
    assert h.heartbeat('serial:COM3', 't')[0].args[1] == 15
    assert h.cmd_result('serial:COM3', 'c1', {'success': True})[0].args[1] == 120


def test_helper_tm_fps() -> None:
    ops = h.tm_fps('d8', 600.04)
    assert ops[0].cmd == 'setex'
    assert ops[0].args == (rk.telemetry_fps_key('D8'), TM_FPS_TTL_S, '600.0')
    assert h.tm_fps('', 1.0) == []


def test_helper_delete_drops_blank_keys() -> None:
    assert h.delete(['a', '', None])[0].args == ('a',)  # type: ignore[list-item]
    assert h.delete([]) == []


def test_resolve_list_cap() -> None:
    assert h.resolve_list_cap(rk.io_log_key('serial:COM3')) == IO_LOG_MAX
    assert h.resolve_list_cap(rk.io_stream_key('serial:COM3')) == IO_LOG_MAX
    assert h.resolve_list_cap(rk.history_key('serial:COM3')) == HISTORY_MAX
    assert h.resolve_list_cap(rk.error_type_key('tm')) == ERROR_LOG_MAX
    assert h.resolve_list_cap(rk.error_type_latest_key('tm')) is None
    assert h.resolve_list_cap(rk.tx_queue_key()) is None
    assert h.resolve_list_cap(rk.archive_queue_key()) is None
    assert h.resolve_list_cap(rk.ctrl_queue_key('serial:COM3')) is None
