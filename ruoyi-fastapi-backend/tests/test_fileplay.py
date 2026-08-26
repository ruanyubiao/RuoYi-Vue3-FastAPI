"""文件回放单测：侦测/拆帧、路径白名单、独立 Hash、取帧带总数、菜单 SQL。

样本一律写在 pytest ``tmp_path``（或由其映射出的回放根）里，测完删除，
不得落到真实 ``logs_data`` / ``upload_path/log_data``。
引擎生产默认 force_estimate=True（先 ready 再后台精确计数）；需要立即精确帧数的用例
显式传 force_estimate=False。
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from module_payload import redis_keys as rk
from module_payload.cfg.can_yc_frame import CAN_YC_FRAME_TYPE_COMPLEX
from module_payload.fileplay import store
from datetime import datetime

from module_payload.fileplay.detect import (
    FileIndex,
    detect_file_kind,
    estimate_frame_count,
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
    """同步 Redis Hash 替身：fileplay 引擎/store 只用 hset/hget/delete。"""

    def __init__(self) -> None:
        self.h: dict[str, dict[str, str]] = {}

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


class _AsyncFakeRedis:
    """服务层 async Redis 替身，内部复用 ``_FakeRedis``。"""

    def __init__(self, inner: _FakeRedis | None = None) -> None:
        self.inner = inner or _FakeRedis()

    async def hget(self, key, field):
        return self.inner.hget(key, field)

    async def hset(self, key, field=None, value=None, mapping=None):
        return self.inner.hset(key, field=field, value=value, mapping=mapping)

    async def expire(self, key, ttl):
        return True


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
    """超长/强制预估：先按「大小/首帧长」估帧数，扫完后改精确。"""
    p = tmp_path / 'est_recv.txt'
    body = _hex_line(_can_frame(0xFF, b'\x01\x02')) + _hex_line(_can_frame(0xFF, b'\x03\x04'))
    with _temp_recv(p, body):
        idx = index_file(p, 'BIU:FF', force_estimate=True)
        assert idx.frame_count_exact is False
        assert idx.frame_count == estimate_frame_count(idx.size, idx.first_frame_len)
        assert idx.frame_count >= 1
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
    assert ingest_kind('XL:RKDJ') == 'board'
    rows = fields_to_rows([{'id': 'A1', 'name': '电流', 'show': '1.2', 'value': 1.2, 'unit': 'A', 'hex': '01'}])
    assert rows[0]['id'] == 'A1'
    assert rows[0]['show'] == '1.2'
    assert rows[0]['unit'] == 'A'


def test_fileplay_hash_isolated_from_live_tm() -> None:
    """文件会话 key 必须是 payload:fileplay:*，禁止 payload:tm:*。"""
    h = rk.fileplay_path_hash('/tmp/x_recv.txt')
    key = rk.fileplay_hash_key(h)
    assert key.startswith('payload:fileplay:')
    store.assert_not_live_tm_key(key)
    with pytest.raises(RuntimeError, match='实时遥测'):
        store.assert_not_live_tm_key('payload:tm:FF:latest')


def test_store_meta_frame_roundtrip() -> None:
    """Hash 读写 meta / f:{n}，切会话 DEL 整个 key。"""
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
        assert all(k.startswith('payload:fileplay:') for k in fake.h)


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
        classmethod(lambda cls: _SilentMgr()),
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


def test_engine_switch_file_drops_old_hash(tmp_path: Path, monkeypatch) -> None:
    """切文件时 DEL 旧会话 Hash，避免串数据。"""
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
        assert store.read_meta(fake, ha) is None
        assert store.read_meta(fake, hb)['status'] == 'ready'


def test_curve_points_from_parsed_frames(tmp_path: Path, monkeypatch) -> None:
    """曲线从已解析帧抽数值点，写入 Hash 子字段 c:{field}。"""
    logs, _upload = _patch_play_roots(tmp_path, monkeypatch)
    monkeypatch.setattr('module_payload.fileplay.engine.parse_frame', _stub_parse_frame)
    p = logs / 'curve_recv.txt'
    body = _hex_line(_can_frame()) + _hex_line(_can_frame(payload=b'\xaa'))
    fake = _FakeRedis()
    engine = FilePlayEngine(fake)
    with _temp_recv(p, body):
        engine.parse('BIU:FF', str(p), force_estimate=False)
        h = rk.fileplay_path_hash(str(resolve_play_path(p)))
        pts = engine.curve_points(h, ['X'], start_index=1, end_index=2)
        assert len(pts['X']) == 2
        assert pts['X'][0][1] == 1.0
        raw = fake.hget(rk.fileplay_hash_key(h), 'c:X')
        assert store.loads(raw) == pts['X']


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
        pts = engine.curve_points(h, ['X'], start_index=1, end_index=2)
        assert pts['X'][0][0] == start
        assert pts['X'][1][0] == start + 1000


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
