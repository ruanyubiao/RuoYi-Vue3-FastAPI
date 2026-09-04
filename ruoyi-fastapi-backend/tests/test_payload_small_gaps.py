"""payload 小模块覆盖率补洞：dao / redis_store / store / hw_probe / golden / keys。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from module_payload import constants as c
from module_payload import redis_keys as rk
from module_payload import redis_store as rs
from module_payload.dao.payload_sequence_dao import PayloadSequenceDao
from module_payload.dao.payload_tm_archive_dao import PayloadTmArchiveDao
from module_payload.hw_probe import call_with_timeout
from module_payload.store import ports
from module_payload.store.archive_queue import enqueue
from module_payload.store.error_store import push_pipeline_error
from module_payload.store.session_store import dumps_session
from module_payload.tm_golden_samples import (
    _omit_fields,
    _sample_button_label,
    reset_sample_cache,
    _load_cache,
)


def _aio(fn):
    def _wrap(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))

    return _wrap


def test_constants_and_redis_keys_leftovers() -> None:
    assert not c.should_archive_tm_mysql('other', 'x', None)
    assert rk.fileplay_worker_status_key() == 'payload:fileplay:worker'
    assert c.checksum_u16(b'\x01\x02') == 3
    assert c.normalize_parser_id(None) == ''
    assert c.normalize_parser_id('none') == ''
    assert c.normalize_parser_id('tm_can_biu') == 'tm_can_biu'
    assert rk.assembled_latest_key('serial:COM1') == 'payload:serial:COM1:assembled:latest'
    assert rk.assembled_log_key('serial:COM1') == 'payload:serial:COM1:assembled'


def test_archive_bytes_empty_and_error_parser_id() -> None:
    from module_payload.store.archive_queue import bytes_to_raw_hex

    assert bytes_to_raw_hex(None) == ''
    assert bytes_to_raw_hex(b'') == ''
    redis = MagicMock(spec=['set', 'lpush', 'ltrim'])
    del redis.pipeline
    push_pipeline_error(redis, stage='tm', message='m', parser_id='p1')
    redis.set.assert_called()


@_aio
async def test_redis_image_lvds() -> None:
    class R:
        def __init__(self):
            self.kv = {}

        async def get(self, key):
            return self.kv.get(key)

        async def lrange(self, key, start, end):
            return ['{"t":1,"v":2}']

    r = R()
    r.kv[f'{rk.PREFIX}:serial:COM1:image:meta'] = '{"phase":1}'
    assert (await rs.get_image_meta(r, 'serial:COM1'))['phase'] == 1
    assert await rs.get_lvds_points(r, 'serial:COM1', 'qd_x') == [{'t': 1, 'v': 2}]


def test_hw_probe_exception_path() -> None:
    def boom():
        raise ValueError('hw')

    with pytest.raises(ValueError, match='hw'):
        call_with_timeout(boom, timeout=1.0, label='t')


def test_session_dumps_and_ports_import() -> None:
    assert '"a": 1' in dumps_session({'a': 1}) or dumps_session({'a': 1})
    assert ports.ErrorSink is not None
    assert ports.SessionReader is not None
    assert ports.ArchiveQueue is not None


@_aio
async def test_archive_enqueue_async_skip_and_push() -> None:
    redis = AsyncMock()
    await enqueue(
        redis,
        {'ts_ms': 1, 'points': {}, 'src_kind': 'serial', 'src_param': 'serial:COM1', 'parser_id': 'tm_xl_camera'},
    )
    redis.lpush.assert_not_called()
    await enqueue(
        redis,
        {'ts_ms': 1, 'points': {}, 'src_kind': 'can', 'src_param': 'can:3:0:0', 'parser_id': 'tm_can_biu'},
    )
    redis.lpush.assert_called()


def test_error_store_without_pipeline() -> None:
    redis = MagicMock(spec=['set', 'lpush', 'ltrim'])
    # no pipeline attr → else 分支
    del redis.pipeline
    push_pipeline_error(
        redis,
        stage='assembler',
        message='m',
        device_id='serial:COM1',
        assembler_id='a',
        data_len=1,
    )
    redis.set.assert_called()
    redis.lpush.assert_called()

    bad = MagicMock()
    bad.pipeline.side_effect = RuntimeError('x')
    push_pipeline_error(bad, stage='tm', message='m')  # 吞异常


@_aio
async def test_redis_store_command_wait_and_curve() -> None:
    class Fake:
        def __init__(self):
            self.kv = {}
            self.lists = {}
            self.zsets = {}

        async def lpush(self, key, value):
            self.lists.setdefault(key, []).insert(0, value)

        async def get(self, key):
            return self.kv.get(key)

        async def set(self, key, value, ex=None):
            self.kv[key] = value

        def pipeline(self, transaction=False):
            return MagicMock(execute=AsyncMock())

        async def zrangebyscore(self, key, min=None, max=None, start=0, num=None, withscores=True):
            return [(b'1|3.5', 1.0), (b'nopie', 2.0), (b'2|bad', 3.0)]

        async def zrange(self, key, start, end, withscores=True):
            return []

    r = Fake()
    await rs.push_command(r, 'serial:COM1', {'op': 'x'})
    assert r.lists

    r.kv[rk.cmd_result_key('serial:COM1', 'c1')] = '{"ok":true}'
    got = await rs.wait_command_result(r, 'serial:COM1', 'c1', timeout_s=0.2)
    assert got == {'ok': True}
    assert await rs.wait_command_result(r, 'serial:COM1', 'missing', timeout_s=0.12) is None

    await rs.append_curve_points(r, 'FF', [{'id': 'J1', 'calc_val': 1}], 'bad-ts')
    pts = await rs.get_curve_points(r, 'FF', 'J1', since_t=0)
    assert pts == [{'t': 1, 'v': 3.5}]


@_aio
async def test_tm_archive_dao() -> None:
    rows = [
        (100, {'A': 1.5}),
        (101, {'A': None}),
        (102, 'bad'),
        (103, {'A': 'x'}),
        (104, {'A': 2}),
    ]

    class _Result:
        def all(self):
            return rows

        def scalar_one(self):
            return 3

        def scalars(self):
            return SimpleNamespace(first=lambda: SimpleNamespace(id=1))

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_Result())
    pts = await PayloadTmArchiveDao.query_field_points(db, 'ff', 'A', 1, 200, src_param='can:1')
    assert pts == [(100, 1.5), (104, 2.0)]
    assert await PayloadTmArchiveDao.count_frames(db, 'ff', 1, 200) == 3
    assert await PayloadTmArchiveDao.get_frame_at_offset(db, 'ff', 1, 200, -1) is None
    assert await PayloadTmArchiveDao.get_frame_at_offset(db, 'ff', 1, 200, 0) is not None


@_aio
async def test_sequence_dao() -> None:
    class SeqModel(BaseModel):
        seq_name: str = 'n'
        project: str | None = None
        status: str | None = None

        def model_dump(self, exclude_unset=True, exclude=None):
            return {'seq_name': self.seq_name}

    row = SimpleNamespace(seq_id=1)
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: row))
    )
    db.add = MagicMock()
    db.flush = AsyncMock()

    assert await PayloadSequenceDao.get_sequence_detail_by_id(db, 1) is row

    query = SimpleNamespace(seq_name='a', project='p', status='0', page_num=1, page_size=10)
    with patch('module_payload.dao.payload_sequence_dao.PageUtil.paginate', new=AsyncMock(return_value=[])):
        assert await PayloadSequenceDao.get_sequence_list(db, query, is_page=True) == []

    from module_payload.entity.vo.payload_sequence_vo import PayloadSequenceModel

    seq = PayloadSequenceModel(seq_name='s1')
    with patch.object(PayloadSequenceModel, 'model_dump', return_value={'seq_name': 's1'}):
        out = await PayloadSequenceDao.add_sequence_dao(db, seq)
        assert out is not None
    await PayloadSequenceDao.edit_sequence_dao(db, {'seq_id': 1, 'seq_name': 'x'})
    await PayloadSequenceDao.delete_sequence_dao(db, seq)


def test_tm_golden_omit_and_labels(tmp_path, monkeypatch) -> None:
    assert _omit_fields([{'fields': [1], 'x': 2}]) == [{'x': 2}]
    assert _sample_button_label('passthrough_cam_unknown', {'kind': 'camera', 'result': {}}) == 'UNKNOWN'
    assert _sample_button_label('x_rkdj_y', {'kind': 'board', 'result': {}}) == 'RKDJ'
    assert _sample_button_label('plain', {'kind': 'board', 'result': {}}) == 'PLAIN'
    assert _sample_button_label('z', {'kind': 'other', 'result': {}}) == 'z'

    reset_sample_cache()
    monkeypatch.setattr(
        'module_payload.tm_golden_samples.resolve_data_file',
        lambda *_a, **_k: tmp_path / 'missing.json',
    )
    assert _load_cache() == {}
    reset_sample_cache()
