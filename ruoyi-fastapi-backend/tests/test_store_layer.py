"""H4 store 层回归：与搬迁前 Redis 键、过滤规则、会话 GET 行为一致。"""

from __future__ import annotations

from unittest.mock import MagicMock

from module_payload import redis_keys as rk
from module_payload.constants import SRC_KIND_UDP
from module_payload.store.archive_queue import build_archive_event, bytes_to_raw_hex, enqueue_sync
from module_payload.store.error_store import normalize_error_type, push_pipeline_error
from module_payload.store.jsonutil import dumps_json, loads_json
from module_payload.store.session_store import delete_session_sync, get_session_sync, loads_session
from module_payload.collectors.redis_sync import dumps_json as redis_sync_dumps


class _MemRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, val: str, ex=None) -> None:
        self.store[key] = val

    def delete(self, key: str) -> None:
        self.store.pop(key, None)

    def lpush(self, key: str, val: str) -> None:
        self.lists.setdefault(key, []).insert(0, val)


def test_jsonutil_matches_redis_sync_reexport() -> None:
    payload = {'中': '文', 'n': 1}
    assert dumps_json(payload) == redis_sync_dumps(payload)
    assert loads_json('') is None
    assert loads_json(dumps_json(payload)) == payload


def test_error_store_same_keys_as_before() -> None:
    redis = MagicMock()
    push_pipeline_error(
        redis,
        stage='assembler',
        message='组帧失败',
        device_id='serial:COM4',
        assembler_id='camera_image_d6',
        data_len=10,
    )
    pipe = redis.pipeline.return_value
    dumped = pipe.set.call_args_list[0].args[1]
    pipe.set.assert_any_call(rk.error_type_latest_key('assembler'), dumped)
    pipe.set.assert_any_call(rk.assembled_error_key('serial:COM4'), dumped)
    assert normalize_error_type('parser') == 'tm'


def test_error_store_shim_reexports() -> None:
    from module_payload.service.payload_error_store import push_pipeline_error as shim

    assert shim is push_pipeline_error


def test_session_store_get_delete() -> None:
    r = _MemRedis()
    key = rk.session_key(SRC_KIND_UDP, 'udp:127.0.0.1:9000')
    r.set(key, dumps_json({'srcParam': 'udp:127.0.0.1:9000', 'source': 'home'}))
    got = get_session_sync(r, 'udp:127.0.0.1:9000', SRC_KIND_UDP)
    assert got['source'] == 'home'
    delete_session_sync(r, 'udp:127.0.0.1:9000', SRC_KIND_UDP)
    assert get_session_sync(r, 'udp:127.0.0.1:9000', SRC_KIND_UDP) is None
    assert loads_session(None) is None
    assert loads_session(b'{"a":1}') == {'a': 1}


def test_archive_queue_can_only() -> None:
    redis = MagicMock()
    enqueue_sync(
        redis,
        {'ts_ms': 1, 'points': {}, 'src_kind': 'can', 'src_param': 'can:3:0:0', 'parser_id': 'tm_can_biu'},
    )
    redis.lpush.assert_called()
    redis.reset_mock()
    enqueue_sync(
        redis,
        {
            'ts_ms': 1,
            'points': {},
            'src_kind': 'serial',
            'src_param': 'serial:COM3',
            'parser_id': 'camera_sc_link41ep',
        },
    )
    redis.lpush.assert_not_called()
    ev = build_archive_event(
        ts_ms=1000,
        raw_frame=b'\xaa\xbb',
        points={'J1': 1.5},
        data_sub='ff',
        src_param='can:3:0:0',
        name='快遥',
    )
    assert ev['raw_hex'] == 'AA BB'
    assert bytes_to_raw_hex(b'\xaa\xbb') == 'AA BB'


def test_archive_service_delegates_enqueue() -> None:
    from module_payload.service.payload_telemetry_archive_service import PayloadTelemetryArchiveService

    redis = MagicMock()
    PayloadTelemetryArchiveService.enqueue_sync(
        redis, {'ts_ms': 1, 'points': {}, 'src_kind': 'can', 'src_param': 'can:3:0:0', 'parser_id': 'tm_can_biu'}
    )
    redis.lpush.assert_called()
