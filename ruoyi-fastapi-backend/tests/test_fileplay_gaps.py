"""fileplay 覆盖率补洞：detect / engine / manager / worker / parse_frame / paths。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from module_payload import redis_keys as rk
from module_payload.cfg.can_yc_frame import CAN_YC_FRAME_TYPE_COMPLEX
from module_payload.fileplay import store
from module_payload.fileplay.detect import (
    FileIndex,
    FrameRef,
    detect_file_kind,
    estimate_frame_count,
    frame_data_ts_ms,
    index_file,
    iter_bin_frames,
    iter_hex_frames,
    parse_recv_file_start_ms,
    _can_frame_ok,
    _first_bin_frame,
    _match_raw_frame,
    _parse_line_ts_ms,
)
from module_payload.fileplay.engine import FilePlayEngine
from module_payload.fileplay.manager import FilePlayManager
from module_payload.fileplay.parse_frame import Path_read, _fmt_ts, parse_frame
from module_payload.fileplay.paths import list_dir, locate_play_file, resolve_play_path, root_for
from module_payload.parsers.xl_board_tm import FRAME_HEADER as BOARD_HEADER
from module_payload.parsers.xl_board_tm import XlBoardTmIngest, _calc_checksum as board_chk
from module_payload.parsers.xl_camera_tm import (
    D8_DATA_LEN,
    FRAME_HEADER as CAM_HEADER,
    FRAME_TYPE_D8,
    FRAME_TYPE_D9,
    XlCameraTmIngest,
    _calc_checksum as cam_chk,
)


def _can_frame(data_type: int = 0xFF, payload: bytes = b'\x11\x22') -> bytes:
    body = bytes([CAN_YC_FRAME_TYPE_COMPLEX, data_type & 0xFF]) + payload
    data_len = len(body)
    head = bytes([(data_len >> 8) & 0xFF, data_len & 0xFF]) + body
    return head + bytes([sum(head) & 0xFF])


def _hex_line(frame: bytes, stamp: str = '20260101120000') -> str:
    id_part = ' ' * 8
    hx = ' '.join(f'{b:02X}' for b in frame)
    return f'{stamp} {id_part} [{hx}]\n'


def _d8_frame() -> bytes:
    data = bytes(D8_DATA_LEN)
    body = bytes([FRAME_TYPE_D8, 0x00, (D8_DATA_LEN >> 8) & 0xFF, D8_DATA_LEN & 0xFF, 0x00, 0x01]) + data
    return CAM_HEADER + body + bytes([cam_chk(body)])


def _d9_frame(seq: int = 1) -> bytes:
    mid = bytes([seq & 0xFF]) + bytes(16)
    return bytes([0xEB, FRAME_TYPE_D9]) + mid + bytes([cam_chk(mid)])


def _board_frame(src: int = 0x33) -> bytes:
    payload = bytes(20)
    body = bytes([src & 0xFF, 0x11]) + payload
    frame = BOARD_HEADER + len(body).to_bytes(2, 'big') + body
    return frame + bytes([board_chk(frame[2:])])


def _patch_play_roots(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    logs = tmp_path / 'logs_data'
    upload = tmp_path / 'log_data'
    logs.mkdir()
    upload.mkdir()
    monkeypatch.setattr('module_payload.fileplay.paths.get_logs_data_dir', lambda: logs)
    monkeypatch.setattr('module_payload.fileplay.paths.get_upload_log_data_dir', lambda: upload)
    return logs, upload


class _FakeRedis:
    def __init__(self) -> None:
        self.h: dict[str, dict[str, str]] = {}
        self.kv: dict[str, str] = {}
        self.lists: dict[str, list] = {}
        self.closed = False
        self._brpop_queue: list = []

    def hset(self, key, field=None, value=None, mapping=None):
        bucket = self.h.setdefault(key, {})
        if mapping:
            bucket.update(mapping)
        if field is not None:
            bucket[field] = value

    def hget(self, key, field):
        return self.h.get(key, {}).get(field)

    def delete(self, key):
        self.h.pop(key, None)
        self.kv.pop(key, None)

    def set(self, key, value, ex=None):
        self.kv[key] = value

    def get(self, key):
        return self.kv.get(key)

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def brpop(self, key, timeout=0):
        if self._brpop_queue:
            return self._brpop_queue.pop(0)
        return None

    def close(self):
        self.closed = True


# ---- detect ----


def test_detect_kind_edge_cases(tmp_path: Path) -> None:
    assert detect_file_kind(tmp_path / 'missing.txt') == 'hex'
    assert detect_file_kind(tmp_path / 'missing.bin') == 'bin'
    assert detect_file_kind('x.bin', sample=b'hello world ' * 50) == 'hex'
    assert detect_file_kind('x.dat', sample=bytes(range(256))) == 'bin'
    # 不可打印占比高 → bin（非 .txt）
    assert detect_file_kind('x.log', sample=bytes([1, 2, 3, 4, 5] * 20)) == 'bin'
    assert parse_recv_file_start_ms('x_20261301_120000_001_recv.bin') == 0
    assert _parse_line_ts_ms('not-a-stamp') == 0
    assert estimate_frame_count(100, 0) == 1
    idx = FileIndex(path='p', table_type='BIU:FF', kind='hex', size=1, start_ts_ms=0)
    ref = FrameRef(offset=0, length=1, ts_ms=12345)
    assert frame_data_ts_ms(idx, 1, ref) == 12345


def test_hex_bad_bytes_and_bin_find_fallback(tmp_path: Path) -> None:
    p = tmp_path / 'badhex_recv.txt'
    p.write_text('[AA BB]\n', encoding='utf-8')
    with patch('module_payload.fileplay.detect.hex_to_bytes', side_effect=ValueError('bad')):
        assert list(iter_hex_frames(p, 'BIU:FF')) == []
    bp = tmp_path / 'ghost_recv.bin'
    bp.write_bytes(b'\x00' * 8)
    ghost = b'\xaa\xbb\xcc\xdd'
    with patch.object(XlCameraTmIngest, 'extract_d8_frames', return_value=[ghost]):
        refs = list(iter_bin_frames(bp, 'XL:D8'))
        assert refs[0].offset == 0
    # 两轮空抽帧后再命中，触发 overlap 滑动
    with patch.object(XlCameraTmIngest, 'extract_d8_frames', side_effect=[[], [], [ghost]]):
        big = tmp_path / 'slide.bin'
        big.write_bytes(b'\x00' * (256 * 1024 * 2 + 10))
        assert _first_bin_frame(big, 'XL:D8') is not None
    from module_payload.fileplay.detect import _iter_frames

    list(_iter_frames(bp, 'BIU:FF', 'bin', keep_raw=False))
    list(_iter_frames(p, 'BIU:FF', 'hex', keep_raw=True))


def test_hex_iter_fallback_lines(tmp_path: Path) -> None:
    p = tmp_path / 'odd_recv.txt'
    frame = _can_frame()
    hx = ' '.join(f'{b:02X}' for b in frame)
    body = (
        b'\xff invalid\n'
        + f'no-stamp [{hx}]\n'.encode()
        + f'{hx}\n'.encode()
        + b'[ZZ ZZ]\n'
        + b'\n'
        + _hex_line(_can_frame(0xAA)).encode()
    )
    p.write_bytes(body)
    got = list(iter_hex_frames(p, 'BIU:FF'))
    assert len(got) >= 1
    assert _can_frame_ok(b'\x00\x01', 'BIU:FF') is None
    assert _can_frame_ok(_can_frame(0xAA), 'BIU:FF') is None
    assert _match_raw_frame(b'\x00', 'BIU:FF', 'unknown') is None


def test_bin_camera_board_and_can(tmp_path: Path) -> None:
    d8 = tmp_path / 'cam_d8_recv.bin'
    d8.write_bytes(b'\x00' + _d8_frame() + b'\xff')
    assert list(iter_bin_frames(d8, 'XL:D8'))
    assert _match_raw_frame(_d8_frame(), 'XL:D8', 'camera_d8')
    assert _match_raw_frame(b'\xeb\x90' + b'\x00' * 10, 'XL:D8', 'camera_d8')

    d9 = tmp_path / 'cam_d9_recv.bin'
    d9.write_bytes(_d9_frame(1) + _d9_frame(2))
    assert list(iter_bin_frames(d9, 'XL:D9'))
    assert _match_raw_frame(_d9_frame(), 'XL:D9', 'camera_d9')
    assert _match_raw_frame(b'\x00\x01', 'XL:D9', 'camera_d9') is None

    board = tmp_path / 'board_recv.bin'
    board.write_bytes(_board_frame(0x33) + _board_frame(0x44))
    assert list(iter_bin_frames(board, 'XL:RKDJ'))
    assert _match_raw_frame(_board_frame(0x33), 'XL:RKDJ', 'board')
    assert _match_raw_frame(_board_frame(0x44), 'XL:RKDJ', 'board') is None

    canp = tmp_path / 'can_recv.bin'
    canp.write_bytes(b'\x00\x00' + _can_frame() + b'\xff')
    refs = list(iter_bin_frames(canp, 'BIU:FF', keep_raw=False))
    assert refs and refs[0].raw is None
    first = _first_bin_frame(canp, 'BIU:FF')
    assert first is not None and first.raw
    empty = tmp_path / 'empty.bin'
    empty.write_bytes(b'')
    assert _first_bin_frame(empty, 'BIU:FF') is None


def test_first_bin_frame_camera_board(tmp_path: Path) -> None:
    p = tmp_path / 'big_d8.bin'
    p.write_bytes(_d8_frame())
    assert _first_bin_frame(p, 'XL:D8') is not None
    p9 = tmp_path / 'big_d9.bin'
    p9.write_bytes(_d9_frame())
    assert _first_bin_frame(p9, 'XL:D9') is not None
    pb = tmp_path / 'big_board.bin'
    pb.write_bytes(_board_frame())
    assert _first_bin_frame(pb, 'XL:RKDJ') is not None


def test_index_no_frames_and_estimate(tmp_path: Path) -> None:
    empty = tmp_path / 'none_recv.txt'
    empty.write_text('hello\n', encoding='utf-8')
    idx = index_file(empty, 'BIU:FF')
    assert idx.error and idx.frame_count_exact is True

    binp = tmp_path / 'est_recv.bin'
    binp.write_bytes(_can_frame())
    est = index_file(binp, 'BIU:FF', force_estimate=True)
    assert est.frame_count_exact is False
    assert est.frames

    miss = tmp_path / 'miss_recv.bin'
    miss.write_bytes(b'\x00' * 20)
    bad = index_file(miss, 'BIU:FF', force_estimate=True)
    assert bad.error and bad.frame_count_exact is True


# ---- paths ----


def test_paths_edge_branches(tmp_path: Path, monkeypatch) -> None:
    logs, upload = _patch_play_roots(tmp_path, monkeypatch)
    assert root_for('log_data') == upload
    assert root_for('uploaddir') == upload
    assert root_for('local') == logs
    with pytest.raises(ValueError, match='允许'):
        resolve_play_path('no_such_recv.txt')

    nested = logs / 'a' / 'b'
    nested.mkdir(parents=True)
    listing = list_dir('logs', 'a/b')
    assert listing['path'] == 'a/b'
    assert listing['parent'] == 'a'

    with pytest.raises(ValueError, match='越界'):
        list_dir('logs', '..')
    file_as_dir = logs / 'file_recv.txt'
    file_as_dir.write_text('x', encoding='utf-8')
    with pytest.raises(ValueError, match='不是目录'):
        list_dir('logs', 'file_recv.txt')
    created = list_dir('logs', 'brand_new')
    assert (logs / 'brand_new').is_dir()
    assert created['entries'] == []

    with patch('module_payload.fileplay.paths._is_relative_to', side_effect=[True, False, False]):
        hit = locate_play_file(str(file_as_dir))
        assert hit['found'] is False


# ---- parse_frame ----


def test_parse_frame_path_read_and_kinds(tmp_path: Path, monkeypatch) -> None:
    logs, _ = _patch_play_roots(tmp_path, monkeypatch)
    p = logs / 'pf_recv.txt'
    line = _hex_line(_can_frame())
    p.write_text(line, encoding='utf-8')
    idx = index_file(p, 'BIU:FF', force_estimate=False)
    for fr in idx.frames:
        fr.raw = None
    snap = parse_frame(idx, 1)
    assert snap['frameIndex'] == 1
    assert snap['rows'] is not None
    assert Path_read(str(p), 0, 4)
    assert _fmt_ts(0) == ''
    with pytest.raises(IndexError):
        parse_frame(idx, 0)

    fake_parsed = SimpleNamespace(
        fields=[{'id': 'A', 'show': '1', 'value': 1}], name='n', raw_frame=b'\x01\x02'
    )
    for table, raw in (
        ('XL:D8', _d8_frame()),
        ('XL:D9', _d9_frame()),
        ('XL:RKDJ', _board_frame()),
    ):
        i = FileIndex(
            path=str(p), table_type=table, kind='bin', size=len(raw), frames=[FrameRef(0, len(raw), raw=raw)]
        )
        with patch.object(XlCameraTmIngest, 'parse_bytes', return_value=fake_parsed), patch.object(
            XlBoardTmIngest, 'parse_bytes', return_value=fake_parsed
        ):
            out = parse_frame(i, 1)
            assert out['name'] == 'n'
            assert out['rawLen'] == 2


def test_parse_frame_d9_multi_and_hex_latin1(tmp_path: Path) -> None:
    raw = _d9_frame(1)
    p = tmp_path / 'd9.bin'
    p.write_bytes(raw + raw)
    frames = [FrameRef(0, len(raw), raw=None), FrameRef(len(raw), len(raw), raw=None)]
    idx = FileIndex(path=str(p), table_type='XL:D9', kind='bin', size=len(raw) * 2, frames=frames)
    fake = SimpleNamespace(fields=[], name='d9', raw_frame=raw)
    with patch.object(XlCameraTmIngest, 'parse_bytes', return_value=fake) as m:
        parse_frame(idx, 2)
        assert m.call_count == 1
        assert len(m.call_args[0][0]) == len(raw) * 2

    line = b'\xff [EB 90]\n'
    hp = tmp_path / 'latin_recv.txt'
    hp.write_bytes(line)
    idx2 = FileIndex(
        path=str(hp),
        table_type='XL:D8',
        kind='hex',
        size=len(line),
        frames=[FrameRef(0, len(line), raw=None)],
    )
    with patch('module_payload.fileplay.detect._match_raw_frame', return_value=b'\xeb\x90'):
        from module_payload.fileplay import parse_frame as pf

        data = pf._load_raw(idx2, idx2.frames[0])
        assert data == b'\xeb\x90'


# ---- engine ----


def test_engine_error_and_ensure_curve_branches(tmp_path: Path, monkeypatch) -> None:
    logs, _ = _patch_play_roots(tmp_path, monkeypatch)
    fake = _FakeRedis()
    engine = FilePlayEngine(fake)
    missing = logs / 'no_recv.txt'
    meta = engine.parse('BIU:FF', str(missing), force_estimate=False)
    assert meta['status'] == 'error'

    p = logs / 'ok_recv.txt'
    p.write_text(_hex_line(_can_frame()) + _hex_line(_can_frame(payload=b'\xaa')), encoding='utf-8')
    with patch('module_payload.fileplay.engine.parse_frame', side_effect=RuntimeError('boom')):
        bad = engine.parse('BIU:FF', str(p), force_estimate=False)
        assert bad['status'] == 'error' and 'boom' in bad['error']

    with patch('module_payload.fileplay.engine.parse_frame') as pf:
        pf.side_effect = lambda idx, n: {
            'type': idx.table_type,
            'rows': [{'id': 'X', 'show': str(n), 'value': float(n) if n != 2 else 'bad'}],
            'frameIndex': n,
            'tsMs': n * 1000 if n != 3 else 0,
        }
        ready = engine.parse('BIU:FF', str(p), force_estimate=False)
        h = ready['pathHash']
        assert engine.meta(h)['status'] == 'ready'
        assert engine.ensure_frame('other', 1) is None
        assert engine.ensure_frame(h, 0) is None
        assert engine.ensure_frame(h, 99) is None
        with patch('module_payload.fileplay.engine.parse_frame', side_effect=ValueError('x')):
            assert engine.ensure_frame(h, 2) is None
        assert engine.curve_points('other', ['X']) == {'X': []}
        pts = engine.curve_points(h, ['X', 'Z'], start_index=1, end_index=2)
        assert 'X' in pts

    engine._scan_gen = 5
    engine._scan_exact(4, 'h')
    engine._idx = FileIndex(path='x', table_type='BIU:FF', kind='hex', size=1)
    engine._path_hash = 'h'
    with patch('module_payload.fileplay.engine.finalize_exact_index') as fin:

        def _bump(idx):
            engine._scan_gen = 99
            return idx

        fin.side_effect = _bump
        engine._scan_exact(5, 'h')


def test_engine_curve_skips_empty_snap(tmp_path: Path, monkeypatch) -> None:
    logs, _ = _patch_play_roots(tmp_path, monkeypatch)
    fake = _FakeRedis()
    engine = FilePlayEngine(fake)
    p = logs / 'curve2_recv.txt'
    p.write_text(_hex_line(_can_frame()), encoding='utf-8')
    with patch(
        'module_payload.fileplay.engine.parse_frame',
        return_value={'type': 'BIU:FF', 'rows': [], 'frameIndex': 1, 'tsMs': 0},
    ):
        meta = engine.parse('BIU:FF', str(p), force_estimate=False)
        h = meta['pathHash']
        store.write_frame(fake, h, 1, {'rows': [], 'tsMs': 0})
        assert engine.curve_points(h, ['X'])['X'] == []
        # ensure_frame 返回 None → continue（line 171）
        with patch.object(engine, 'ensure_frame', return_value=None):
            fake.h[rk.fileplay_hash_key(h)].pop(store.frame_field(1), None)
            assert engine.curve_points(h, ['X'])['X'] == []


# ---- manager ----


def test_manager_local_engine_and_send(monkeypatch) -> None:
    FilePlayManager._instance = None
    fake = _FakeRedis()
    local = MagicMock()
    monkeypatch.setattr('module_payload.collectors.redis_sync.create_sync_redis', lambda: fake)
    monkeypatch.setattr(
        'module_payload.collectors.process_guard.install_shutdown_hooks',
        lambda *_a, **_k: None,
    )
    mgr = FilePlayManager()
    mgr._use_local = True
    mgr._local_engine = local
    mgr.parse('BIU:FF', '/tmp/a_recv.txt')
    local.parse.assert_called()
    mgr.ensure_frame('abcd', 2)
    local.ensure_frame.assert_called_with('abcd', 2)
    mgr.send({'op': 'curve', 'pathHash': 'h', 'fields': ['A'], 'startIndex': 1, 'endIndex': 2})
    local.curve_points.assert_called()
    mgr.send({'op': 'noop'})
    mgr.shutdown()
    assert mgr._local_engine is None


def test_manager_ensure_worker_fallback(monkeypatch) -> None:
    FilePlayManager._instance = None
    fake = _FakeRedis()
    monkeypatch.setattr('module_payload.collectors.redis_sync.create_sync_redis', lambda: fake)
    monkeypatch.setattr(
        'module_payload.collectors.process_guard.install_shutdown_hooks',
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr('module_payload.collectors.process_guard.assign_to_kill_job', lambda *_a, **_k: None)
    mgr = FilePlayManager.instance()
    assert mgr is FilePlayManager.instance()

    with patch('config.paths.get_logs_dir', side_effect=OSError('x')):
        assert mgr._open_worker_log() is None

    with patch('subprocess.Popen', side_effect=OSError('fail')):
        mgr._proc = None
        mgr._use_local = False
        mgr._local_engine = None
        mgr.ensure_worker()
        assert mgr._use_local is True

    alive = MagicMock()
    alive.poll.return_value = None
    fake.set(rk.fileplay_worker_status_key(), '{"alive":true}')
    with patch('subprocess.Popen', return_value=alive):
        mgr2 = FilePlayManager()
        mgr2._redis = fake
        mgr2.ensure_worker()
        assert mgr2._is_alive()

    dead = MagicMock()
    dead.poll.return_value = 1
    with patch('subprocess.Popen', return_value=dead):
        mgr3 = FilePlayManager()
        mgr3._redis = fake
        mgr3._proc = None
        mgr3._use_local = False
        mgr3._local_engine = None
        mgr3.ensure_worker()
        assert mgr3._use_local is True

    mgr4 = FilePlayManager()
    mgr4._use_local = False
    mgr4._proc = alive
    mgr4._redis = fake
    mgr4.send({'op': 'parse', 'type': 'BIU:FF', 'path': 'x'})
    assert fake.lists.get(rk.fileplay_ctrl_key())

    stubborn = MagicMock()
    stubborn.poll.return_value = None
    stubborn.wait.side_effect = Exception('timeout')
    mgr5 = FilePlayManager()
    mgr5._proc = stubborn
    mgr5._redis = fake
    mgr5._log_fp = MagicMock()
    mgr5.shutdown()
    stubborn.kill.assert_called()

    bad_r = MagicMock()
    bad_r.close.side_effect = RuntimeError('x')
    mgr6 = FilePlayManager()
    mgr6._redis = bad_r
    mgr6._close_redis()

    mgr7 = FilePlayManager()
    mgr7._proc = MagicMock()
    mgr7._proc.poll.return_value = 1
    mgr7._redis = fake
    assert mgr7._wait_worker_heartbeat(timeout_s=0.05) is False
    mgr7._proc.poll.return_value = None
    boom = MagicMock()
    boom.get.side_effect = RuntimeError('x')
    mgr7._redis = boom
    assert mgr7._wait_worker_heartbeat(timeout_s=0.15) is True

    # _get_redis 懒创建 + shutdown lpush/kill 异常
    mgr8 = FilePlayManager()
    mgr8._redis = None
    assert mgr8._get_redis() is fake
    alive2 = MagicMock()
    alive2.poll.return_value = None
    alive2.wait.side_effect = Exception('t')
    alive2.kill.side_effect = Exception('k')
    mgr8._proc = alive2
    mgr8._redis = MagicMock()
    mgr8._redis.lpush.side_effect = RuntimeError('lp')
    mgr8._log_fp = MagicMock()
    mgr8._log_fp.close.side_effect = OSError('c')
    mgr8.shutdown()

    # unix preexec 分支
    with patch('sys.platform', 'linux'), patch('subprocess.Popen', return_value=alive) as popen:
        mgr9 = FilePlayManager()
        mgr9._redis = fake
        fake.set(rk.fileplay_worker_status_key(), '1')
        mgr9.ensure_worker()
        assert 'preexec_fn' in (popen.call_args.kwargs if popen.call_args else {})


# ---- worker ----


def test_worker_bootstrap_and_main_guard(monkeypatch) -> None:
    from module_payload.fileplay import worker as w

    with patch('os.chdir') as ch, patch.object(w.sys, 'path', []):
        w._bootstrap()
        ch.assert_called()
        assert str(w._BACKEND_ROOT) in w.sys.path


def test_worker_helpers_and_main_loop(monkeypatch, tmp_path: Path) -> None:
    from module_payload.fileplay import worker as w

    fake = _FakeRedis()
    w._write_parse_error(fake, {'pathHash': 'abc', 'path': 'p', 'type': 'BIU:FF'}, RuntimeError('e'))
    meta = store.read_meta(fake, 'abc')
    assert meta['status'] == 'error'

    logs = tmp_path / 'logs_data'
    upload = tmp_path / 'log_data'
    logs.mkdir()
    upload.mkdir()
    monkeypatch.setattr('module_payload.fileplay.paths.get_logs_data_dir', lambda: logs)
    monkeypatch.setattr('module_payload.fileplay.paths.get_upload_log_data_dir', lambda: upload)
    p = logs / 'w_recv.txt'
    p.write_text('x', encoding='utf-8')
    w._write_parse_error(fake, {'path': str(p), 'type': 'BIU:FF'}, ValueError('v'))
    assert store.read_meta(fake, rk.fileplay_path_hash(str(p)))['status'] == 'error'
    w._write_parse_error(fake, {}, RuntimeError('nohash'))

    with patch('module_payload.fileplay.paths.resolve_play_path', side_effect=ValueError('bad')):
        w._write_parse_error(fake, {'path': 'outside'}, OSError('o'))

    eng = MagicMock()
    fake._brpop_queue = [
        None,
        (rk.fileplay_ctrl_key(), 'not-json'),
        (rk.fileplay_ctrl_key(), json.dumps({'op': 'parse', 'type': 'BIU:FF', 'path': 'a'})),
        (rk.fileplay_ctrl_key(), json.dumps({'op': 'ensure', 'pathHash': 'h', 'index': 1})),
        (rk.fileplay_ctrl_key(), json.dumps({'op': 'curve', 'pathHash': 'h', 'fields': ['A']})),
        (rk.fileplay_ctrl_key(), json.dumps({'op': 'parse', 'pathHash': 'eh'})),
        (rk.fileplay_ctrl_key(), json.dumps({'op': 'stop'})),
    ]
    eng.parse.side_effect = [None, RuntimeError('fail')]

    class _BoomThenOk(_FakeRedis):
        def __init__(self, inner: _FakeRedis):
            super().__init__()
            self.h = inner.h
            self.kv = inner.kv
            self.lists = inner.lists
            self._brpop_queue = inner._brpop_queue
            self._n = 0

        def set(self, *a, **k):
            self._n += 1
            if self._n == 1:
                raise RuntimeError('set fail once')
            return super().set(*a, **k)

    boom_redis = _BoomThenOk(fake)

    monkeypatch.setattr(w, '_bootstrap', lambda: None)
    monkeypatch.setattr('module_payload.collectors.redis_sync.create_sync_redis', lambda: boom_redis)
    monkeypatch.setattr('module_payload.fileplay.engine.FilePlayEngine', lambda redis: eng)
    with patch('time.sleep', return_value=None):
        w.main()
    eng.parse.assert_called()
    eng.ensure_frame.assert_called()
    eng.curve_points.assert_called()
    assert store.read_meta(boom_redis, 'eh')['status'] == 'error'
