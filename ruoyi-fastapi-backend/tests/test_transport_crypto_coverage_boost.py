"""Raise coverage of transport crypto util + middleware toward 99%+."""

from __future__ import annotations

import base64
import json
import os
import secrets
import time
from collections import Counter, defaultdict, deque
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from starlette.testclient import TestClient

from config.env import AppConfig, TransportCryptoConfig
from middlewares.transport_crypto_middleware import (
    TransportCryptoMiddleware,
    add_transport_crypto_middleware,
)
from utils.transport_crypto_util import (
    TransportCryptoMonitorUtil,
    TransportCryptoUtil,
    TransportKeyProvider,
    TransportSecurityUtil,
    _urlsafe_b64decode,
    _urlsafe_b64encode,
)


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


def _gen_rsa_pem(key_size: int = 2048) -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode('utf-8')
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode('utf-8')
    )
    return private_pem, public_pem


PRIVATE_KEY_PEM, PUBLIC_KEY_PEM = _gen_rsa_pem()
LEGACY_PRIVATE_PEM, LEGACY_PUBLIC_PEM = _gen_rsa_pem()
KID = 'default'
ALG = 'RSA_OAEP_AES_256_GCM'


def _reset_key_provider() -> None:
    TransportKeyProvider._key_pairs = None


def _reset_monitor() -> None:
    with TransportCryptoMonitorUtil._lock:
        TransportCryptoMonitorUtil._counters = Counter()
        TransportCryptoMonitorUtil._failure_reasons = Counter()
        TransportCryptoMonitorUtil._kid_counters = defaultdict(Counter)
        TransportCryptoMonitorUtil._recent_failures = deque(
            maxlen=TransportCryptoMonitorUtil._RECENT_FAILURE_LIMIT
        )
        TransportCryptoMonitorUtil._last_redis_warning_at = 0.0
        TransportCryptoMonitorUtil._started_at = datetime.now()


@contextmanager
def crypto_config(**overrides: Any):
    originals: dict[str, Any] = {}
    app_originals: dict[str, Any] = {}
    _reset_key_provider()
    try:
        for key, value in overrides.items():
            if key.startswith('app_'):
                attr = key[len('app_') :]
                app_originals[attr] = getattr(AppConfig, attr)
                setattr(AppConfig, attr, value)
            else:
                originals[key] = getattr(TransportCryptoConfig, key)
                setattr(TransportCryptoConfig, key, value)
        yield
    finally:
        for key, value in originals.items():
            setattr(TransportCryptoConfig, key, value)
        for key, value in app_originals.items():
            setattr(AppConfig, key, value)
        _reset_key_provider()


def _default_crypto_kwargs(**extra: Any) -> dict[str, Any]:
    base = {
        'transport_crypto_enabled': True,
        'transport_crypto_mode': 'optional',
        'transport_crypto_algorithm': ALG,
        'transport_crypto_kid': KID,
        'transport_crypto_public_key': PUBLIC_KEY_PEM,
        'transport_crypto_private_key': PRIVATE_KEY_PEM,
        'transport_crypto_legacy_key_pairs': '[]',
        'transport_crypto_rsa_key_size': 2048,
        'transport_crypto_clock_skew_seconds': 120,
        'transport_crypto_replay_ttl_seconds': 300,
        'transport_crypto_enabled_paths': '',
        'transport_crypto_required_paths': '',
        'transport_crypto_exclude_paths': '/health,/transport/crypto/public-key',
        'transport_crypto_public_key_ttl_seconds': 3600,
        'transport_crypto_frontend_config_ttl_seconds': 300,
        'transport_crypto_max_get_url_length': 4096,
    }
    base.update(extra)
    return base


def build_envelope(
    plaintext: bytes,
    *,
    method: str = 'POST',
    path: str = '/api/data',
    kid: str = KID,
    public_key_pem: str = PUBLIC_KEY_PEM,
    timestamp: int | None = None,
    nonce: str | None = None,
    **field_overrides: Any,
) -> tuple[dict[str, Any], bytes]:
    aes_key = os.urandom(32)
    iv = os.urandom(12)
    aad = {'method': method.upper(), 'path': path}
    ciphertext = AESGCM(aes_key).encrypt(
        iv, plaintext, json.dumps(aad, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    )
    public_key = serialization.load_pem_public_key(public_key_pem.encode('utf-8'))
    encrypted_key = public_key.encrypt(
        aes_key,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    envelope: dict[str, Any] = {
        'v': '1',
        'kid': kid,
        'alg': ALG,
        'ts': timestamp if timestamp is not None else int(time.time()),
        'nonce': nonce or secrets.token_urlsafe(16),
        'ek': _urlsafe_b64encode(encrypted_key),
        'iv': _urlsafe_b64encode(iv),
        'ct': _urlsafe_b64encode(ciphertext),
        'aad': aad,
    }
    envelope.update(field_overrides)
    return envelope, aes_key


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.ops: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def set(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self.ops.append(('set', args, kwargs))
        return self

    def hincrby(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self.ops.append(('hincrby', args, kwargs))
        return self

    def sadd(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self.ops.append(('sadd', args, kwargs))
        return self

    def lpush(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self.ops.append(('lpush', args, kwargs))
        return self

    def ltrim(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self.ops.append(('ltrim', args, kwargs))
        return self

    def get(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self.ops.append(('get', args, kwargs))
        return self

    def hgetall(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self.ops.append(('hgetall', args, kwargs))
        return self

    def lrange(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self.ops.append(('lrange', args, kwargs))
        return self

    def smembers(self, *args: Any, **kwargs: Any) -> FakePipeline:
        self.ops.append(('smembers', args, kwargs))
        return self

    async def __aenter__(self) -> FakePipeline:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def execute(self) -> list[Any]:
        if self.redis.pipeline_fail:
            raise RuntimeError('pipeline boom')
        results: list[Any] = []
        for op, args, kwargs in self.ops:
            if op == 'set':
                key, value = args[0], args[1]
                nx = kwargs.get('nx', False)
                if nx and key in self.redis.kv:
                    results.append(False)
                else:
                    self.redis.kv[key] = value
                    results.append(True)
            elif op == 'hincrby':
                key, field, delta = args
                bucket = self.redis.hashes.setdefault(key, {})
                bucket[field] = int(bucket.get(field, 0)) + int(delta)
                results.append(bucket[field])
            elif op == 'sadd':
                key, member = args[0], args[1]
                self.redis.sets.setdefault(key, set()).add(member)
                results.append(1)
            elif op == 'lpush':
                key, value = args[0], args[1]
                self.redis.lists.setdefault(key, []).insert(0, value)
                results.append(len(self.redis.lists[key]))
            elif op == 'ltrim':
                key, start, end = args
                values = self.redis.lists.get(key, [])
                self.redis.lists[key] = values[start : end + 1]
                results.append(True)
            elif op == 'get':
                results.append(self.redis.kv.get(args[0]))
            elif op == 'hgetall':
                results.append(dict(self.redis.hashes.get(args[0], {})))
            elif op == 'lrange':
                key, start, end = args
                values = self.redis.lists.get(key, [])
                if end == -1:
                    results.append(list(values[start:]))
                else:
                    results.append(list(values[start : end + 1]))
            elif op == 'smembers':
                results.append(set(self.redis.sets.get(args[0], set())))
            else:
                results.append(None)
        return results


class FakeRedis:
    def __init__(self, *, set_fail: bool = False, pipeline_fail: bool = False) -> None:
        self.kv: dict[str, Any] = {}
        self.hashes: dict[str, dict[str, Any]] = {}
        self.sets: dict[str, set[Any]] = {}
        self.lists: dict[str, list[Any]] = {}
        self.set_fail = set_fail
        self.pipeline_fail = pipeline_fail

    async def set(self, key: str, value: Any, ex: int | None = None, nx: bool = False) -> bool:
        if self.set_fail:
            raise RuntimeError('redis set failed')
        if nx and key in self.kv:
            return False
        self.kv[key] = value
        return True

    def pipeline(self, transaction: bool = False) -> FakePipeline:
        return FakePipeline(self)


def _make_request(
    *,
    path: str = '/api/data',
    method: str = 'POST',
    redis: Any = None,
    app_root: str = '',
) -> Request:
    app = SimpleNamespace(state=SimpleNamespace(redis=redis))
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0'},
        'http_version': '1.1',
        'method': method,
        'scheme': 'http',
        'path': path,
        'raw_path': path.encode(),
        'query_string': b'',
        'headers': [],
        'client': ('127.0.0.1', 12345),
        'server': ('testserver', 80),
        'root_path': app_root,
        'app': app,
    }
    return Request(scope)


def _crypto_app(
    *,
    redis: Any = None,
    include_text: bool = True,
) -> FastAPI:
    app = FastAPI()
    if redis is not None:
        app.state.redis = redis
    else:
        app.state.redis = None

    @app.post('/api/data')
    async def post_data(request: Request) -> dict[str, Any]:
        body = await request.body()
        return {'echo': body.decode('utf-8') if body else '', 'q': dict(request.query_params)}

    @app.get('/api/data')
    async def get_data(request: Request) -> dict[str, Any]:
        return {'q': dict(request.query_params)}

    @app.post('/api/form')
    async def post_form(request: Request) -> dict[str, Any]:
        form = await request.form()
        return {'form': {k: v for k, v in form.items()}}

    @app.post('/secure/secret')
    async def secure() -> dict[str, str]:
        return {'ok': '1'}

    @app.get('/health')
    async def health() -> dict[str, str]:
        return {'status': 'up'}

    @app.get('/other')
    async def other() -> dict[str, str]:
        return {'status': 'other'}

    if include_text:

        @app.post('/api/text')
        async def text_endpoint() -> PlainTextResponse:
            return PlainTextResponse('plain-text')

    app.add_middleware(TransportCryptoMiddleware)
    return app


# ---------------------------------------------------------------------------
# urlsafe helpers
# ---------------------------------------------------------------------------


def test_urlsafe_b64_roundtrip() -> None:
    raw = b'hello-world\x00\xff'
    encoded = _urlsafe_b64encode(raw)
    assert '=' not in encoded
    assert _urlsafe_b64decode(encoded) == raw
    assert _urlsafe_b64decode(base64.urlsafe_b64encode(raw).decode()) == raw


# ---------------------------------------------------------------------------
# TransportKeyProvider
# ---------------------------------------------------------------------------


def test_key_provider_validate_disabled_or_off() -> None:
    with crypto_config(**_default_crypto_kwargs(transport_crypto_enabled=False)):
        TransportKeyProvider.validate_runtime_configuration()
    with crypto_config(**_default_crypto_kwargs(transport_crypto_mode='off')):
        TransportKeyProvider.validate_runtime_configuration()


def test_key_provider_validate_rsa_size_and_missing_keys() -> None:
    with crypto_config(**_default_crypto_kwargs(transport_crypto_rsa_key_size=1024)):
        with pytest.raises(ValueError, match='RSA_KEY_SIZE'):
            TransportKeyProvider.validate_runtime_configuration()
    with crypto_config(**_default_crypto_kwargs(transport_crypto_rsa_key_size=2300)):
        with pytest.raises(ValueError, match='RSA_KEY_SIZE'):
            TransportKeyProvider.validate_runtime_configuration()
    with crypto_config(**_default_crypto_kwargs(transport_crypto_private_key='', transport_crypto_public_key='')):
        with pytest.raises(ValueError, match='必须显式配置'):
            TransportKeyProvider.validate_runtime_configuration()


def test_key_provider_validate_mismatched_and_legacy() -> None:
    with crypto_config(
        **_default_crypto_kwargs(
            transport_crypto_public_key=LEGACY_PUBLIC_PEM,
            transport_crypto_private_key=PRIVATE_KEY_PEM,
        )
    ):
        with pytest.raises(ValueError, match='不匹配'):
            TransportKeyProvider.validate_runtime_configuration()

    legacy = json.dumps(
        [{'kid': 'legacy', 'privateKey': LEGACY_PRIVATE_PEM, 'publicKey': LEGACY_PUBLIC_PEM}]
    )
    with crypto_config(**_default_crypto_kwargs(transport_crypto_legacy_key_pairs=legacy)):
        TransportKeyProvider.validate_runtime_configuration()


def test_key_provider_getters_and_missing_kid() -> None:
    with crypto_config(**_default_crypto_kwargs()):
        pair = TransportKeyProvider.get_current_key_pair()
        assert pair.kid == KID
        assert TransportKeyProvider.get_current_kid() == KID
        assert 'BEGIN PUBLIC KEY' in TransportKeyProvider.get_public_key_pem()
        assert 'BEGIN PRIVATE KEY' in TransportKeyProvider.get_private_key_pem(KID)
        assert KID in TransportKeyProvider.get_supported_kids()
        with pytest.raises(ValueError, match='密钥版本不存在'):
            TransportKeyProvider.get_key_pair('missing')


def test_key_provider_build_key_pairs_requires_keys() -> None:
    with crypto_config(**_default_crypto_kwargs(transport_crypto_private_key='', transport_crypto_public_key='')):
        with pytest.raises(ValueError, match='必须显式配置'):
            TransportKeyProvider._build_key_pairs()


def test_key_provider_legacy_variants() -> None:
    with crypto_config(**_default_crypto_kwargs(transport_crypto_legacy_key_pairs='')):
        assert TransportKeyProvider._build_legacy_key_pairs() == {}

    with crypto_config(**_default_crypto_kwargs(transport_crypto_legacy_key_pairs='{bad')):
        with pytest.raises(ValueError, match='合法JSON'):
            TransportKeyProvider._build_legacy_key_pairs()

    with crypto_config(**_default_crypto_kwargs(transport_crypto_legacy_key_pairs='{"a":1}')):
        with pytest.raises(ValueError, match='JSON数组'):
            TransportKeyProvider._build_legacy_key_pairs()

    with crypto_config(**_default_crypto_kwargs(transport_crypto_legacy_key_pairs='[1]')):
        with pytest.raises(ValueError, match='JSON对象'):
            TransportKeyProvider._build_legacy_key_pairs()

    with crypto_config(
        **_default_crypto_kwargs(transport_crypto_legacy_key_pairs='[{"kid":"","privateKey":""}]')
    ):
        with pytest.raises(ValueError, match='kid和privateKey'):
            TransportKeyProvider._build_legacy_key_pairs()

    # derive public from private; accept private_key / public_key aliases
    legacy = json.dumps([{'kid': 'old', 'private_key': LEGACY_PRIVATE_PEM.replace('\n', '\\n')}])
    with crypto_config(**_default_crypto_kwargs(transport_crypto_legacy_key_pairs=legacy)):
        pairs = TransportKeyProvider._build_legacy_key_pairs()
        assert 'old' in pairs
        assert 'BEGIN PUBLIC KEY' in pairs['old'].public_key_pem


def test_normalize_pem_empty_and_escaped() -> None:
    assert TransportKeyProvider._normalize_pem('') == ''
    assert TransportKeyProvider._normalize_pem(None) == ''  # type: ignore[arg-type]
    normalized = TransportKeyProvider._normalize_pem('-----BEGIN\\nKEY-----\\n')
    assert '\n' in normalized


# ---------------------------------------------------------------------------
# TransportSecurityUtil
# ---------------------------------------------------------------------------


def test_validate_timestamp() -> None:
    with crypto_config(**_default_crypto_kwargs(transport_crypto_clock_skew_seconds=30)):
        TransportSecurityUtil.validate_timestamp(int(time.time()))
        with pytest.raises(ValueError, match='过期'):
            TransportSecurityUtil.validate_timestamp(int(time.time()) - 120)


@pytest.mark.asyncio
async def test_validate_replay_paths() -> None:
    with crypto_config(**_default_crypto_kwargs(transport_crypto_mode='required')):
        req = _make_request(redis=None)
        with pytest.raises(ValueError, match='防重放校验不可用'):
            await TransportSecurityUtil.validate_replay(req, KID, 'n1')

    with crypto_config(**_default_crypto_kwargs(transport_crypto_mode='optional')):
        req = _make_request(redis=None)
        await TransportSecurityUtil.validate_replay(req, KID, 'n2')

    redis = FakeRedis()
    with crypto_config(**_default_crypto_kwargs()):
        req = _make_request(redis=redis)
        await TransportSecurityUtil.validate_replay(req, KID, 'n3')
        with pytest.raises(ValueError, match='重复请求'):
            await TransportSecurityUtil.validate_replay(req, KID, 'n3')

    boom = FakeRedis(set_fail=True)
    with crypto_config(**_default_crypto_kwargs(transport_crypto_mode='required')):
        req = _make_request(redis=boom)
        with pytest.raises(ValueError, match='防重放校验不可用'):
            await TransportSecurityUtil.validate_replay(req, KID, 'n4')

    with crypto_config(**_default_crypto_kwargs(transport_crypto_mode='optional')):
        req = _make_request(redis=boom)
        await TransportSecurityUtil.validate_replay(req, KID, 'n5')


def test_security_path_helpers() -> None:
    with crypto_config(**_default_crypto_kwargs(app_app_root_path='/dev-api')):
        assert TransportSecurityUtil._normalize_path('/dev-api') == '/'
        assert TransportSecurityUtil._normalize_path('/dev-api/foo') == '/foo'
        assert TransportSecurityUtil._normalize_path('') == '/'
        assert TransportSecurityUtil._normalize_path('/plain') == '/plain'

    with crypto_config(**_default_crypto_kwargs(transport_crypto_required_paths='')):
        assert TransportSecurityUtil._is_required_path('/x') is False
    with crypto_config(**_default_crypto_kwargs(transport_crypto_required_paths='/secure,/api')):
        assert TransportSecurityUtil._is_required_path('/secure/a') is True
        assert TransportSecurityUtil._is_required_path('/other') is False

    with crypto_config(
        **_default_crypto_kwargs(
            transport_crypto_mode='optional',
            transport_crypto_required_paths='/secure',
        )
    ):
        req = _make_request(path='/secure/x')
        assert TransportSecurityUtil._should_fail_closed_when_replay_check_unavailable(req) is True


# ---------------------------------------------------------------------------
# TransportCryptoUtil
# ---------------------------------------------------------------------------


def test_crypto_util_encrypt_decrypt_roundtrip() -> None:
    with crypto_config(**_default_crypto_kwargs()):
        envelope, aes_key = build_envelope(b'{"a":1}', method='POST', path='/api/data')
        decrypted = TransportCryptoUtil.decrypt_envelope(envelope, 'POST', '/api/data')
        assert decrypted.plaintext == b'{"a":1}'
        assert decrypted.aes_key == aes_key
        assert decrypted.kid == KID

        key_only = TransportCryptoUtil.decrypt_request_key(envelope)
        assert key_only == aes_key

        encrypted = TransportCryptoUtil.encrypt_response_body(
            aes_key, b'{"ok":true}', KID, 'POST', '/api/data'
        )
        payload = json.loads(encrypted.decode('utf-8'))
        assert payload['alg'] == 'AES_256_GCM'
        assert payload['kid'] == KID
        assert TransportCryptoUtil.get_response_envelope_algorithm() == 'AES_256_GCM'

        encoded = _urlsafe_b64encode(json.dumps(envelope).encode('utf-8'))
        assert TransportCryptoUtil.decode_query_envelope(encoded)['kid'] == KID


def test_crypto_util_payloads() -> None:
    with crypto_config(**_default_crypto_kwargs()):
        pub = TransportCryptoUtil.build_public_key_payload()
        assert pub['kid'] == KID
        assert pub['alg'] == ALG
        assert KID in pub['supportedKids']

        cfg = TransportCryptoUtil.build_frontend_config_payload()
        assert cfg['transportCryptoActive'] is True
        assert cfg['publicKeyUrl'] == '/transport/crypto/public-key'

    with crypto_config(**_default_crypto_kwargs(transport_crypto_mode='off')):
        cfg = TransportCryptoUtil.build_frontend_config_payload()
        assert cfg['transportCryptoActive'] is False


def test_crypto_util_validate_envelope_errors() -> None:
    valid_aad = {'method': 'POST', 'path': '/p'}
    with crypto_config(**_default_crypto_kwargs()):
        with pytest.raises(ValueError, match='格式不合法'):
            TransportCryptoUtil._validate_envelope([])  # type: ignore[arg-type]
        with pytest.raises(ValueError, match='缺少必要字段'):
            TransportCryptoUtil._validate_envelope({'kid': 'x'})
        # empty aad is falsy and treated as missing
        with pytest.raises(ValueError, match='缺少必要字段'):
            TransportCryptoUtil._validate_envelope(
                {
                    'kid': 'a',
                    'ts': 1,
                    'nonce': 'n',
                    'ek': 'e',
                    'iv': 'i',
                    'ct': 'c',
                    'aad': {},
                    'v': '1',
                    'alg': ALG,
                }
            )
        with pytest.raises(ValueError, match='协议版本'):
            TransportCryptoUtil._validate_envelope(
                {
                    'kid': 'a',
                    'ts': 1,
                    'nonce': 'n',
                    'ek': 'e',
                    'iv': 'i',
                    'ct': 'c',
                    'aad': valid_aad,
                    'v': '9',
                    'alg': ALG,
                }
            )
        with pytest.raises(ValueError, match='算法不受支持'):
            TransportCryptoUtil._validate_envelope(
                {
                    'kid': 'a',
                    'ts': 1,
                    'nonce': 'n',
                    'ek': 'e',
                    'iv': 'i',
                    'ct': 'c',
                    'aad': valid_aad,
                    'v': '1',
                    'alg': 'BAD',
                }
            )


def test_crypto_util_aad_validation() -> None:
    with crypto_config(**_default_crypto_kwargs()):
        with pytest.raises(ValueError, match='合法的aad'):
            TransportCryptoUtil._extract_and_validate_aad({'aad': 'x'}, 'POST', '/p')
        with pytest.raises(ValueError, match='method/path'):
            TransportCryptoUtil._extract_and_validate_aad(
                {'aad': {'method': 'GET', 'path': '/other'}}, 'POST', '/p'
            )
        aad = TransportCryptoUtil._extract_and_validate_aad(
            {'aad': {'method': 'post', 'path': '/p'}}, 'POST', '/p'
        )
        assert aad == {'method': 'POST', 'path': '/p'}


def test_split_paths() -> None:
    assert TransportCryptoUtil._split_paths(' /a , /b,, ') == ['/a', '/b']
    assert TransportCryptoUtil._split_paths('') == []


# ---------------------------------------------------------------------------
# TransportCryptoMonitorUtil
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_local_fallback_and_snapshot() -> None:
    _reset_monitor()
    with crypto_config(**_default_crypto_kwargs()):
        await TransportCryptoMonitorUtil.record_plain_request(None)
        await TransportCryptoMonitorUtil.record_encrypted_request(None, KID)
        await TransportCryptoMonitorUtil.record_decrypt_success(None, KID)
        await TransportCryptoMonitorUtil.record_decrypt_failure(
            None, method='POST', path='/p', reason='aad_mismatch', kid=KID
        )
        await TransportCryptoMonitorUtil.record_required_rejected(None, 'GET', '/secure')
        await TransportCryptoMonitorUtil.record_plain_response(None)
        await TransportCryptoMonitorUtil.record_encrypted_response(None, KID, is_error=False)
        await TransportCryptoMonitorUtil.record_encrypted_response(None, KID, is_error=True)
        await TransportCryptoMonitorUtil.record_encrypted_request(None, None)
        await TransportCryptoMonitorUtil.record_decrypt_success(None, None)

        snap = await TransportCryptoMonitorUtil.get_snapshot(None)
        assert snap['requestsTotal'] >= 2
        assert snap['plainRequestsTotal'] >= 1
        assert snap['encryptedRequestsTotal'] >= 1
        assert snap['decryptSuccessTotal'] >= 1
        assert snap['decryptFailureTotal'] >= 1
        assert snap['requiredRejectedTotal'] >= 1
        assert snap['plainResponsesTotal'] >= 1
        assert snap['encryptedResponsesTotal'] >= 1
        assert snap['encryptedErrorResponsesTotal'] >= 1
        assert snap['currentKid'] == KID
        assert 'aad_mismatch' in snap['failureReasons']
        assert snap['kidStats']


@pytest.mark.asyncio
async def test_monitor_redis_write_and_read() -> None:
    _reset_monitor()
    redis = FakeRedis()
    app = FastAPI()
    app.state.redis = redis
    with crypto_config(**_default_crypto_kwargs()):
        assert await TransportCryptoMonitorUtil._write_redis_counters(
            app,
            counter_updates={'requests_total': 1, 'encrypted_requests_total': 1},
            kid=KID,
            kid_counter_updates={'encrypted_requests_total': 1},
        )
        assert await TransportCryptoMonitorUtil._write_redis_failure(
            app, method='POST', path='/p', reason='replay_detected', kid=KID
        )
        assert await TransportCryptoMonitorUtil._write_redis_failure(
            app, method='GET', path='/s', reason='required_missing', include_decrypt_failure=False
        )
        snap = await TransportCryptoMonitorUtil._get_redis_snapshot(app)
        assert snap['monitor_scope'] == 'redis-aggregated'
        assert snap['counters'].get('encrypted_requests_total', 0) >= 1
        kid_stats = await TransportCryptoMonitorUtil._get_redis_kid_stats(redis, [KID])
        assert kid_stats[0]['kid'] == KID
        assert await TransportCryptoMonitorUtil._get_redis_kid_stats(redis, []) == []

        # record_* redis path returns early
        assert await TransportCryptoMonitorUtil.record_plain_request(app) is None
        assert await TransportCryptoMonitorUtil.record_encrypted_request(app, KID) is None
        assert await TransportCryptoMonitorUtil.record_decrypt_success(app, KID) is None
        assert await TransportCryptoMonitorUtil.record_plain_response(app) is None
        assert await TransportCryptoMonitorUtil.record_encrypted_response(app, KID, True) is None
        assert await TransportCryptoMonitorUtil.record_required_rejected(app, 'POST', '/x') is None
        assert await TransportCryptoMonitorUtil.record_decrypt_failure(app, 'POST', '/x', 'x', KID) is None

        merged = await TransportCryptoMonitorUtil.get_snapshot(app)
        assert 'monitorScope' in merged


@pytest.mark.asyncio
async def test_monitor_redis_failures_and_helpers() -> None:
    _reset_monitor()
    boom = FakeRedis(pipeline_fail=True)
    app = FastAPI()
    app.state.redis = boom
    with crypto_config(**_default_crypto_kwargs()):
        assert await TransportCryptoMonitorUtil._write_redis_counters(app, {'requests_total': 1}) is False
        assert (
            await TransportCryptoMonitorUtil._write_redis_failure(app, 'POST', '/p', 'decrypt_failed') is False
        )
        snap = await TransportCryptoMonitorUtil._get_redis_snapshot(app)
        assert snap['monitor_scope'] == 'process-local-fallback'

        # rate-limited warning
        TransportCryptoMonitorUtil._last_redis_warning_at = time.monotonic()
        TransportCryptoMonitorUtil._log_redis_warning('again', RuntimeError('x'))
        TransportCryptoMonitorUtil._last_redis_warning_at = 0.0
        TransportCryptoMonitorUtil._log_redis_warning('first', RuntimeError('y'))

    assert TransportCryptoMonitorUtil._get_redis_client(None) is None
    assert TransportCryptoMonitorUtil._parse_datetime(datetime.now()) is not None
    assert TransportCryptoMonitorUtil._parse_datetime(None) is None
    assert TransportCryptoMonitorUtil._parse_datetime(123) is None
    assert TransportCryptoMonitorUtil._parse_datetime('not-a-date') is None
    assert TransportCryptoMonitorUtil._parse_datetime('2020-01-01T00:00:00') is not None
    assert TransportCryptoMonitorUtil._coerce_datetime_for_sort('bad') == datetime.min
    assert TransportCryptoMonitorUtil._to_int_mapping({'a': '2'}) == {'a': 2}
    parsed = TransportCryptoMonitorUtil._parse_recent_failures(
        ['{"time":"2020-01-01T00:00:00","method":"GET","path":"/","reason":"x"}', 'not-json', '[]']
    )
    assert len(parsed) == 1
    assert TransportCryptoMonitorUtil._has_local_fallback_data(
        {'counters': {}, 'failure_reasons': {}, 'kid_stats': [], 'recent_failures': []}
    ) is False
    assert TransportCryptoMonitorUtil._has_local_fallback_data(
        {'counters': {'a': 1}, 'failure_reasons': {}, 'kid_stats': [], 'recent_failures': []}
    )
    assert TransportCryptoMonitorUtil._has_local_fallback_data(
        {'counters': {}, 'failure_reasons': {'x': 1}, 'kid_stats': [], 'recent_failures': []}
    )
    assert TransportCryptoMonitorUtil._has_local_fallback_data(
        {'counters': {}, 'failure_reasons': {}, 'kid_stats': [{'kid': 'a'}], 'recent_failures': []}
    )
    assert TransportCryptoMonitorUtil._has_local_fallback_data(
        {'counters': {}, 'failure_reasons': {}, 'kid_stats': [], 'recent_failures': [{}]}
    )
    assert TransportCryptoMonitorUtil._build_kid_counter_key('k') == 'transport:monitor:kid:k:counters'


@pytest.mark.asyncio
async def test_monitor_merge_and_build_snapshot_without_keys() -> None:
    _reset_monitor()
    redis_part = {
        'monitor_scope': 'redis-aggregated',
        'started_at': datetime(2020, 1, 1),
        'counters': {'requests_total': 1},
        'failure_reasons': {'x': 1},
        'kid_stats': [{'kid': 'a', 'encryptedRequests': 1, 'decryptSuccess': 0, 'decryptFailure': 0, 'encryptedResponses': 0}],
        'recent_failures': [{'time': datetime(2020, 1, 2), 'reason': 'x'}],
    }
    local_part = {
        'monitor_scope': 'process-local-fallback',
        'started_at': datetime(2020, 1, 3),
        'counters': {'requests_total': 2},
        'failure_reasons': {'y': 1},
        'kid_stats': [
            {'kid': 'a', 'encryptedRequests': 1, 'decryptSuccess': 1, 'decryptFailure': 0, 'encryptedResponses': 0},
            {'kid': '', 'encryptedRequests': 9},
        ],
        'recent_failures': [{'time': datetime(2020, 1, 4), 'reason': 'y'}],
    }
    merged = TransportCryptoMonitorUtil._merge_snapshot_parts(redis_part, local_part)
    assert merged['monitor_scope'] == 'redis-aggregated+local-fallback'
    assert merged['counters']['requests_total'] == 3

    with crypto_config(**_default_crypto_kwargs(transport_crypto_private_key='', transport_crypto_public_key='')):
        snap = TransportCryptoMonitorUtil._build_snapshot(merged)
        assert snap['currentKid'] == ''
        assert snap['supportedKids'] == []


# ---------------------------------------------------------------------------
# Middleware helpers / classify
# ---------------------------------------------------------------------------


def test_middleware_classify_and_path_helpers() -> None:
    assert TransportCryptoMiddleware._classify_failure_reason('') == 'decrypt_failed'
    assert TransportCryptoMiddleware._classify_failure_reason('加密请求解析失败') == 'decrypt_failed'
    assert TransportCryptoMiddleware._classify_failure_reason('method/path与当前接口不匹配') == 'aad_mismatch'
    assert TransportCryptoMiddleware._classify_failure_reason('缺少合法的aad') == 'aad_invalid'
    assert TransportCryptoMiddleware._classify_failure_reason('已过期') == 'timestamp_expired'
    assert TransportCryptoMiddleware._classify_failure_reason('缺少必要字段') == 'envelope_fields_missing'
    assert TransportCryptoMiddleware._classify_failure_reason('协议版本不受支持') == 'protocol_version_invalid'
    assert TransportCryptoMiddleware._classify_failure_reason('算法不受支持') == 'algorithm_invalid'
    assert TransportCryptoMiddleware._classify_failure_reason('未找到可解密的请求载荷') == 'envelope_missing'
    assert TransportCryptoMiddleware._classify_failure_reason('密钥版本不一致') == 'kid_mismatch'
    assert TransportCryptoMiddleware._classify_failure_reason('检测到重复请求') == 'replay_detected'
    assert TransportCryptoMiddleware._classify_failure_reason('重放攻击') == 'replay_detected'
    assert TransportCryptoMiddleware._classify_failure_reason('other') == 'decrypt_failed'

    with crypto_config(**_default_crypto_kwargs(transport_crypto_exclude_paths='/health,/docs')):
        assert TransportCryptoMiddleware._is_excluded_path('/health') is True
        assert TransportCryptoMiddleware._is_excluded_path('/docs/x') is True
        assert TransportCryptoMiddleware._is_excluded_path('/api') is False
    with crypto_config(**_default_crypto_kwargs(transport_crypto_required_paths='')):
        assert TransportCryptoMiddleware._is_required_path('/x') is False
    with crypto_config(**_default_crypto_kwargs(transport_crypto_required_paths='/secure')):
        assert TransportCryptoMiddleware._is_required_path('/secure/a') is True
    with crypto_config(**_default_crypto_kwargs(transport_crypto_enabled_paths='')):
        assert TransportCryptoMiddleware._is_enabled_path('/anything') is True
    with crypto_config(**_default_crypto_kwargs(transport_crypto_enabled_paths='/api')):
        assert TransportCryptoMiddleware._is_enabled_path('/api/data') is True
        assert TransportCryptoMiddleware._is_enabled_path('/other') is False

    with crypto_config(**_default_crypto_kwargs(app_app_root_path='/prefix')):
        assert TransportCryptoMiddleware._normalize_path('/prefix') == '/'
        assert TransportCryptoMiddleware._normalize_path('/prefix/a') == '/a'
        assert TransportCryptoMiddleware._normalize_path('') == '/'

    headers = [(b'content-type', b'application/json'), (b'accept-encoding', b'gzip')]
    assert b'accept-encoding' not in [
        k for k, _ in TransportCryptoMiddleware._remove_header(headers, b'accept-encoding')
    ]
    replaced = TransportCryptoMiddleware._replace_header(headers, b'content-type', b'text/plain')
    assert (b'content-type', b'text/plain') in replaced
    merged = TransportCryptoMiddleware._merge_response_headers([], {'x-a': '1'})
    assert (b'x-a', b'1') in merged
    mon = TransportCryptoMiddleware._build_monitor_headers('encrypted', 'plain', 'ok', kid=KID)
    assert mon['x-transport-key-id'] == KID
    mon2 = TransportCryptoMiddleware._build_monitor_headers('plain', 'plain', 'ok')
    assert 'x-transport-key-id' not in mon2

    assert TransportCryptoMiddleware._loads_json_mapping('{"a":1}') == {'a': 1}
    with pytest.raises(ValueError, match='JSON对象'):
        TransportCryptoMiddleware._loads_json_mapping('[1]')


@pytest.mark.asyncio
async def test_middleware_receive_helpers() -> None:
    chunks = [
        {'type': 'http.request', 'body': b'ab', 'more_body': True},
        {'type': 'http.disconnect'},
        {'type': 'http.request', 'body': b'c', 'more_body': False},
    ]
    idx = {'i': 0}

    async def receive() -> dict[str, Any]:
        msg = chunks[idx['i']]
        idx['i'] += 1
        return msg

    body = await TransportCryptoMiddleware._read_body(receive)
    assert body == b'abc'

    rebuilt = TransportCryptoMiddleware._build_receive(b'xyz')
    first = await rebuilt()
    second = await rebuilt()
    assert first['body'] == b'xyz'
    assert second['body'] == b''


# ---------------------------------------------------------------------------
# Middleware TestClient flows
# ---------------------------------------------------------------------------


def test_middleware_disabled_excluded_off_and_not_enabled() -> None:
    with crypto_config(**_default_crypto_kwargs(transport_crypto_enabled=False)):
        client = TestClient(_crypto_app())
        assert client.post('/api/data', json={'a': 1}).status_code == 200

    with crypto_config(**_default_crypto_kwargs()):
        client = TestClient(_crypto_app())
        assert client.get('/health').json()['status'] == 'up'

    with crypto_config(**_default_crypto_kwargs(transport_crypto_mode='off')):
        client = TestClient(_crypto_app())
        assert client.post('/api/data', json={'a': 1}).status_code == 200

    with crypto_config(**_default_crypto_kwargs(transport_crypto_enabled_paths='/secure')):
        client = TestClient(_crypto_app())
        assert client.post('/api/data', json={'a': 1}).status_code == 200


def test_middleware_required_plain_rejected() -> None:
    with crypto_config(
        **_default_crypto_kwargs(
            transport_crypto_mode='optional',
            transport_crypto_required_paths='/secure',
        )
    ):
        client = TestClient(_crypto_app())
        resp = client.post('/secure/secret', json={'a': 1})
        assert resp.status_code == 400
        assert '加密传输' in resp.json()['msg']
        assert resp.headers.get('x-transport-crypto-status') == 'required_missing'


def test_middleware_plain_passthrough_monitor_headers() -> None:
    with crypto_config(**_default_crypto_kwargs()):
        client = TestClient(_crypto_app())
        resp = client.post('/api/data', json={'hello': 'world'})
        assert resp.status_code == 200
        assert resp.headers.get('x-transport-request-mode') == 'plain'
        assert resp.headers.get('x-transport-crypto-status') == 'pass_through'


def test_middleware_encrypted_json_success() -> None:
    with crypto_config(**_default_crypto_kwargs()):
        envelope, _ = build_envelope(b'{"hello":"world"}', method='POST', path='/api/data')
        client = TestClient(_crypto_app())
        resp = client.post(
            '/api/data',
            content=json.dumps(envelope),
            headers={
                'content-type': 'application/json',
                'x-transport-encrypt': '1',
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get('x-body-encrypted') == '1'
        assert resp.headers.get('x-key-id') == KID
        body = resp.json()
        assert body['v'] == '1'
        assert body['alg'] == 'AES_256_GCM'


def test_middleware_encrypted_form_and_query() -> None:
    with crypto_config(**_default_crypto_kwargs()):
        envelope, _ = build_envelope(
            json.dumps({'name': 'bob', 'age': '1'}).encode('utf-8'),
            method='POST',
            path='/api/form',
        )
        form_fields = {k: (json.dumps(v) if k == 'aad' else str(v)) for k, v in envelope.items()}
        # aad as JSON string for form parsing
        form_fields['aad'] = json.dumps(envelope['aad'])
        client = TestClient(_crypto_app())
        resp = client.post(
            '/api/form',
            data=form_fields,
            headers={'x-transport-encrypt': '1'},
        )
        assert resp.status_code == 200
        assert resp.headers.get('x-body-encrypted') == '1'

        query_plain = json.dumps({'page': '1', 'size': '10'}).encode('utf-8')
        q_env, _ = build_envelope(query_plain, method='GET', path='/api/data')
        enc_q = _urlsafe_b64encode(json.dumps(q_env).encode('utf-8'))
        resp2 = client.get(
            f'/api/data?__enc={enc_q}',
            headers={'x-transport-encrypt': '1'},
        )
        assert resp2.status_code == 200
        assert resp2.headers.get('x-body-encrypted') == '1'


def test_middleware_query_and_body_kid_and_key_mismatch() -> None:
    with crypto_config(
        **_default_crypto_kwargs(
            transport_crypto_legacy_key_pairs=json.dumps(
                [{'kid': 'legacy', 'privateKey': LEGACY_PRIVATE_PEM, 'publicKey': LEGACY_PUBLIC_PEM}]
            )
        )
    ):
        query_plain = json.dumps({'q': '1'}).encode()
        q_env, aes1 = build_envelope(query_plain, method='POST', path='/api/data', kid=KID)
        body_env, _ = build_envelope(
            b'{"x":1}',
            method='POST',
            path='/api/data',
            kid='legacy',
            public_key_pem=LEGACY_PUBLIC_PEM,
        )
        enc_q = _urlsafe_b64encode(json.dumps(q_env).encode('utf-8'))
        client = TestClient(_crypto_app())
        resp = client.post(
            f'/api/data?__enc={enc_q}',
            content=json.dumps(body_env),
            headers={'content-type': 'application/json', 'x-transport-encrypt': '1'},
        )
        assert resp.status_code == 400
        assert resp.headers.get('x-transport-crypto-status') == 'kid_mismatch'

        # same kid different aes keys
        body_env2, _ = build_envelope(b'{"x":1}', method='POST', path='/api/data', kid=KID)
        resp2 = client.post(
            f'/api/data?__enc={enc_q}',
            content=json.dumps(body_env2),
            headers={'content-type': 'application/json', 'x-transport-encrypt': '1'},
        )
        assert resp2.status_code == 400


def test_middleware_decrypt_failure_encrypted_error_and_plain_error() -> None:
    with crypto_config(**_default_crypto_kwargs()):
        envelope, _ = build_envelope(b'{"a":1}', method='POST', path='/api/data', timestamp=1)
        client = TestClient(_crypto_app())
        resp = client.post(
            '/api/data',
            content=json.dumps(envelope),
            headers={'content-type': 'application/json', 'x-transport-encrypt': '1'},
        )
        assert resp.status_code == 400
        assert resp.headers.get('x-body-encrypted') == '1'
        assert resp.headers.get('x-transport-crypto-status') == 'timestamp_expired'

        # no usable envelope -> plain error
        resp2 = client.post(
            '/api/data',
            content='not-json',
            headers={'content-type': 'application/json', 'x-transport-encrypt': '1'},
        )
        assert resp2.status_code == 400
        assert resp2.headers.get('x-body-encrypted') is None


def test_middleware_missing_envelope_and_multipart_and_non_json_body() -> None:
    with crypto_config(**_default_crypto_kwargs()):
        client = TestClient(_crypto_app())
        resp = client.post(
            '/api/data',
            content=b'',
            headers={'content-type': 'application/json', 'x-transport-encrypt': '1'},
        )
        assert resp.status_code == 400
        assert resp.headers.get('x-transport-crypto-status') == 'envelope_missing'

        resp2 = client.post(
            '/api/data',
            content=b'[]',
            headers={'content-type': 'application/json', 'x-transport-encrypt': '1'},
        )
        assert resp2.status_code == 400

        # multipart body skipped -> missing envelope
        resp3 = client.post(
            '/api/data',
            content=b'--bound',
            headers={
                'content-type': 'multipart/form-data; boundary=bound',
                'x-transport-encrypt': '1',
            },
        )
        assert resp3.status_code == 400

        # unsupported content type with body
        resp4 = client.post(
            '/api/data',
            content=b'raw',
            headers={'content-type': 'text/plain', 'x-transport-encrypt': '1'},
        )
        assert resp4.status_code == 400


def test_middleware_non_json_response_and_chunked_json() -> None:
    with crypto_config(**_default_crypto_kwargs()):
        envelope, _ = build_envelope(b'{}', method='POST', path='/api/text')
        client = TestClient(_crypto_app())
        resp = client.post(
            '/api/text',
            content=json.dumps(envelope),
            headers={'content-type': 'application/json', 'x-transport-encrypt': '1'},
        )
        assert resp.status_code == 200
        assert resp.headers.get('x-body-encrypted') is None
        assert resp.headers.get('x-transport-response-mode') == 'plain'
        assert resp.text == 'plain-text'


@pytest.mark.asyncio
async def test_middleware_response_encryptor_more_body_and_non_body() -> None:
    mw = TransportCryptoMiddleware(MagicMock())
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    crypto_context = {'active': True, 'kid': KID, 'aes_key': os.urandom(32)}
    with crypto_config(**_default_crypto_kwargs()):
        encryptor = mw._build_response_encryptor(
            app=None,
            scope={'method': 'POST', 'path': '/api/data'},
            send=send,
            crypto_context=crypto_context,
        )
        await encryptor(
            {
                'type': 'http.response.start',
                'status': 200,
                'headers': [(b'content-type', b'application/json')],
            }
        )
        await encryptor({'type': 'http.response.body', 'body': b'{"a":', 'more_body': True})
        await encryptor({'type': 'http.response.body', 'body': b'1}', 'more_body': False})
        assert any(m.get('type') == 'http.response.body' for m in sent)
        assert any(
            (b'x-body-encrypted', b'1') in m.get('headers', [])
            for m in sent
            if m.get('type') == 'http.response.start'
        )

        # non-body message passthrough when not buffering
        sent.clear()
        encryptor2 = mw._build_response_encryptor(
            app=None,
            scope={'method': 'POST', 'path': '/api/data'},
            send=send,
            crypto_context=crypto_context,
        )
        await encryptor2(
            {
                'type': 'http.response.start',
                'status': 200,
                'headers': [(b'content-type', b'text/plain')],
            }
        )
        await encryptor2({'type': 'http.response.body', 'body': b'hi', 'more_body': False})
        await encryptor2({'type': 'http.disconnect'})


@pytest.mark.asyncio
async def test_middleware_passthrough_observer_and_error_context() -> None:
    mw = TransportCryptoMiddleware(MagicMock())
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    observer = mw._build_passthrough_response_observer(
        app=None, send=send, request_mode='plain', crypto_status='pass_through', kid=None
    )
    await observer({'type': 'http.response.start', 'status': 200, 'headers': []})
    await observer({'type': 'http.response.body', 'body': b'ok'})
    assert any(m['type'] == 'http.response.start' for m in sent)

    with crypto_config(**_default_crypto_kwargs()):
        envelope, aes_key = build_envelope(b'{"a":1}', method='POST', path='/api/data')
        scope = {
            'type': 'http',
            'method': 'POST',
            'path': '/api/data',
            'query_string': b'',
            'headers': [(b'content-type', b'application/json')],
        }
        from fastapi.datastructures import Headers

        headers = Headers(scope=scope)
        body = json.dumps(envelope).encode('utf-8')
        ctx = mw._build_error_crypto_context(scope, headers, body)
        assert ctx is not None
        assert ctx['kid'] == KID
        assert ctx['aes_key'] == aes_key

        # aad mismatch -> None
        bad = dict(envelope)
        bad['aad'] = {'method': 'GET', 'path': '/wrong'}
        assert mw._build_error_crypto_context(scope, headers, json.dumps(bad).encode()) is None

        assert mw._extract_request_kid(scope, headers, body) == KID
        assert mw._extract_request_kid(scope, headers, b'') is None

        # extract_body_envelope form aad non-json string
        form_body = urlencode({'kid': KID, 'aad': 'not-json'}).encode()
        form_env = mw._extract_body_envelope('application/x-www-form-urlencoded', form_body)
        assert form_env is not None
        assert form_env['aad'] == 'not-json'


def test_middleware_form_aad_json_and_extract_query_none() -> None:
    mw = TransportCryptoMiddleware(MagicMock())
    form_body = urlencode({'kid': KID, 'aad': json.dumps({'method': 'POST', 'path': '/p'})}).encode()
    env = mw._extract_body_envelope('application/x-www-form-urlencoded', form_body)
    assert isinstance(env['aad'], dict)
    assert mw._extract_body_envelope('application/json', b'') is None
    assert mw._extract_query_envelope({'query_string': b'a=1'}) is None


def test_add_transport_crypto_middleware() -> None:
    app = FastAPI()

    @app.get('/ping')
    async def ping() -> dict[str, str]:
        return {'pong': '1'}

    with crypto_config(**_default_crypto_kwargs(transport_crypto_enabled=False)):
        add_transport_crypto_middleware(app)
        client = TestClient(app)
        assert client.get('/ping').json()['pong'] == '1'


@pytest.mark.asyncio
async def test_middleware_non_http_scope_passthrough() -> None:
    called = {'ok': False}

    async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
        called['ok'] = True

    mw = TransportCryptoMiddleware(inner)
    await mw({'type': 'websocket'}, AsyncMock(), AsyncMock())
    assert called['ok'] is True


@pytest.mark.asyncio
async def test_middleware_crypto_context_none_guard() -> None:
    """Cover the defensive crypto_context is None branch in _decrypt_request."""
    mw = TransportCryptoMiddleware(MagicMock())
    with crypto_config(**_default_crypto_kwargs()):
        envelope, _ = build_envelope(b'{"a":1}', method='POST', path='/api/data')
        app = FastAPI()
        app.state.redis = None
        scope = {
            'type': 'http',
            'asgi': {'version': '3.0'},
            'http_version': '1.1',
            'method': 'POST',
            'scheme': 'http',
            'path': '/api/data',
            'raw_path': b'/api/data',
            'query_string': b'',
            'headers': [(b'content-type', b'application/json')],
            'client': ('127.0.0.1', 12345),
            'server': ('testserver', 80),
            'root_path': '',
            'app': app,
            'state': {},
        }
        from fastapi.datastructures import Headers

        headers = Headers(scope=scope)
        body = json.dumps(envelope).encode('utf-8')
        request = Request(scope, receive=TransportCryptoMiddleware._build_receive(body))
        with patch.object(TransportCryptoMiddleware, '_build_crypto_context', return_value=None):
            with pytest.raises(ValueError, match='密钥上下文'):
                await mw._decrypt_request(scope, request, headers, body)


def test_middleware_mode_required_global() -> None:
    with crypto_config(**_default_crypto_kwargs(transport_crypto_mode='required')):
        client = TestClient(_crypto_app())
        resp = client.post('/api/data', json={'a': 1})
        assert resp.status_code == 400
        assert '加密传输' in resp.json()['msg']


def test_middleware_encrypted_with_query_only_then_json_response() -> None:
    with crypto_config(**_default_crypto_kwargs()):
        query_plain = json.dumps({'pageNum': '1'}).encode()
        q_env, _ = build_envelope(query_plain, method='GET', path='/api/data')
        enc_q = _urlsafe_b64encode(json.dumps(q_env).encode('utf-8'))
        client = TestClient(_crypto_app())
        resp = client.get(f'/api/data?__enc={enc_q}', headers={'x-transport-encrypt': '1'})
        assert resp.status_code == 200
        assert resp.headers.get('x-body-encrypted') == '1'


@pytest.mark.asyncio
async def test_send_error_response_plain_and_encrypted() -> None:
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    scope = {'type': 'http', 'method': 'POST', 'path': '/api/data', 'headers': []}
    with crypto_config(**_default_crypto_kwargs()):
        await TransportCryptoMiddleware._send_error_response(
            scope, receive, send, 'boom', headers={'x-transport-crypto-status': 'decrypt_failed'}
        )
        assert any(m.get('type') == 'http.response.start' for m in sent)

        sent.clear()
        await TransportCryptoMiddleware._send_error_response(
            scope,
            receive,
            send,
            'boom2',
            crypto_context={'active': True, 'kid': KID, 'aes_key': os.urandom(32)},
            headers={'x-transport-crypto-status': 'decrypt_failed'},
        )
        start = next(m for m in sent if m['type'] == 'http.response.start')
        header_map = {k.decode(): v.decode() for k, v in start['headers']}
        assert header_map.get('x-body-encrypted') == '1'


def test_build_crypto_context() -> None:
    from utils.transport_crypto_util import DecryptedTransportEnvelope

    mw = TransportCryptoMiddleware(MagicMock())
    payload = DecryptedTransportEnvelope(
        kid=KID,
        nonce='n',
        timestamp=1,
        aes_key=b'1' * 32,
        aad={'method': 'POST', 'path': '/p'},
        plaintext=b'{}',
    )
    ctx = mw._build_crypto_context(payload)
    assert ctx['active'] is True
    assert ctx['kid'] == KID


@pytest.mark.asyncio
async def test_extract_request_kid_exception_path() -> None:
    mw = TransportCryptoMiddleware(MagicMock())
    scope = {'query_string': b'__enc=%%%', 'headers': []}
    from fastapi.datastructures import Headers

    headers = Headers(scope={'headers': [(b'content-type', b'application/json')]})
    assert mw._extract_request_kid(scope, headers, b'{') is None


def test_form_envelope_list_values() -> None:
    mw = TransportCryptoMiddleware(MagicMock())
    # parse_qs returns lists; middleware takes last value
    body = b'kid=default&kid=other&nonce=n1'
    env = mw._extract_body_envelope('application/x-www-form-urlencoded', body)
    assert env['kid'] == 'other'
