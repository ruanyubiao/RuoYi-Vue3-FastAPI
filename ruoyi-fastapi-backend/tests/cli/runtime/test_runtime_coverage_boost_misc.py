"""Raise base/db/crypto/dev/app runtime coverage toward 99%."""

from __future__ import annotations

import getpass
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from cli.exit_codes import DATABASE_ERROR, RUNTIME_ERROR
from cli.runtime.app import AppRuntimeService
from cli.runtime.app.gateway import AppInfrastructureGateway
from cli.runtime.base import RuntimeEnvironmentService, RuntimeOperatorService
from cli.runtime.crypto import CryptoRuntimeService
from cli.runtime.crypto.gateway import CryptoInfrastructureGateway
from cli.runtime.crypto.support import CryptoDomainSupport, CryptoResultSupport
from cli.runtime.db import DatabaseRuntimeService
from cli.runtime.db.gateway import DatabaseInfrastructureGateway
from cli.runtime.db.support import DatabaseAlembicCommandSupport, DatabaseRevisionSupport
from cli.runtime.dev import DevelopmentRuntimeService
from cli.runtime.dev.gateway import DevelopmentProcessGateway
from cli.runtime.dev.support import DevelopmentCommandSupport, DevelopmentToolingSupport

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _runtime_boost_helpers import patch_gateway


# ---------------------------------------------------------------------------
# base
# ---------------------------------------------------------------------------


def test_runtime_environment_and_operator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = RuntimeEnvironmentService()
    if RuntimeEnvironmentService.is_backend_project_dir(Path.cwd()):
        assert Path(env.get_backend_dir()) == Path.cwd().resolve()
    else:
        (tmp_path / 'app.py').write_text('', encoding='utf-8')
        (tmp_path / 'config').mkdir()
        (tmp_path / 'config' / 'env.py').write_text('', encoding='utf-8')
        (tmp_path / 'cli').mkdir()
        monkeypatch.chdir(tmp_path)
        assert Path(env.get_backend_dir()) == tmp_path.resolve()

    empty = tmp_path / 'empty'
    empty.mkdir(exist_ok=True)
    monkeypatch.chdir(empty)
    monkeypatch.setattr('config.paths.get_package_root', lambda: Path('/pkg/root'))
    assert env.get_backend_dir() == str(Path('/pkg/root'))

    monkeypatch.setattr(sys, 'executable', '')
    assert RuntimeEnvironmentService.get_python_executable() == 'python'
    monkeypatch.setattr(sys, 'executable', sys.executable or 'python')

    monkeypatch.setattr(getpass, 'getuser', lambda: 'alice')
    assert RuntimeOperatorService.resolve_operator() == 'alice'
    monkeypatch.setattr(getpass, 'getuser', lambda: '')
    assert RuntimeOperatorService.resolve_operator() == 'ruoyi-cli'

    def _boom_user() -> str:
        raise RuntimeError('no user')

    monkeypatch.setattr(getpass, 'getuser', _boom_user)
    assert RuntimeOperatorService.resolve_operator() == 'ruoyi-cli'


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------


def test_app_runtime_and_gateway() -> None:
    gateway = AppInfrastructureGateway()
    service = AppRuntimeService(infrastructure_gateway=gateway)

    class FakeSnapshot:
        @staticmethod
        def build_app_config_snapshot() -> dict[str, str]:
            return {'app': 'cfg'}

        @staticmethod
        def build_app_env_snapshot() -> dict[str, str]:
            return {'env': 'dev'}

    service.snapshot_support = FakeSnapshot()  # type: ignore[assignment]
    assert service.get_app_config_snapshot() == {'app': 'cfg'}
    assert service.get_app_env_snapshot() == {'env': 'dev'}

    assert gateway.get_server_module() is not None
    assert gateway.get_env_module() is not None


# ---------------------------------------------------------------------------
# db
# ---------------------------------------------------------------------------


class FakeRuntimeEnvironment(RuntimeEnvironmentService):
    @staticmethod
    def get_backend_dir() -> str:
        return '/tmp/ruoyi-backend'

    @staticmethod
    def get_python_executable() -> str:
        return '/usr/bin/python3'


@pytest.mark.asyncio
async def test_db_ping_success_and_revision_paths() -> None:
    gateway = DatabaseInfrastructureGateway()
    service = DatabaseRuntimeService(
        runtime_environment=FakeRuntimeEnvironment(),
        infrastructure_gateway=gateway,
    )

    class FakeConnection:
        async def __aenter__(self) -> FakeConnection:
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

        async def execute(self, sql: Any) -> Any:
            del sql
            return SimpleNamespace(scalar=lambda: 'abc')

    class FakeEngine:
        def connect(self) -> FakeConnection:
            return FakeConnection()

        async def dispose(self) -> None:
            return None

    patch_gateway(
        gateway,
        get_async_db_engine_factory=lambda: (lambda *, echo=False: FakeEngine()),
        get_sqlalchemy_text=lambda: (lambda sql: sql),
    )
    assert (await service.ping_database())['ok'] is True

    class SyncConn:
        def __enter__(self) -> SyncConn:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(self, sql: Any) -> Any:
            del sql
            return SimpleNamespace(scalar=lambda: 'rev1')

    class SyncEngine:
        def connect(self) -> SyncConn:
            return SyncConn()

        def dispose(self) -> None:
            return None

    patch_gateway(
        gateway,
        get_sync_db_engine_factory=lambda: (lambda *, echo=False: SyncEngine()),
        get_sqlalchemy_text=lambda: (lambda sql: sql),
    )
    assert service.get_current_revision()['currentRevision'] == 'rev1'

    class BoomSync:
        def connect(self) -> Any:
            raise RuntimeError('sync boom')

        def dispose(self) -> None:
            return None

    patch_gateway(gateway, get_sync_db_engine_factory=lambda: (lambda *, echo=False: BoomSync()))
    assert service.get_current_revision()['exit_code'] == DATABASE_ERROR

    assert service.init_database(dry_run=True)['dryRun'] is True
    assert service.downgrade_database(dry_run=True)['dryRun'] is True
    assert service.create_revision('msg', autogenerate=True, dry_run=True)['command'][-1] == '--autogenerate'


def test_db_alembic_heads_history_and_command_run(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = DatabaseInfrastructureGateway()
    env = FakeRuntimeEnvironment()
    revision_support = DatabaseRevisionSupport(gateway, env)
    service = DatabaseRuntimeService(
        runtime_environment=env,
        infrastructure_gateway=gateway,
        revision_support=revision_support,
    )

    class FakeRevision:
        revision = 'r2'
        down_revision = 'r1'
        branch_labels = None
        dependencies = ('d1',)
        doc = 'doc'
        path = Path('/tmp/r2.py')

    class FakeScriptDir:
        @staticmethod
        def get_revisions(label: str) -> list[FakeRevision]:
            assert label == 'heads'
            return [FakeRevision()]

        @staticmethod
        def walk_revisions() -> list[FakeRevision]:
            return [FakeRevision(), FakeRevision()]

    object.__setattr__(revision_support, 'build_alembic_script_directory', lambda: FakeScriptDir())
    heads = service.get_alembic_heads()
    assert heads['count'] == 1
    history = service.get_alembic_history(limit=1)
    assert history['count'] == 1
    assert history['totalCount'] == 2

    def _boom_script_directory() -> Any:
        raise RuntimeError('heads boom')

    object.__setattr__(revision_support, 'build_alembic_script_directory', _boom_script_directory)
    assert service.get_alembic_heads()['exit_code'] == DATABASE_ERROR
    assert service.get_alembic_history()['exit_code'] == DATABASE_ERROR

    assert DatabaseRevisionSupport.normalize_revision_value(None) == []
    assert DatabaseRevisionSupport.normalize_revision_value('x') == ['x']

    class FakeConfig:
        def __init__(self, path: str) -> None:
            self.path = path

    class FakeScriptDirectory:
        @staticmethod
        def from_config(config: FakeConfig) -> str:
            return f'script:{config.path}'

    patch_gateway(
        gateway,
        get_alembic_config_class=lambda: FakeConfig,
        get_alembic_script_directory_class=lambda: FakeScriptDirectory,
    )
    restored = DatabaseRevisionSupport(gateway, env)
    assert restored.build_alembic_script_directory().startswith('script:')

    import cli.runtime.db.support as db_support_mod
    import subprocess as _sp

    command_support = DatabaseAlembicCommandSupport(env)
    completed = SimpleNamespace(returncode=0, stdout='done\n', stderr='')
    monkeypatch.setattr(db_support_mod.subprocess, 'run', lambda *a, **k: completed)
    ok = command_support.run_alembic_command('upgrade', 'head', success_message='ok', failure_message='fail')
    assert ok['ok'] is True
    assert ok['stdout'] == 'done'

    completed_fail = SimpleNamespace(returncode=1, stdout='', stderr='err')
    monkeypatch.setattr(db_support_mod.subprocess, 'run', lambda *a, **k: completed_fail)
    fail = command_support.run_alembic_command('upgrade', 'head', success_message='ok', failure_message='fail')
    assert fail['exit_code'] == DATABASE_ERROR

    def _raise(*a, **k):
        raise OSError('spawn fail')

    monkeypatch.setattr(db_support_mod.subprocess, 'run', _raise)
    boom = command_support.run_alembic_command('upgrade', 'head', success_message='ok', failure_message='fail')
    assert boom['exit_code'] == DATABASE_ERROR


def test_db_gateway_lazy_imports() -> None:
    gateway = DatabaseInfrastructureGateway()
    assert callable(gateway.get_async_db_engine_factory())
    assert callable(gateway.get_sync_db_engine_factory())
    assert callable(gateway.get_sqlalchemy_text())
    assert gateway.get_alembic_config_class() is not None
    assert gateway.get_alembic_script_directory_class() is not None


# ---------------------------------------------------------------------------
# crypto
# ---------------------------------------------------------------------------


def test_crypto_generate_validate_export_and_support() -> None:
    gateway = CryptoInfrastructureGateway()
    domain = CryptoDomainSupport(gateway)
    service = CryptoRuntimeService(infrastructure_gateway=gateway, domain_support=domain)

    fake_private = MagicMock()
    fake_private.private_bytes.return_value = b'PRIV-PEM'
    fake_private.public_key.return_value.public_bytes.return_value = b'PUB-PEM'
    fake_rsa = SimpleNamespace(generate_private_key=lambda **kwargs: fake_private)
    fake_serialization = SimpleNamespace(
        Encoding=SimpleNamespace(PEM='PEM'),
        PrivateFormat=SimpleNamespace(PKCS8='PKCS8'),
        PublicFormat=SimpleNamespace(SubjectPublicKeyInfo='SPKI'),
        NoEncryption=lambda: 'none',
    )
    patch_gateway(
        gateway,
        get_rsa_module=lambda: fake_rsa,
        get_serialization_module=lambda: fake_serialization,
        get_transport_crypto_config=lambda: SimpleNamespace(transport_crypto_legacy_key_pairs='[]'),
    )
    private_pem, public_pem = domain.generate_rsa_key_pair(2048)
    assert private_pem == 'PRIV-PEM'
    assert public_pem == 'PUB-PEM'
    assert domain.load_existing_legacy_key_pairs() == []

    gen = service.generate_crypto_key_pair('kid-1', 2048)
    assert gen['ok'] is True
    assert gen['privateKey'] == 'PRIV-PEM'

    provider = SimpleNamespace(
        validate_runtime_configuration=lambda: None,
        get_current_key_pair=lambda: SimpleNamespace(kid='c', private_key_pem='p', public_key_pem='u'),
    )
    crypto_util = SimpleNamespace(build_public_key_payload=lambda: {'kid': 'c', 'publicKey': 'PUB'})
    patch_gateway(
        gateway,
        get_transport_key_provider=lambda: provider,
        get_transport_crypto_util=lambda: crypto_util,
    )
    assert service.validate_crypto_config()['ok'] is True
    assert service.export_public_key()['publicKey']['kid'] == 'c'

    def _bad_cfg() -> None:
        raise RuntimeError('bad cfg')

    boom_provider = SimpleNamespace(
        validate_runtime_configuration=_bad_cfg,
        get_current_key_pair=lambda: None,
    )
    patch_gateway(gateway, get_transport_key_provider=lambda: boom_provider)
    assert service.validate_crypto_config()['exit_code'] == RUNTIME_ERROR
    assert service.export_public_key()['exit_code'] == RUNTIME_ERROR

    result = CryptoResultSupport()

    def _raise_runtime() -> dict[str, Any]:
        raise RuntimeError('x')

    assert result.run_argument_guarded(_raise_runtime, failure_message='f')['exit_code'] == RUNTIME_ERROR
    assert result.run_runtime_guarded(lambda: {'ok': True}, failure_message='f') == {'ok': True}


def test_crypto_gateway_lazy_imports() -> None:
    gateway = CryptoInfrastructureGateway()
    assert gateway.get_rsa_module() is not None
    assert gateway.get_serialization_module() is not None
    assert gateway.get_transport_crypto_config() is not None
    assert gateway.get_transport_key_provider() is not None
    assert gateway.get_transport_crypto_util() is not None


# ---------------------------------------------------------------------------
# dev
# ---------------------------------------------------------------------------


def test_dev_tooling_commands_process_and_service(monkeypatch: pytest.MonkeyPatch) -> None:
    env = FakeRuntimeEnvironment()
    tooling = DevelopmentToolingSupport()
    assert tooling.resolve_targets(None) == ['.']
    assert tooling.resolve_targets(['', ' tests ']) == ['tests']
    assert tooling.is_pytest_available() is True

    commands = DevelopmentCommandSupport(env)
    assert '--check' in commands.build_format_command(['.'], check_only=True)
    check = commands.build_check_command(['.'], check_only=False, fix=True, unsafe_fixes=True)
    assert '--fix' in check and '--unsafe-fixes' in check
    pytest_cmd = commands.build_pytest_command(['tests'], keyword='x', maxfail=2, quiet=True)
    assert '-q' in pytest_cmd and '-k' in pytest_cmd and '--maxfail=2' in pytest_cmd

    import cli.runtime.dev.gateway as dev_gateway_mod

    gateway = DevelopmentProcessGateway(env)
    completed = SimpleNamespace(returncode=0, stdout='out\n', stderr='err\n')
    monkeypatch.setattr(dev_gateway_mod.subprocess, 'run', lambda *a, **k: completed)
    ok = gateway.run_command(['echo'])
    assert ok['ok'] is True
    assert ok['stdout'] == 'out'
    assert ok['stderr'] == 'err'

    def _raise_spawn(*a, **k):
        raise OSError('spawn')

    monkeypatch.setattr(dev_gateway_mod.subprocess, 'run', _raise_spawn)
    fail = gateway.run_command(['echo'])
    assert fail['exit_code'] == RUNTIME_ERROR

    class FakeProcess(DevelopmentProcessGateway):
        def __init__(self) -> None:
            self.calls: list[list[str]] = []
            self.mode = 'ok'

        def run_command(self, command: list[str]) -> dict[str, object]:
            self.calls.append(command)
            if self.mode == 'format-fail':
                return {'ok': False, 'command': command}
            if self.mode == 'check-fail':
                if command == ['check']:
                    return {'ok': False, 'command': command}
                return {'ok': True, 'command': command}
            if self.mode == 'test-fail':
                return {'ok': False, 'command': command}
            return {'ok': True, 'command': command}

    class FakeCommands(DevelopmentCommandSupport):
        def build_format_command(self, normalized_targets: list[str], *, check_only: bool) -> list[str]:
            del normalized_targets, check_only
            return ['format']

        def build_check_command(
            self,
            normalized_targets: list[str],
            *,
            check_only: bool,
            fix: bool,
            unsafe_fixes: bool,
        ) -> list[str]:
            del normalized_targets, check_only, fix, unsafe_fixes
            return ['check']

        def build_pytest_command(
            self,
            normalized_targets: list[str],
            *,
            keyword: str,
            maxfail: int,
            quiet: bool,
        ) -> list[str]:
            del normalized_targets, keyword, maxfail, quiet
            return ['pytest']

    class AlwaysPytest(DevelopmentToolingSupport):
        @staticmethod
        def is_pytest_available() -> bool:
            return True

    process = FakeProcess()
    service = DevelopmentRuntimeService(
        runtime_environment=env,
        tooling_support=AlwaysPytest(),
        command_support=FakeCommands(env),
        process_gateway=process,
    )
    process.mode = 'format-fail'
    assert service.run_lint(['x'])['message'] == 'Ruff format 阶段失败'
    process.mode = 'check-fail'
    assert service.run_lint(['x'])['message'] == 'Ruff check 阶段失败'
    process.mode = 'ok'
    assert service.run_tests(['tests'], keyword='a', maxfail=1, quiet=True)['ok'] is True
    process.mode = 'test-fail'
    assert service.run_tests(['tests'])['exit_code'] == RUNTIME_ERROR
