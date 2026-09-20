"""文件回放单测：侦测/拆帧、路径白名单、独立 Hash、取帧带总数、菜单 SQL。

样本一律写在 pytest ``tmp_path``（或由其映射出的回放根）里，测完删除，
不得落到真实 ``logs_data`` / ``upload_path/log_data``。
引擎生产默认 force_estimate=True（先 ready 再后台精确计数）；需要立即精确帧数的用例
显式传 force_estimate=False。
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading
import time

import pytest

from module_payload import redis_keys as rk
from module_payload.cfg.can_yc_frame import CAN_YC_FRAME_TYPE_COMPLEX
from module_payload.fileplay import store
from datetime import datetime

from module_payload.fileplay.detect import (
    FileIndex,
    detect_file_kind,
    fields_to_rows,
    finalize_exact_index,
    frame_data_ts_ms,
    index_file,
    ingest_kind,
    parse_recv_file_start_ms,
)
from module_payload.fileplay.engine import FilePlayEngine
from module_payload.fileplay.paths import is_recv_file, list_dir, locate_play_file, resolve_play_path
from module_payload.service.payload_fileplay_service import PayloadFilePlayService, _safe_filename


def _can_frame(data_type: int = 0xFF, payload: bytes = b'\x11\x22') -> bytes:
    """拼一帧 CAN 复合遥测（dataType 默认 FF）。"""
    body = bytes([CAN_YC_FRAME_TYPE_COMPLEX, data_type & 0xFF]) + payload
    data_len = len(body)
    head = bytes([(data_len >> 8) & 0xFF, data_len & 0xFF]) + body
    chk = sum(head) & 0xFF
    return head + bytes([chk])


def _hex_line(frame: bytes, stamp: str = '20260101120000') -> str:
    """CAN recv 文本行：时间戳 + 8 空格 id 列 + [HEX]。"""
    id_part = ' ' * 8
    hx = ' '.join(f'{b:02X}' for b in frame)
    return f'{stamp} {id_part} [{hx}]\n'


@contextmanager
def _temp_recv(path: Path, text: str = '', data: bytes | None = None):
    """写入临时 ``*_recv*`` 样本，退出时删除（即使断言失败）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if data is not None:
        path.write_bytes(data)
    else:
        path.write_text(text, encoding='utf-8')
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _patch_play_roots(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """把回放白名单根指到临时目录，避免污染真实 logs_data。"""
    logs = tmp_path / 'logs_data'
    upload = tmp_path / 'log_data'
    logs.mkdir()
    upload.mkdir()
    monkeypatch.setattr('module_payload.fileplay.paths.get_logs_data_dir', lambda: logs)
    monkeypatch.setattr('module_payload.fileplay.paths.get_upload_log_data_dir', lambda: upload)
    return logs, upload


def _stub_parse_frame(idx, n):
    """引擎单测不走真实 TeleMetry 解析，只返回可断言的表快照。"""
    return {
        'type': idx.table_type,
        'rows': [{'id': 'X', 'show': str(n), 'value': float(n)}],
        'frameIndex': n,
        'tsMs': n * 1000,
    }


class _FakeRedis:
    """同步 Redis 替身：Hash + SET（meta / worker 在 Hash 外面）。"""

    def __init__(self) -> None:
        self.h: dict[str, dict[str, str]] = {}
        self.kv: dict[str, str] = {}
        self.lists: dict[str, list] = {}

    def hset(self, key, field=None, value=None, mapping=None):
        bucket = self.h.setdefault(key, {})
        if mapping:
            bucket.update(mapping)
        if field is not None:
            bucket[field] = value

    def hget(self, key, field):
        return self.h.get(key, {}).get(field)

    def hlen(self, key):
        return len(self.h.get(key) or {})

    def hmget(self, key, *fields):
        return [self.hget(key, f) for f in fields]

    def hdel(self, key, *fields):
        bucket = self.h.get(key) or {}
        n = 0
        for f in fields:
            if f in bucket:
                bucket.pop(f, None)
                n += 1
        return n

    def set(self, key, value, ex=None):
        self.kv[key] = value

    def get(self, key):
        return self.kv.get(key)

    def lpop(self, key):
        return None

    def delete(self, *keys):
        for key in keys:
            self.h.pop(key, None)
            self.kv.pop(key, None)
            self.lists.pop(key, None)

    def unlink(self, *keys):
        return self.delete(*keys)

    def close(self):
        return None

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def llen(self, key):
        return len(self.lists.get(key) or [])

    def brpop(self, key, timeout=0):
        q = getattr(self, '_brpop_queue', None)
        if q:
            return q.pop(0)
        lst = self.lists.get(key)
        if lst:
            return key, lst.pop()
        return None

    def scan(self, cursor=0, match=None, count=None):
        import fnmatch

        keys = list(self.h) + list(self.kv) + list(self.lists)
        if match:
            keys = [k for k in keys if fnmatch.fnmatch(k, match)]
        return 0, keys


class _AsyncFakeRedis:
    """服务层 async Redis 替身，内部复用 ``_FakeRedis``。"""

    def __init__(self, inner: _FakeRedis | None = None) -> None:
        self.inner = inner or _FakeRedis()

    async def hget(self, key, field):
        return self.inner.hget(key, field)

    async def hmget(self, key, *fields):
        return self.inner.hmget(key, *fields)

    async def hdel(self, key, *fields):
        return self.inner.hdel(key, *fields)

    async def hset(self, key, field=None, value=None, mapping=None):
        return self.inner.hset(key, field=field, value=value, mapping=mapping)

    async def get(self, key):
        return self.inner.get(key)

    async def set(self, key, value, ex=None):
        return self.inner.set(key, value, ex=ex)

    async def expire(self, key, ttl):
        return True

    async def delete(self, *keys):
        return self.inner.delete(*keys)

    async def scan(self, cursor=0, match=None, count=None):
        return self.inner.scan(cursor=cursor, match=match, count=count)

    async def hlen(self, key):
        return self.inner.hlen(key)


class _Utf8DecodingAsyncRedis(_AsyncFakeRedis):
    """模拟 FastAPI Redis ``decode_responses=True``：二进制 Hash 值会炸 UTF-8。"""

    async def hget(self, key, field):
        raw = await super().hget(key, field)
        if isinstance(raw, (bytes, bytearray)):
            return bytes(raw).decode('utf-8')
        return raw


def test_detect_hex_vs_bin(tmp_path: Path) -> None:
    """有 NUL 的样本判 bin；可打印 CAN recv 文本判 hex。"""
    txt = tmp_path / 'a_recv.txt'
    binp = tmp_path / 'b_recv.bin'
    with _temp_recv(txt, _hex_line(_can_frame())):
        assert detect_file_kind(txt) == 'hex'
    with _temp_recv(binp, data=_can_frame() + b'\x00\xff'):
        assert detect_file_kind(binp) == 'bin'


def test_small_file_exact_count(tmp_path: Path) -> None:
    """小于 100MB 的 hex 文件开局即精确计帧。"""
    p = tmp_path / 'two_recv.txt'
    body = _hex_line(_can_frame(0xFF, b'\x01'), '20260101120000') + _hex_line(
        _can_frame(0xFF, b'\x02'), '20260101120001'
    )
    with _temp_recv(p, body):
        idx = index_file(p, 'BIU:FF')
        assert idx.error == ''
        assert idx.kind == 'hex'
        assert idx.frame_count == 2
        assert idx.frame_count_exact is True
        assert idx.has_timestamp is True


def test_estimate_then_exact(tmp_path: Path) -> None:
    """强制预估：先报已找到的帧数（1），扫完后改精确。"""
    p = tmp_path / 'est_recv.txt'
    body = _hex_line(_can_frame(0xFF, b'\x01\x02')) + _hex_line(_can_frame(0xFF, b'\x03\x04'))
    with _temp_recv(p, body):
        idx = index_file(p, 'BIU:FF', force_estimate=True)
        assert idx.frame_count_exact is False
        assert idx.frame_count == 1
        finalize_exact_index(idx)
        assert idx.frame_count_exact is True
        assert idx.frame_count == 2


def test_index_missing_file(tmp_path: Path) -> None:
    """文件不存在时给出 error，不计帧。"""
    idx = index_file(tmp_path / 'missing_recv.txt', 'BIU:FF')
    assert idx.error
    assert idx.frame_count == 0


def test_ingest_kind_and_fields_to_rows() -> None:
    """表 key 决定拆帧策略；解析字段列表转成遥测表行。"""
    assert ingest_kind('BIU:FF') == 'can'
    assert ingest_kind('XL:D8') == 'camera_d8'
    assert ingest_kind('XL:D9') == 'camera_d9'
    assert ingest_kind('D8V17') == 'camera_d8'
    assert ingest_kind('D9V17') == 'camera_d9'
    assert ingest_kind('XL:D9V17') == 'camera_d9'
    assert ingest_kind('XL:RKDJ') == 'board'
    rows = fields_to_rows([{'id': 'A1', 'name': '电流', 'show': '1.2', 'value': 1.2, 'unit': 'A', 'hex': '01'}])
    assert rows[0]['id'] == 'A1'
    assert rows[0]['show'] == '1.2'
    assert rows[0]['unit'] == 'A'


def test_index_d9v17_bin_not_scanned_as_can(tmp_path: Path) -> None:
    """D9V17 须按相机快遥拆 EB D9，不能当 CAN 滑窗扫到超时。"""
    from module_payload.parsers.xl_camera_tm import FRAME_TYPE_D9, _calc_checksum as cam_chk

    mid = bytes([1]) + bytes(16)
    frame = bytes([0xEB, FRAME_TYPE_D9]) + mid + bytes([cam_chk(mid)])
    p = tmp_path / 'cam_d9v17_recv.bin'
    p.write_bytes(frame * 3)
    idx = index_file(p, 'D9V17', force_estimate=True)
    assert not idx.error
    assert idx.frame_count >= 1
    assert idx.frames[0].raw[:2] == bytes([0xEB, 0xD9])
    exact = index_file(p, 'D9V17', force_estimate=False)
    assert exact.frame_count == 3
    assert exact.frame_count_exact is True


def test_fileplay_hash_isolated_from_live_tm() -> None:
    """文件会话 key 必须是 payload:play:file:*，禁止 payload:tm:*。"""
    h = rk.fileplay_path_hash('/tmp/x_recv.txt')
    key = rk.fileplay_hash_key(h)
    assert key == f'payload:play:file:history:{h}:data'
    assert rk.fileplay_hash_key(h, 'curve') == f'payload:play:file:curve:{h}:data'
    assert rk.fileplay_meta_key(h) == f'payload:play:file:history:{h}:meta'
    assert rk.fileplay_meta_key(h, 'curve') == f'payload:play:file:curve:{h}:meta'
    store.assert_not_live_tm_key(key)
    with pytest.raises(RuntimeError, match='实时遥测'):
        store.assert_not_live_tm_key('payload:tm:FF:latest')


def test_store_meta_frame_roundtrip() -> None:
    """Hash 读写 meta / 帧序号，切会话 DEL 整个 key。"""
    fake = _FakeRedis()
    h = 'abcd1234abcd1234'
    store.write_meta(fake, h, {'frameCount': 3, 'status': 'ready'})
    store.write_frame(fake, h, 2, {'frameIndex': 2, 'rows': []})
    assert store.read_meta(fake, h)['frameCount'] == 3
    assert store.read_frame(fake, h, 2)['frameIndex'] == 2
    parsed = store.iter_parsed_frames(fake, h, 1, 2)
    assert len(parsed) == 1 and parsed[0][0] == 2
    store.delete_session(fake, h)
    assert store.read_meta(fake, h) is None
    assert store.loads('not-json') is None
    assert store.loads(None) is None


def test_clear_channel_drops_history_keeps_curve() -> None:
    """history 启动清残余不能碰到 curve。"""
    fake = _FakeRedis()
    store.write_meta(fake, 'aaa', {'status': 'ready'}, channel='history')
    store.write_frame(fake, 'aaa', 1, {'rows': []}, channel='history')
    store.write_meta(fake, 'bbb', {'status': 'ready'}, channel='curve')
    store.write_frame(fake, 'bbb', 1, {'rows': [1]}, channel='curve')
    n = store.clear_channel(fake, 'history')
    assert n >= 2
    assert store.read_meta(fake, 'aaa', channel='history') is None
    assert store.read_frame(fake, 'aaa', 1, channel='history') is None
    assert store.read_meta(fake, 'bbb', channel='curve')['status'] == 'ready'
    assert store.read_frame(fake, 'bbb', 1, channel='curve')['rows'] == [1]


def test_is_recv_file_and_list_dir(tmp_path: Path, monkeypatch) -> None:
    """浏览只列出文件夹 + 文件名含 _recv 的项。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    sub = logs / 'sub'
    recv = logs / 'ok_recv.txt'
    other = logs / 'noise.bin'
    nested = sub / 'cam_recv.bin'
    with _temp_recv(recv, 'x'), _temp_recv(other, 'y'), _temp_recv(nested, 'z'):
        sub.mkdir(exist_ok=True)
        listing = list_dir('logs', '')
        names = {e['name']: e for e in listing['entries']}
        assert names['ok_recv.txt']['selectable'] is True
        assert names['ok_recv.txt']['size'] == recv.stat().st_size
        assert names['sub']['isDir'] is True
        assert names['sub']['size'] is None
        assert 'noise.bin' not in names
        inner = list_dir('logs', 'sub')
        assert inner['parent'] == ''
        assert any(e['name'] == 'cam_recv.bin' for e in inner['entries'])
    assert is_recv_file('a_recv.txt') is True
    assert is_recv_file('plain.txt') is False


def test_resolve_play_path_whitelist(tmp_path: Path, monkeypatch) -> None:
    """路径必须落在上传 log_data 或 logs_data；相对名按两根依次解析。"""
    logs, upload = _patch_play_roots(tmp_path, monkeypatch)
    inside = logs / 'in_recv.txt'
    with _temp_recv(inside, _hex_line(_can_frame())):
        assert resolve_play_path(inside) == inside.resolve()
        assert resolve_play_path('in_recv.txt') == inside.resolve()
    outside = tmp_path / 'outside_recv.txt'
    with _temp_recv(outside, 'x'):
        with pytest.raises(ValueError, match='允许'):
            resolve_play_path(outside)
    with pytest.raises(ValueError, match='root'):
        from module_payload.fileplay.paths import root_for

        root_for('other')
    up = upload / 'up_recv.txt'
    with _temp_recv(up, 'x'):
        assert resolve_play_path(up) == up.resolve()


def test_recv_filename_start_ts_and_frame_spacing() -> None:
    """文件名 YYYYMMDD_HHMMSS_mmm 为起始，后续帧 +1s。"""
    p = 'camera_ctrl_serial_COM3_20260824_103104_356_recv.bin'
    start = parse_recv_file_start_ms(p)
    assert start % 1000 == 356
    dt = datetime.fromtimestamp(start / 1000.0)
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second) == (2026, 8, 24, 10, 31, 4)
    idx = FileIndex(path=p, table_type='XL:D8', kind='bin', size=1, start_ts_ms=start)
    assert frame_data_ts_ms(idx, 1) == start
    assert frame_data_ts_ms(idx, 3) == start + 2000
    assert parse_recv_file_start_ms('plain_recv.bin') == 0


def test_locate_play_file(tmp_path: Path, monkeypatch) -> None:
    """已存在且在白名单内才定位；越界/缺失 found=false。"""
    logs, upload = _patch_play_roots(tmp_path, monkeypatch)
    nested = logs / '20260824' / 'cam_recv.bin'
    nested.parent.mkdir(parents=True)
    with _temp_recv(nested, 'x'):
        hit = locate_play_file(str(nested))
        assert hit['found'] is True
        assert hit['root'] == 'logs'
        assert hit['path'] == '20260824'
        assert hit['name'] == 'cam_recv.bin'
        up = upload / 'up_recv.txt'
        with _temp_recv(up, 'y'):
            uh = locate_play_file(str(up))
            assert uh['found'] is True
            assert uh['root'] == 'upload'
            assert uh['path'] == ''
            assert uh['name'] == 'up_recv.txt'
    assert locate_play_file(str(nested))['found'] is False
    outside = tmp_path / 'out_recv.txt'
    with _temp_recv(outside, 'z'):
        assert locate_play_file(str(outside))['found'] is False
    assert locate_play_file('')['found'] is False


def test_safe_filename() -> None:
    """上传只取 basename，拒绝空名与 . / ..。"""
    assert _safe_filename(r'C:\tmp\a_recv.txt') == 'a_recv.txt'
    with pytest.raises(ValueError, match='文件名'):
        _safe_filename('..')
    with pytest.raises(ValueError, match='文件名'):
        _safe_filename('')


def test_get_frame_response_includes_count(tmp_path: Path, monkeypatch) -> None:
    """解析写入独立 Hash；取帧带回 frameCount，且不创建 payload:tm:*。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    monkeypatch.setattr('module_payload.fileplay.engine.parse_frame', _stub_parse_frame)
    p = logs / 'play_sample_recv.txt'
    body = _hex_line(_can_frame()) + _hex_line(_can_frame(payload=b'\xaa'))
    fake = _FakeRedis()
    engine = FilePlayEngine(fake)
    with _temp_recv(p, body):
        meta = engine.parse('BIU:FF', str(p), force_estimate=False)
        assert meta.get('status') == 'ready'
        assert int(meta.get('frameCount') or 0) == 2
        assert meta.get('frameCountExact') is True
        path_hash = rk.fileplay_path_hash(str(resolve_play_path(p)))
        assert engine.ensure_frame(path_hash, 1) is not None
        second = engine.ensure_frame(path_hash, 2)
        assert second is not None and second['frameIndex'] == 2
        got = store.read_meta(fake, path_hash)
        assert got['frameCount'] == 2
        assert store.read_frame(fake, path_hash, 1)['rows'][0]['show'] == '1'
        live_keys = [k for k in fake.h if k.startswith('payload:tm:')]
        assert live_keys == []
        assert all(k.startswith('payload:play:file:history:') for k in fake.h)
        assert rk.fileplay_meta_key(path_hash, 'history') in fake.kv


def test_parse_default_ready_without_full_scan(tmp_path: Path, monkeypatch) -> None:
    """默认先预估：立刻 ready + 第 1 帧，精确计数后台扫完再覆盖。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    monkeypatch.setattr('module_payload.fileplay.engine.parse_frame', _stub_parse_frame)
    p = logs / 'est_play_recv.txt'
    body = _hex_line(_can_frame()) + _hex_line(_can_frame(payload=b'\xaa'))
    fake = _FakeRedis()
    engine = FilePlayEngine(fake)
    with _temp_recv(p, body):
        meta = engine.parse('BIU:FF', str(p))
        assert meta.get('status') == 'ready'
        assert int(meta.get('frameCount') or 0) == 1
        assert meta.get('frameCountExact') is False
        assert store.read_frame(fake, rk.fileplay_path_hash(str(resolve_play_path(p))), 1)
        if engine._scan_thread:
            engine._scan_thread.join(timeout=5)
        got = store.read_meta(fake, rk.fileplay_path_hash(str(resolve_play_path(p))))
        assert got['frameCountExact'] is True
        assert got['frameCount'] == 2


async def test_service_get_frame_returns_count(tmp_path: Path, monkeypatch) -> None:
    """HTTP 取帧接口每次带上当前总帧数（预估改精确后前端滑块能跟着变）。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    monkeypatch.setattr('module_payload.fileplay.engine.parse_frame', _stub_parse_frame)
    p = logs / 'svc_recv.txt'
    body = _hex_line(_can_frame()) + _hex_line(_can_frame(payload=b'\xaa'))
    fake = _FakeRedis()
    with _temp_recv(p, body):
        FilePlayEngine(fake).parse('BIU:FF', str(p), force_estimate=False)
        out = await PayloadFilePlayService.get_frame(_AsyncFakeRedis(fake), str(p), 1)
        assert out['frameCount'] == 2
        assert out['frameCountExact'] is True
        assert out['frame']['frameIndex'] == 1
        assert out['path']


async def test_service_parse_returns_without_waiting(tmp_path: Path, monkeypatch) -> None:
    """parse 只通知拆帧，不等 ready；status 接口再读结果。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    p = logs / 'kick_recv.txt'
    fake = _FakeRedis()

    class _SilentMgr:
        def parse(self, *_a, **_k):
            return None

    monkeypatch.setattr(
        'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
        classmethod(lambda cls, channel='history': _SilentMgr()),
    )
    with _temp_recv(p, _hex_line(_can_frame())):
        kicked = await PayloadFilePlayService.parse(_AsyncFakeRedis(fake), 'BIU:FF', str(p))
        assert kicked['status'] == 'parsing'
        assert kicked.get('frame') is None
        FilePlayEngine(fake).parse('BIU:FF', str(p), force_estimate=False)
        ready = await PayloadFilePlayService.get_status(_AsyncFakeRedis(fake), str(p))
        assert ready['status'] == 'ready'
        assert ready['frameCount'] == 1
        assert ready.get('frame')


def test_parse_same_file_while_scanning_skips(tmp_path: Path, monkeypatch) -> None:
    """同一文件扫描中再次 parse：不取消扫描、不删已写入的第 1 帧。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    monkeypatch.setattr('module_payload.fileplay.engine.parse_frame', _stub_parse_frame)
    gate = threading.Event()
    orig_finalize = finalize_exact_index

    def _blocked_finalize(idx, on_progress=None, should_stop=None):
        gate.wait(timeout=5)
        return orig_finalize(idx, on_progress=on_progress, should_stop=should_stop)

    monkeypatch.setattr('module_payload.fileplay.engine.finalize_exact_index', _blocked_finalize)
    p = logs / 'dup_recv.txt'
    body = _hex_line(_can_frame()) + _hex_line(_can_frame(payload=b'\xaa'))
    fake = _FakeRedis()
    engine = FilePlayEngine(fake)
    with _temp_recv(p, body):
        first = engine.parse('BIU:FF', str(p), force_estimate=True)
        assert first.get('alreadyParsing') is not True
        gen = engine._scan_gen
        path_hash = rk.fileplay_path_hash(str(resolve_play_path(p)))
        assert store.read_frame(fake, path_hash, 1)
        second = engine.parse('BIU:FF', str(p), force_estimate=True)
        assert second.get('alreadyParsing') is True
        assert engine._scan_gen == gen
        assert store.read_frame(fake, path_hash, 1)
        gate.set()
        if engine._scan_thread:
            engine._scan_thread.join(timeout=5)
        got = store.read_meta(fake, path_hash)
        assert got['frameCountExact'] is True
        assert got['frameCount'] == 2


async def test_service_parse_skips_same_file_scanning(tmp_path: Path, monkeypatch) -> None:
    """扫描未完成时 HTTP parse 不再推送，只回已找到的帧数。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    p = logs / 'skip_recv.txt'
    fake = _FakeRedis()
    with _temp_recv(p, _hex_line(_can_frame())):
        resolved = str(resolve_play_path(p))
        path_hash = rk.fileplay_path_hash(resolved)
        store.write_meta(
            fake,
            path_hash,
            {
                'status': 'ready',
                'type': 'BIU:FF',
                'frameCount': 1,
                'frameCountExact': False,
                'path': resolved,
            },
        )
        fake.set(rk.fileplay_worker_status_key(path_hash, 'history'), '{"alive":true}')
        calls: list[int] = []

        class _Mgr:
            def parse(self, *_a, **_k):
                calls.append(1)

        monkeypatch.setattr(
            'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
            classmethod(lambda cls, channel='history': _Mgr()),
        )
        out = await PayloadFilePlayService.parse(_AsyncFakeRedis(fake), 'BIU:FF', str(p))
        assert calls == []
        assert out['alreadyParsing'] is True
        assert out['frameCount'] == 1


async def test_service_parse_skips_same_file_complete(tmp_path: Path, monkeypatch) -> None:
    """已解析完成且无 force：拦截，不推 parse。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    p = logs / 'done_recv.txt'
    fake = _FakeRedis()
    with _temp_recv(p, _hex_line(_can_frame())):
        resolved = str(resolve_play_path(p))
        path_hash = rk.fileplay_path_hash(resolved)
        store.write_meta(
            fake,
            path_hash,
            {
                'status': 'ready',
                'type': 'BIU:FF',
                'frameCount': 12,
                'frameCountExact': True,
                'path': resolved,
            },
        )
        fake.set(rk.fileplay_worker_status_key(path_hash, 'history'), '{"alive":true}')
        calls: list[int] = []

        class _Mgr:
            def parse(self, *_a, **_k):
                calls.append(1)

        monkeypatch.setattr(
            'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
            classmethod(lambda cls, channel='history': _Mgr()),
        )
        out = await PayloadFilePlayService.parse(_AsyncFakeRedis(fake), 'BIU:FF', str(p))
        assert calls == []
        assert out['alreadyComplete'] is True
        assert out['alreadyParsing'] is False
        assert out['frameCount'] == 12


async def test_service_parse_force_sends(tmp_path: Path, monkeypatch) -> None:
    """弹窗确认 force=1：即使已完成也推 parse。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    p = logs / 'force_recv.txt'
    fake = _FakeRedis()
    with _temp_recv(p, _hex_line(_can_frame())):
        resolved = str(resolve_play_path(p))
        path_hash = rk.fileplay_path_hash(resolved)
        store.write_meta(
            fake,
            path_hash,
            {
                'status': 'ready',
                'type': 'BIU:FF',
                'frameCount': 12,
                'frameCountExact': True,
                'path': resolved,
            },
        )
        fake.set(rk.fileplay_worker_status_key(path_hash, 'history'), '{"alive":true}')
        calls: list[tuple] = []

        class _Mgr:
            def parse(self, *a, **k):
                calls.append((a, k))

        monkeypatch.setattr(
            'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
            classmethod(lambda cls, channel='history': _Mgr()),
        )
        await PayloadFilePlayService.parse(_AsyncFakeRedis(fake), 'BIU:FF', str(p), force=1)
        assert len(calls) == 1
        assert calls[0][1].get('force') is True


async def test_service_parse_leftover_without_worker_uses_cache(tmp_path: Path, monkeypatch) -> None:
    """worker 已退但 parsedDone/complete 仍在：当缓存用，不重新 parse。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    p = logs / 'stale_recv.txt'
    fake = _FakeRedis()
    with _temp_recv(p, _hex_line(_can_frame())):
        resolved = str(resolve_play_path(p))
        path_hash = rk.fileplay_path_hash(resolved)
        store.write_meta(
            fake,
            path_hash,
            {
                'status': 'ready',
                'type': 'BIU:FF',
                'frameCount': 12,
                'frameCountExact': True,
                'parsedDone': True,
                'path': resolved,
            },
        )
        calls: list[int] = []

        class _Mgr:
            def parse(self, *_a, **_k):
                calls.append(1)

        monkeypatch.setattr(
            'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
            classmethod(lambda cls, channel='history': _Mgr()),
        )
        out = await PayloadFilePlayService.parse(_AsyncFakeRedis(fake), 'BIU:FF', str(p))
        assert calls == []
        assert out['alreadyComplete'] is True


async def test_get_curve_returns_ready_chunks(tmp_path: Path, monkeypatch) -> None:
    """已有块直接返回；缺块通知 worker，pendingChunks 标明未完成。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    p = logs / 'job_recv.txt'
    fake = _FakeRedis()
    sent = []
    with _temp_recv(p, _hex_line(_can_frame())):
        resolved = str(resolve_play_path(p))
        h = rk.fileplay_path_hash(resolved)
        store.write_meta(
            fake,
            h,
            {'status': 'ready', 'type': 'BIU:FF', 'frameCount': 20000, 'frameCountExact': True, 'path': resolved},
            channel='curve',
        )
        fake.set(rk.fileplay_worker_status_key(h, 'curve'), '{"alive":true}')
        store.write_curve_chunk(fake, h, 0, [(1, {'X': 2.5})], channel='curve')

        class _Mgr:
            def send(self, msg):
                sent.append(msg)

        monkeypatch.setattr(
            'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
            classmethod(lambda cls, channel='curve': _Mgr()),
        )
        out = await PayloadFilePlayService.get_curve(
            _AsyncFakeRedis(fake),
            {
                'pathHash': h,
                'channel': 'curve',
                'items': [{'field': 'X'}],
                'startIndex': 0,
                'endIndex': 2,
            },
        )
        assert out['items'][0]['points'] == [[1, 2.5]]
        assert out['items'][0]['chunkPoints']['0'] == [[1, 2.5]]
        assert out['pendingChunks'] == [1]
        assert out['chunkCount'] == 2
        assert not out.get('error')
        assert sent and sent[0]['chunks'] == [1]

        store.write_curve_chunk(fake, h, 1, [(2, {'X': 3.5})], channel='curve')
        sent.clear()
        again = await PayloadFilePlayService.get_curve(
            _AsyncFakeRedis(fake),
            {
                'pathHash': h,
                'channel': 'curve',
                'items': [{'field': 'X', 'haveChunks': [0]}],
                'startIndex': 0,
                'endIndex': 2,
            },
        )
        assert again['items'][0]['points'] == [[2, 3.5]]
        assert again['items'][0]['chunkPoints'] == {'1': [[2, 3.5]]}
        assert again['pendingChunks'] == []
        assert sent == []

        idle = await PayloadFilePlayService.get_curve(
            _AsyncFakeRedis(fake),
            {
                'pathHash': h,
                'channel': 'curve',
                'items': [{'field': 'X', 'haveChunks': [0, 1]}],
                'startIndex': 0,
                'endIndex': 2,
            },
        )
        assert idle['items'][0]['points'] == []
        assert idle['items'][0]['chunkPoints'] == {}
        assert idle['pendingChunks'] == []


async def test_curve_status_does_not_decode_binary_chunk_as_frame(tmp_path: Path, monkeypatch) -> None:
    """曲线 data Hash 的字段是 zstd 块；二次 parse/status 不得当第 1 帧 UTF-8 解码。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    p = logs / 'curve_bin_recv.txt'
    fake = _FakeRedis()
    with _temp_recv(p, _hex_line(_can_frame())):
        resolved = str(resolve_play_path(p))
        h = rk.fileplay_path_hash(resolved)
        store.write_meta(
            fake,
            h,
            {
                'status': 'ready',
                'type': 'D9V17',
                'frameCount': 20000,
                'frameCountExact': True,
                'path': resolved,
            },
            channel='curve',
        )
        store.write_curve_chunk(fake, h, 1, [(10001, {'CAMF001': 1.0})], channel='curve')
        redis = _Utf8DecodingAsyncRedis(fake)
        st = await PayloadFilePlayService.get_status(redis, resolved, channel='curve')
        assert st['frameCount'] == 20000
        assert 'frame' not in st or st.get('frame') is None

        class _Mgr:
            def parse(self, *_a, **_k):
                raise AssertionError('不应再推 parse')

        monkeypatch.setattr(
            'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
            classmethod(lambda cls, channel='curve': _Mgr()),
        )
        out = await PayloadFilePlayService.parse(redis, 'D9V17', resolved, channel='curve')
        assert out['alreadyComplete'] is True
        assert out['frameCount'] == 20000


def test_parse_force_cancels_in_progress_scan(tmp_path: Path, monkeypatch) -> None:
    """force=1 取消正在扫描并重新 parse。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    monkeypatch.setattr('module_payload.fileplay.engine.parse_frame', _stub_parse_frame)
    gate = threading.Event()
    orig_finalize = finalize_exact_index

    def _blocked_finalize(idx, on_progress=None, should_stop=None):
        gate.wait(timeout=5)
        return orig_finalize(idx, on_progress=on_progress, should_stop=should_stop)

    monkeypatch.setattr('module_payload.fileplay.engine.finalize_exact_index', _blocked_finalize)
    p = logs / 'force_scan_recv.txt'
    body = _hex_line(_can_frame()) + _hex_line(_can_frame(payload=b'\xaa'))
    fake = _FakeRedis()
    engine = FilePlayEngine(fake)
    with _temp_recv(p, body):
        first = engine.parse('BIU:FF', str(p), force_estimate=True)
        assert first.get('alreadyParsing') is not True
        gen = engine._scan_gen
        second = engine.parse('BIU:FF', str(p), force_estimate=True, force=True, parse_id='force-1')
        assert second.get('alreadyParsing') is not True
        assert engine._scan_gen == gen + 1
        gate.set()
        if engine._scan_thread:
            engine._scan_thread.join(timeout=5)


def test_finalize_should_stop(tmp_path: Path) -> None:
    p = tmp_path / 'stop_recv.txt'
    body = _hex_line(_can_frame()) + _hex_line(_can_frame(payload=b'\xaa'))
    with _temp_recv(p, body):
        idx = index_file(p, 'BIU:FF', force_estimate=True)
        finalize_exact_index(idx, should_stop=lambda: True)
        assert idx.frame_count_exact is False


def test_parse_force_flag() -> None:
    from module_payload.fileplay.engine import parse_force

    assert parse_force(1) is True
    assert parse_force(True) is True
    assert parse_force('1') is True
    assert parse_force(0) is False
    assert parse_force(None) is False
    assert parse_force('0') is False


def test_engine_parse_keeps_other_hash(tmp_path: Path, monkeypatch) -> None:
    """解析另一文件不删前一个 pathHash 的缓存。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    monkeypatch.setattr('module_payload.fileplay.engine.parse_frame', _stub_parse_frame)
    a = logs / 'a_recv.txt'
    b = logs / 'b_recv.txt'
    fake = _FakeRedis()
    engine = FilePlayEngine(fake)
    with _temp_recv(a, _hex_line(_can_frame())), _temp_recv(b, _hex_line(_can_frame(payload=b'\xbb'))):
        engine.parse('BIU:FF', str(a))
        ha = rk.fileplay_path_hash(str(resolve_play_path(a)))
        assert store.read_meta(fake, ha) is not None
        engine.parse('BIU:FF', str(b))
        hb = rk.fileplay_path_hash(str(resolve_play_path(b)))
        assert store.read_meta(fake, ha) is not None
        assert store.read_meta(fake, hb)['status'] == 'ready'


def test_fileplay_chunk_is_msgpack_zstd() -> None:
    fake = _FakeRedis()
    h = 'abcd1234abcd1234'
    store.write_curve_chunk(fake, h, 0, [(10, {'J1': 1.5, 'J2': 2.0})], channel='curve')
    raw = fake.h[rk.fileplay_points_key(h, channel='curve')]['0']
    assert isinstance(raw, (bytes, bytearray))
    assert not str(raw).strip().startswith('[')
    assert store.read_curve_chunk(fake, h, 'J1', 0, channel='curve') == [[10, 1.5]]
    assert store.read_curve_chunk(fake, h, 'J2', 0, channel='curve') == [[10, 2.0]]


def test_curve_chunk_math() -> None:
    assert store.curve_chunk_count(0) == 0
    assert store.curve_chunk_count(1) == 1
    assert store.curve_chunk_count(10000) == 1
    assert store.curve_chunk_count(10001) == 2
    assert store.curve_chunk_count(432567) == 44
    assert store.curve_chunk_frames(0, 432567) == (1, 10000)
    assert store.curve_chunk_frames(43, 432567) == (430001, 432567)
    assert store.curve_chunks_requested({'startIndex': 0, 'endIndex': 2}, 432567) == [0, 1]


def test_curve_points_from_parsed_frames(tmp_path: Path, monkeypatch) -> None:
    """曲线按万点块写入 Hash，字段 0 表示第一块。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    monkeypatch.setattr('module_payload.fileplay.engine.parse_frame', _stub_parse_frame)
    p = logs / 'curve_recv.txt'
    body = _hex_line(_can_frame()) + _hex_line(_can_frame(payload=b'\xaa'))
    fake = _FakeRedis()
    engine = FilePlayEngine(fake)
    with _temp_recv(p, body):
        engine.parse('BIU:FF', str(p), force_estimate=False)
        h = rk.fileplay_path_hash(str(resolve_play_path(p)))
        if engine._scan_thread:
            engine._scan_thread.join(timeout=5)
        pts = engine.curve_points(h, ['X'], start_index=0, end_index=1)
        assert len(pts['X']) == 2
        assert pts['X'][0][1] == 1.0
        raw = store.read_curve_chunk(fake, h, 'X', 0, channel='history')
        assert raw == pts['X']
        assert store.read_frame(fake, h, 2)


def test_curve_points_reuses_parsed_frames(tmp_path: Path, monkeypatch) -> None:
    """块已在 Redis 则第二次不再 parse_frame。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    n = {'c': 0}

    def _count_parse(idx, i):
        n['c'] += 1
        return _stub_parse_frame(idx, i)

    monkeypatch.setattr('module_payload.fileplay.engine.parse_frame', _count_parse)
    p = logs / 'curve_cache_recv.txt'
    body = _hex_line(_can_frame()) + _hex_line(_can_frame(payload=b'\xaa'))
    fake = _FakeRedis()
    engine = FilePlayEngine(fake)
    with _temp_recv(p, body):
        engine.parse('BIU:FF', str(p), force_estimate=False)
        h = rk.fileplay_path_hash(str(resolve_play_path(p)))
        engine.curve_points(h, ['X'], chunks=[0])
        after_first = n['c']
        engine.curve_points(h, ['X'], chunks=[0])
        assert n['c'] == after_first
        assert store.curve_chunk_ready(fake, h, 0, channel='history')


def test_curve_channel_parse_does_not_write_frames(tmp_path: Path, monkeypatch) -> None:
    """曲线解析只写 meta，文件 Hash 里不应出现帧序号。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    monkeypatch.setattr('module_payload.fileplay.engine.parse_frame', _stub_parse_frame)
    p = logs / 'curve_only_recv.txt'
    fake = _FakeRedis()
    engine = FilePlayEngine(fake, channel='curve')
    with _temp_recv(p, _hex_line(_can_frame())):
        meta = engine.parse('BIU:FF', str(p), force_estimate=False)
        h = meta['pathHash']
        assert store.read_frame(fake, h, 1, channel='curve') is None
        assert rk.fileplay_hash_key(h, 'curve') not in fake.h


async def test_get_curve_spawns_when_worker_dead(tmp_path: Path, monkeypatch) -> None:
    """缺块且 worker 已退：通知 manager 再拉起，不空等。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    p = logs / 'dead_recv.txt'
    sent = []

    class _Mgr:
        def send(self, msg):
            sent.append(msg)
            return True

    monkeypatch.setattr(
        'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
        classmethod(lambda cls, channel='curve': _Mgr()),
    )
    fake = _FakeRedis()
    with _temp_recv(p, _hex_line(_can_frame())):
        h = rk.fileplay_path_hash(str(p))
        store.write_meta(fake, h, {'status': 'ready', 'type': 'D9V17', 'frameCount': 3}, channel='curve')
        t0 = time.monotonic()
        out = await PayloadFilePlayService.get_curve(
            _AsyncFakeRedis(fake),
            {'pathHash': h, 'channel': 'curve', 'items': [{'field': 'CAMF008'}]},
        )
        assert time.monotonic() - t0 < 0.5
        assert sent
        assert out['pendingChunks']


def test_history_parse_does_not_delete_curve(tmp_path: Path, monkeypatch) -> None:
    """历史文件数据切文件只删 history Hash，曲线频道数据必须还在。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    monkeypatch.setattr('module_payload.fileplay.engine.parse_frame', _stub_parse_frame)
    a = logs / 'hist_recv.txt'
    b = logs / 'other_recv.txt'
    fake = _FakeRedis()
    hist = FilePlayEngine(fake, channel='history')
    curv = FilePlayEngine(fake, channel='curve')
    with _temp_recv(a, _hex_line(_can_frame())), _temp_recv(b, _hex_line(_can_frame(payload=b'\xbb'))):
        hist.parse('BIU:FF', str(a), force_estimate=False)
        curv.parse('BIU:FF', str(a), force_estimate=False)
        ha = rk.fileplay_path_hash(str(resolve_play_path(a)))
        assert store.read_frame(fake, ha, 1, channel='history')
        assert store.read_frame(fake, ha, 1, channel='curve') is None
        hist.parse('BIU:FF', str(b), force_estimate=False)
        assert store.read_frame(fake, ha, 1, channel='history')
        assert store.read_meta(fake, ha, channel='curve')['status'] == 'ready'
        assert rk.fileplay_meta_key(ha, 'curve') in fake.kv


def test_curve_points_use_filename_start(tmp_path: Path, monkeypatch) -> None:
    """bin/无行内时间时，曲线 X 轴用文件名起始 + 1s/帧，避免落到 1970。"""

    def _stub(idx, n):
        return {
            'type': idx.table_type,
            'rows': [{'id': 'X', 'show': str(n), 'value': float(n)}],
            'frameIndex': n,
            'tsMs': 0,
        }

    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    monkeypatch.setattr('module_payload.fileplay.engine.parse_frame', _stub)
    p = logs / 'cam_20260824_103104_356_recv.txt'
    body = _hex_line(_can_frame()) + _hex_line(_can_frame(payload=b'\xaa'))
    fake = _FakeRedis()
    engine = FilePlayEngine(fake)
    with _temp_recv(p, body):
        start = parse_recv_file_start_ms(p)
        engine.parse('BIU:FF', str(p), force_estimate=False)
        h = rk.fileplay_path_hash(str(resolve_play_path(p)))
        pts = engine.curve_points(h, ['X'], chunks=[0])
        assert pts['X'][0][0] == start
        assert pts['X'][1][0] == start + 1000


def test_curve_points_keeps_other_chunks(tmp_path: Path, monkeypatch) -> None:
    """新块写入后，已有块仍在；同帧其它字段后写。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    monkeypatch.setattr(store, 'CURVE_CHUNK', 1)

    def _two_fields(idx, n):
        return {
            'type': idx.table_type,
            'rows': [
                {'id': 'CAMF008', 'value': float(n)},
                {'id': 'CAMF001', 'value': float(n) + 10},
            ],
            'frameIndex': n,
            'tsMs': n * 1000,
        }

    monkeypatch.setattr('module_payload.fileplay.engine.parse_frame', _two_fields)
    p = logs / 'curve_keep_recv.txt'
    body = _hex_line(_can_frame()) + _hex_line(_can_frame(payload=b'\xaa'))
    fake = _FakeRedis()
    engine = FilePlayEngine(fake, channel='curve')
    with _temp_recv(p, body):
        engine.parse('BIU:FF', str(p), force_estimate=False)
        h = rk.fileplay_path_hash(str(resolve_play_path(p)))
        engine.curve_points(h, ['CAMF008'], chunks=[0])
        engine.curve_points(h, ['CAMF008'], chunks=[1])
        assert store.curve_chunk_ready(fake, h, 0, channel='curve')
        assert store.curve_chunk_ready(fake, h, 1, channel='curve')
        assert store.read_curve_chunk(fake, h, 'CAMF001', 0, channel='curve')[0][1] == 11.0
        assert store.read_curve_chunk(fake, h, 'CAMF008', 0, channel='curve')[0][1] == 1.0
        data_hash = fake.h.get(rk.fileplay_hash_key(h, 'curve')) or {}
        assert '0' in data_hash and '1' in data_hash
        assert 'CAMF008' not in data_hash


def test_sql_patch_statements() -> None:
    """遥测菜单改名/删除/新增及角色授权补丁语句齐全。"""
    text = (Path(__file__).resolve().parents[1] / 'sql' / 'patch_telemetry_menu_20260826.sql').read_text(
        encoding='utf-8'
    )
    assert 'UPDATE sys_menu' in text
    assert '实时数据' in text
    assert 'DELETE FROM sys_menu WHERE menu_id = 2111' in text
    assert '2112' in text and '历史CAN数据' in text
    assert '2113' in text and '历史文件数据' in text
    assert '2114' in text and '历史文件曲线' in text
    assert 'INSERT IGNORE INTO sys_role_menu' in text
    assert 'role_id' in text


def test_two_hashes_coexist_after_parse(tmp_path: Path, monkeypatch) -> None:
    """两个文件解析后 Redis 里两份 meta 都在。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    monkeypatch.setattr('module_payload.fileplay.engine.parse_frame', _stub_parse_frame)
    a = logs / 'co_a_recv.txt'
    b = logs / 'co_b_recv.txt'
    fake = _FakeRedis()
    ea = FilePlayEngine(fake)
    eb = FilePlayEngine(fake)
    with _temp_recv(a, _hex_line(_can_frame())), _temp_recv(b, _hex_line(_can_frame(payload=b'\xbb'))):
        ea.parse('BIU:FF', str(a), force_estimate=False)
        eb.parse('BIU:FF', str(b), force_estimate=False)
        ha = rk.fileplay_path_hash(str(resolve_play_path(a)))
        hb = rk.fileplay_path_hash(str(resolve_play_path(b)))
        assert store.read_meta(fake, ha)['status'] == 'ready'
        assert store.read_meta(fake, hb)['status'] == 'ready'
        assert store.read_frame(fake, ha, 1)
        assert store.read_frame(fake, hb, 1)


async def test_service_parse_busy_when_manager_rejects(tmp_path: Path, monkeypatch) -> None:
    """第 6 个新文件：manager 拒绝 → busy。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    p = logs / 'busy_recv.txt'
    fake = _FakeRedis()

    class _Mgr:
        def parse(self, *_a, **_k):
            return False

    monkeypatch.setattr(
        'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
        classmethod(lambda cls, channel='history': _Mgr()),
    )
    with _temp_recv(p, _hex_line(_can_frame())):
        out = await PayloadFilePlayService.parse(_AsyncFakeRedis(fake), 'BIU:FF', str(p))
        assert out['status'] == 'busy'
        assert '5' in (out.get('error') or '')


def test_manager_slot_share_and_sixth_reject(monkeypatch) -> None:
    """同 hash 不占第二槽；第 6 个新 hash 拒绝。"""
    from module_payload.fileplay.manager import FilePlayManager

    FilePlayManager._instances.clear()
    fake = _FakeRedis()
    monkeypatch.setattr('module_payload.collectors.redis_sync.create_sync_redis', lambda: fake)
    monkeypatch.setattr(
        'module_payload.collectors.process_guard.install_shutdown_hooks',
        lambda *_a, **_k: None,
    )
    mgr = FilePlayManager()
    mgr._redis = fake
    from unittest.mock import MagicMock

    for i in range(5):
        proc = MagicMock()
        proc.poll.return_value = None
        mgr._procs[f'{i:016x}'] = proc
    assert mgr.worker_count() == 5
    assert mgr.can_accept('0000000000000000') is True
    assert mgr.can_accept('ffffffffffffffff') is False
    assert mgr.parse('BIU:FF', '/no/such/file_recv.txt') is False


def test_janitor_sweep_expires_idle_hash(monkeypatch) -> None:
    """touch 超过 1 小时则删该 hash 缓存。"""
    from module_payload.fileplay.janitor import sweep_idle

    fake = _FakeRedis()
    h = 'abcdabcdabcdabcd'
    store.write_meta(fake, h, {'status': 'ready', 'frameCount': 1, 'frameCountExact': True})
    fake.set(rk.fileplay_touch_key(h), str(int(time.time()) - 4000))
    killed: list[str] = []

    class _Mgr:
        def kill(self, hh):
            killed.append(hh)

    monkeypatch.setattr(
        'module_payload.fileplay.manager.FilePlayManager.instance',
        classmethod(lambda cls, channel='history': _Mgr()),
    )
    n = sweep_idle(fake, now=int(time.time()), idle_s=3600)
    assert n >= 1
    assert store.read_meta(fake, h) is None
    assert h in killed


def test_ensure_worker_does_not_clear_channel(monkeypatch) -> None:
    """拉起子进程不得 clear_channel。"""
    from unittest.mock import MagicMock, patch

    from module_payload.fileplay.manager import FilePlayManager

    FilePlayManager._instances.clear()
    fake = _FakeRedis()
    h = 'aabbccddeeff0011'
    monkeypatch.setattr('module_payload.collectors.redis_sync.create_sync_redis', lambda: fake)
    monkeypatch.setattr(
        'module_payload.collectors.process_guard.install_shutdown_hooks',
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr('module_payload.collectors.process_guard.assign_to_kill_job', lambda *_a, **_k: None)
    fake.set(rk.fileplay_worker_status_key(h), '{"alive":true}')
    alive = MagicMock()
    alive.poll.return_value = None
    mgr = FilePlayManager()
    mgr._redis = fake
    with (
        patch('subprocess.Popen', return_value=alive),
        patch.object(store, 'clear_channel') as clr,
    ):
        mgr.ensure_worker(h)
        clr.assert_not_called()
    assert mgr._is_alive(h)


def test_engine_fills_all_frames_after_index(tmp_path: Path, monkeypatch) -> None:
    """精确索引后继续把剩余帧写入 Redis，parsedDone 才表示全部解码。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    monkeypatch.setattr('module_payload.fileplay.engine.parse_frame', _stub_parse_frame)
    p = logs / 'fill_all_recv.txt'
    body = _hex_line(_can_frame()) + _hex_line(_can_frame(payload=b'\xaa'))
    fake = _FakeRedis()
    engine = FilePlayEngine(fake)
    with _temp_recv(p, body):
        meta = engine.parse('BIU:FF', str(p), force_estimate=False)
        assert meta.get('frameCountExact') is True
        assert meta.get('parsedDone') is not True
        if engine._scan_thread:
            engine._scan_thread.join(timeout=5)
        h = rk.fileplay_path_hash(str(resolve_play_path(p)))
        assert store.stored_frame_count(fake, h) == 2
        got = store.read_meta(fake, h)
        assert got['parsedDone'] is True
        assert engine.all_frames_parsed() is True


def test_worker_stays_until_all_frames_parsed(monkeypatch) -> None:
    """索引完成不等于退出；all_frames_parsed 之前继续 fill。"""
    from unittest.mock import MagicMock, patch

    from module_payload.fileplay import worker as w

    fake = _FakeRedis()
    eng = MagicMock()
    eng.all_frames_parsed.side_effect = [False, False, True]
    fake._brpop_queue = [None, None]
    monkeypatch.setattr(w, '_bootstrap', lambda: None)
    monkeypatch.setattr(w.sys, 'argv', ['worker.py', 'history', 'aabbccddeeff0011'])
    monkeypatch.setattr('module_payload.collectors.redis_sync.create_sync_redis', lambda: fake)
    monkeypatch.setattr('module_payload.fileplay.engine.FilePlayEngine', lambda redis, channel='history', **k: eng)
    with patch('time.sleep', return_value=None):
        w.main()
    assert eng.fill_missing_frames.call_count >= 3
    assert eng.all_frames_parsed.call_count >= 3
    meta = store.read_meta(fake, 'aabbccddeeff0011')
    assert meta and meta.get('parsedDone') is True


async def test_list_sessions_merges_cache_and_live(tmp_path: Path, monkeypatch) -> None:
    """列表 = Redis meta ∪ 活进程；关进程不删缓存，清缓存不杀进程。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    p = logs / 'sess_recv.txt'
    fake = _FakeRedis()
    with _temp_recv(p, _hex_line(_can_frame())):
        resolved = str(resolve_play_path(p))
        h = rk.fileplay_path_hash(resolved)
        store.write_meta(
            fake,
            h,
            {
                'status': 'ready',
                'type': 'BIU:FF',
                'path': resolved,
                'frameCount': 12,
                'frameCountExact': True,
                'parsedDone': True,
                'startedAt': 1700000000,
            },
        )
        fake.set(rk.fileplay_touch_key(h, 'history'), '1700000100')
        live_h = '1111222233334444'
        killed: list[str] = []

        class _Mgr:
            def list_live(self):
                return [{'pathHash': live_h, 'startedAt': 1700000200, 'alive': True}]

            def kill(self, path_hash):
                killed.append(path_hash)

        monkeypatch.setattr(
            'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
            classmethod(lambda cls, channel='history': _Mgr()),
        )
        monkeypatch.setattr(
            'module_payload.collectors.redis_sync.create_sync_redis',
            lambda: fake,
        )
        out = await PayloadFilePlayService.list_sessions(_AsyncFakeRedis(fake), 'history')
        hashes = {x['pathHash'] for x in out['items']}
        assert h in hashes
        assert live_h in hashes
        cached = next(x for x in out['items'] if x['pathHash'] == h)
        assert cached['fileStatus'] == '已完成'
        assert cached['procStatus'] == '已退出'
        live = next(x for x in out['items'] if x['pathHash'] == live_h)
        assert live['fileStatus'] == '解析中'
        assert live['procStatus'] == '运行中'

        PayloadFilePlayService.close_session(h, 'history')
        assert killed == [h]
        assert store.read_meta(fake, h)

        await PayloadFilePlayService.clear_session(_AsyncFakeRedis(fake), h, 'history')
        assert store.read_meta(fake, h) is None
        assert killed == [h]


async def test_list_sessions_curve_complete_when_all_chunks_ready(monkeypatch) -> None:
    """曲线块齐了即使 meta.parsedDone 仍假，列表文件状态也应是已完成。"""
    fake = _FakeRedis()
    h = 'a918bb4bc7c3193d'
    store.write_meta(
        fake,
        h,
        {
            'status': 'ready',
            'type': 'D9V17',
            'path': r'E:\plat\logs\a_recv.bin',
            'frameCount': 152419,
            'frameCountExact': True,
            'parsedDone': False,
            'startedAt': 1700000000,
        },
        channel='curve',
    )
    key = rk.fileplay_hash_key(h, 'curve')
    for i in range(16):
        fake.hset(key, str(i), b'x')

    class _Mgr:
        def list_live(self):
            return [{'pathHash': h, 'startedAt': 1700000000, 'alive': True}]

    monkeypatch.setattr(
        'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
        classmethod(lambda cls, channel='history': _Mgr()),
    )
    out = await PayloadFilePlayService.list_sessions(_AsyncFakeRedis(fake), 'curve')
    row = next(x for x in out['items'] if x['pathHash'] == h)
    assert row['fileStatus'] == '已完成'
    assert row['parsedDone'] is True
    assert row['procStatus'] == '空闲'
    assert row['frameCount'] == 152419


async def test_list_sessions_curve_parsing_when_chunks_missing(monkeypatch) -> None:
    """精确帧数已有但万帧块不齐，文件状态仍是解析中。"""
    fake = _FakeRedis()
    h = 'bbbbbbbbbbbbbbbb'
    store.write_meta(
        fake,
        h,
        {
            'status': 'ready',
            'frameCount': 152419,
            'frameCountExact': True,
            'parsedDone': False,
            'startedAt': 1,
        },
        channel='curve',
    )
    fake.hset(rk.fileplay_hash_key(h, 'curve'), '0', b'x')

    class _Mgr:
        def list_live(self):
            return [{'pathHash': h, 'startedAt': 1, 'alive': True}]

    monkeypatch.setattr(
        'module_payload.service.payload_fileplay_service.FilePlayManager.instance',
        classmethod(lambda cls, channel='history': _Mgr()),
    )
    out = await PayloadFilePlayService.list_sessions(_AsyncFakeRedis(fake), 'curve')
    row = next(x for x in out['items'] if x['pathHash'] == h)
    assert row['fileStatus'] == '解析中'
    assert row['parsedDone'] is False
    assert row['procStatus'] == '运行中'


def test_engine_curve_all_frames_parsed_uses_chunk_count() -> None:
    """曲线完成看万帧块数，不能拿 Hash 字段数去比总帧数。"""
    from types import SimpleNamespace

    fake = _FakeRedis()
    engine = FilePlayEngine(fake, channel='curve')
    engine._path_hash = 'abcdabcdabcdabcd'
    engine._idx = SimpleNamespace(frame_count=10001, frame_count_exact=True)
    assert engine.all_frames_parsed() is False
    key = rk.fileplay_hash_key('abcdabcdabcdabcd', 'curve')
    fake.hset(key, '0', b'a')
    assert engine.all_frames_parsed() is False
    fake.hset(key, '1', b'b')
    assert engine.all_frames_parsed() is True


def test_worker_curve_sets_parsed_done_when_chunks_ready(monkeypatch) -> None:
    """曲线块写齐且队列空时写 parsedDone 并退出。"""
    from unittest.mock import MagicMock, patch

    from module_payload.fileplay import worker as w

    fake = _FakeRedis()
    eng = MagicMock()
    eng.all_frames_parsed.side_effect = [False, True]
    fake._brpop_queue = [None]
    monkeypatch.setattr(w, '_bootstrap', lambda: None)
    monkeypatch.setattr(w.sys, 'argv', ['worker.py', 'curve', 'aabbccddeeff0011'])
    monkeypatch.setattr('module_payload.collectors.redis_sync.create_sync_redis', lambda: fake)
    monkeypatch.setattr('module_payload.fileplay.engine.FilePlayEngine', lambda redis, channel='history', **k: eng)
    with patch('time.sleep', return_value=None):
        w.main()
    assert eng.fill_missing_frames.call_count == 0
    meta = store.read_meta(fake, 'aabbccddeeff0011', channel='curve')
    assert meta and meta.get('parsedDone') is True


def test_manager_list_live_includes_local(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from module_payload.fileplay.manager import FilePlayManager

    FilePlayManager._instances.clear()
    mgr = FilePlayManager()
    mgr._started_at['abcd'] = 123
    proc = MagicMock()
    proc.poll.return_value = None
    mgr._procs['abcd'] = proc
    rows = mgr.list_live()
    assert rows and rows[0]['pathHash'] == 'abcd'
    assert rows[0]['alive'] is True

