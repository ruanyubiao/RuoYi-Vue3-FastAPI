"""Controller + command wiring coverage for cli.groups."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

from fastapi.routing import APIRoute
from pytest import MonkeyPatch

from cli.groups.app import command as app_command
from cli.groups.app.controller import AppCommandController
from cli.groups.cache import command as cache_command
from cli.groups.cache.controller import CacheCommandController
from cli.groups.config import command as config_command
from cli.groups.config.controller import ConfigCommandController
from cli.groups.crypto import command as crypto_command
from cli.groups.crypto.controller import CryptoCommandController
from cli.groups.db import command as db_command
from cli.groups.db.controller import DbCommandController
from cli.groups.dev import command as dev_command
from cli.groups.dev.controller import DevCommandController
from cli.groups.gen import command as gen_command
from cli.groups.gen.controller import GenCommandController
from cli.groups.job import command as job_command
from cli.groups.job.controller import JobCommandController
from cli.groups.ops import command as ops_command
from cli.groups.ops.controller import OpsCommandController


class FakeContextFactory:
    def build_readonly(self, env: str, output: str) -> SimpleNamespace:
        return SimpleNamespace(env=env, output=output)

    def build_dangerous(
        self,
        env: str,
        output: str,
        allow_prod: bool,
        yes: bool,
        dry_run: bool,
        command_name: str = '',
    ) -> SimpleNamespace:
        return SimpleNamespace(
            env=env,
            output=output,
            allow_prod=allow_prod,
            yes=yes,
            dry_run=dry_run,
            command_name=command_name,
        )


class FakeExecutionService:
    def __init__(self, *, invoke_text_builders: bool = True) -> None:
        self.invoke_text_builders = invoke_text_builders
        self.completed: list[tuple[Any, Any]] = []
        self.completed_with_text: list[tuple[Any, Any, dict[str, Any]]] = []
        self.completed_payload_result: list[tuple[Any, Any, dict[str, Any]]] = []

    def run_async(self, value: Any) -> Any:
        return value

    def complete_payload(self, ctx: Any, payload: Any) -> None:
        self.completed.append((ctx, payload))

    def complete_payload_with_text(
        self,
        ctx: Any,
        payload: Any,
        *,
        text_builder: Callable[[Any], str] | None = None,
        text_condition: Callable[[Any], bool] | None = None,
        default_exit_code: int | None = None,
    ) -> None:
        kwargs = {
            'text_builder': text_builder,
            'text_condition': text_condition,
            'default_exit_code': default_exit_code,
        }
        self.completed_with_text.append((ctx, payload, kwargs))
        if self.invoke_text_builders and text_builder is not None:
            condition = text_condition or (lambda data: True)
            if condition(payload):
                text_builder(payload)

    def complete_payload_result(
        self,
        ctx: Any,
        payload: Any,
        *,
        text_builder: Callable[[Any], str] | None = None,
        default_exit_code: int | None = None,
    ) -> None:
        kwargs = {'text_builder': text_builder, 'default_exit_code': default_exit_code}
        self.completed_payload_result.append((ctx, payload, kwargs))
        if self.invoke_text_builders and text_builder is not None:
            text_builder(payload)


def _make_deps(**runtime_attrs: Any) -> dict[str, Any]:
    return {
        'context_factory': FakeContextFactory(),
        'execution_service': FakeExecutionService(),
        **runtime_attrs,
    }


# --- cache ---


def test_cache_controller_and_commands(monkeypatch: MonkeyPatch) -> None:
    runtime = SimpleNamespace(
        get_cache_stats=lambda: {'ok': True},
        list_cache_keys=lambda name: {'ok': True, 'cacheName': name, 'keys': ['a']},
        get_cache_value=lambda name, key: {'ok': True, 'cacheName': name, 'cacheKey': key, 'cacheValue': 'v'},
        clear_cache=lambda **kwargs: {'ok': True, **kwargs},
        get_cache_ttl=lambda name, key: {'ok': True, 'ttlSeconds': 1},
        warmup_cache=lambda: {'ok': True},
    )

    deps = _make_deps(runtime_service=runtime)
    controller = CacheCommandController(**deps)
    execution = deps['execution_service']

    controller.stats('dev', 'text')
    controller.keys('sys', 'dev', 'text')
    controller.get('sys', 'k', 'dev', 'text')
    controller.clear('dev', 'text', False, True, True, cache_name='sys', cache_key='', clear_all=False)
    controller.ttl('sys', 'k', 'dev', 'text')
    controller.warmup('dev', 'text', False, True)
    assert len(execution.completed_with_text) == 4
    assert len(execution.completed) == 2

    fake = SimpleNamespace(
        stats=lambda *a, **k: None,
        keys=lambda *a, **k: None,
        get=lambda *a, **k: None,
        clear=lambda *a, **k: None,
        ttl=lambda *a, **k: None,
        warmup=lambda *a, **k: None,
    )
    monkeypatch.setattr(cache_command, '_CACHE_COMMAND_CONTROLLER', fake)
    cache_command.stats('dev', 'json')
    cache_command.keys('sys', 'dev', 'json')
    cache_command.get('sys', 'k', 'dev', 'json')
    cache_command.clear('dev', 'json', False, True, False, cache_name='', cache_key='', clear_all=True)
    cache_command.ttl('sys', 'k', 'dev', 'json')
    cache_command.warmup('dev', 'json', False, True)

    CacheCommandController()


# --- app ---


def test_app_controller_and_commands(monkeypatch: MonkeyPatch) -> None:
    def _endpoint() -> None:
        return None

    visible = APIRoute('/api/a', _endpoint, methods=['GET'], summary='A', tags=['sys'])
    hidden = APIRoute('/hidden', _endpoint, methods=['POST'], include_in_schema=False)
    multi_tag = APIRoute('/api/b', _endpoint, methods=['POST'], tags=['ops', 'sys'])
    app_instance = SimpleNamespace(routes=[visible, hidden, multi_tag, SimpleNamespace(path='/not-route')])

    runtime = SimpleNamespace(
        get_app_config_snapshot=lambda: {'name': 'app'},
        get_app_env_snapshot=lambda: {'cliEnv': 'dev'},
        build_app_instance=lambda: app_instance,
    )
    db_runtime = SimpleNamespace(ping_database=lambda: {'ok': True, 'message': 'db'})
    ops_runtime = SimpleNamespace(ping_redis=lambda: {'ok': True, 'message': 'redis'})
    crypto_runtime = SimpleNamespace(validate_crypto_config=lambda: {'ok': True, 'message': 'crypto'})
    captured: dict[str, Any] = {}
    bootstrap = SimpleNamespace(exec_app_run_command=lambda env: captured.update({'run_env': env}))

    deps = _make_deps(
        runtime_service=runtime,
        database_runtime=db_runtime,
        operations_runtime=ops_runtime,
        crypto_runtime=crypto_runtime,
        bootstrap_service=bootstrap,
    )
    controller = AppCommandController(**deps)

    controller.run_app('prod')
    assert captured['run_env'] == 'prod'
    controller.doctor('dev', 'text')
    controller.show_config('dev', 'text')
    controller.show_env('dev', 'text')
    controller.show_routes('dev', 'text', path_prefix='/api', method='GET', group_by='none', include_hidden=False)
    controller.show_routes('dev', 'text', path_prefix='/api', method='DELETE', group_by='none', include_hidden=True)
    controller.show_routes('dev', 'text', path_prefix='', method='', group_by='tag', include_hidden=True)
    db_runtime.ping_database = lambda: {'ok': False, 'message': 'db'}
    controller.doctor('dev', 'json')

    assert AppCommandController._group_routes_by_tag([{'path': '/x', 'tags': []}])['__untagged__']

    fake = SimpleNamespace(
        run_app=lambda *a, **k: None,
        doctor=lambda *a, **k: None,
        show_config=lambda *a, **k: None,
        show_env=lambda *a, **k: None,
        show_routes=lambda *a, **k: None,
    )
    monkeypatch.setattr(app_command, '_APP_COMMAND_CONTROLLER', fake)
    app_command.run_app('dev')
    app_command.doctor('dev', 'text')
    app_command.app_config('dev', 'text')
    app_command.app_env('dev', 'text')
    app_command.routes('dev', 'text', path_prefix='', method='', group_by='none', include_hidden=False)

    AppCommandController()


# --- ops ---


def test_ops_controller_and_commands(monkeypatch: MonkeyPatch) -> None:
    db_runtime = SimpleNamespace(ping_database=lambda: {'ok': True})
    ops_runtime = SimpleNamespace(
        ping_redis=lambda: {'ok': True},
        get_dependency_versions=lambda include_dev=False: {'ok': True, 'packages': {}, 'includeDev': include_dev},
        get_server_info=lambda: {'ok': True, 'server': {}},
    )
    deps = _make_deps(database_runtime=db_runtime, operations_runtime=ops_runtime)
    controller = OpsCommandController(**deps)

    controller.ping_db('dev', 'text')
    controller.ping_redis('dev', 'text')
    controller.health('dev', 'text')
    controller.deps('dev', 'text', include_dev=True)
    controller.server_info('dev', 'text')
    db_runtime.ping_database = lambda: {'ok': False}
    controller.health('dev', 'json')
    ops_runtime.get_dependency_versions = lambda include_dev=False: {'ok': False, 'packages': {}}
    controller.deps('dev', 'json', include_dev=False)

    fake = SimpleNamespace(
        ping_db=lambda *a, **k: None,
        ping_redis=lambda *a, **k: None,
        health=lambda *a, **k: None,
        deps=lambda *a, **k: None,
        server_info=lambda *a, **k: None,
    )
    monkeypatch.setattr(ops_command, '_OPS_COMMAND_CONTROLLER', fake)
    ops_command.ping_db('dev', 'text')
    ops_command.ping_redis_command('dev', 'text')
    ops_command.health('dev', 'text')
    ops_command.deps('dev', 'text', include_dev=False)
    ops_command.server_info('dev', 'text')
    OpsCommandController()


# --- db ---


def test_db_controller_and_commands(monkeypatch: MonkeyPatch) -> None:
    runtime = SimpleNamespace(
        ping_database=lambda: {'ok': True},
        get_current_revision=lambda: {'ok': True, 'currentRevision': 'abc'},
        upgrade_database=lambda revision, dry_run=False: {'ok': True, 'revision': revision, 'dryRun': dry_run},
        init_database=lambda dry_run=False: {'ok': True, 'dryRun': dry_run},
        downgrade_database=lambda revision, dry_run=False: {'ok': True, 'revision': revision},
        create_revision=lambda message, autogenerate=False, dry_run=False: {'ok': True, 'message': message},
        get_alembic_heads=lambda: {'ok': True, 'items': [], 'count': 0},
        get_alembic_history=lambda limit=20: {'ok': True, 'items': [], 'count': 0, 'limit': limit},
    )
    deps = _make_deps(runtime_service=runtime)
    controller = DbCommandController(**deps)

    controller.check('dev', 'text')
    controller.current('dev', 'text')
    controller.upgrade('dev', 'text', False, True, True, revision='head')
    controller.init('dev', 'text', False, True, False)
    controller.downgrade('dev', 'text', False, True, False, revision='-1')
    controller.revision('msg', 'dev', 'text', False, True, False, autogenerate=True)
    controller.heads('dev', 'text')
    controller.history('dev', 'text', limit=5)

    fake = SimpleNamespace(
        check=lambda *a, **k: None,
        current=lambda *a, **k: None,
        upgrade=lambda *a, **k: None,
        init=lambda *a, **k: None,
        downgrade=lambda *a, **k: None,
        revision=lambda *a, **k: None,
        heads=lambda *a, **k: None,
        history=lambda *a, **k: None,
    )
    monkeypatch.setattr(db_command, '_DB_COMMAND_CONTROLLER', fake)
    db_command.check('dev', 'text')
    db_command.current('dev', 'text')
    db_command.upgrade('dev', 'text', False, True, False, revision='head')
    db_command.init('dev', 'text', False, True, False)
    db_command.downgrade('dev', 'text', False, True, False, revision='-1')
    db_command.revision('m', 'dev', 'text', False, True, False, autogenerate=False)
    db_command.heads('dev', 'text')
    db_command.history('dev', 'text', limit=10)
    DbCommandController()


# --- dev ---


def test_dev_controller_and_commands(monkeypatch: MonkeyPatch) -> None:
    runtime = SimpleNamespace(
        run_lint=lambda targets, check_only=False, fix=False, unsafe_fixes=False: {
            'ok': True,
            'targets': targets or [],
            'checkOnly': check_only,
            'fix': fix,
            'unsafeFixes': unsafe_fixes,
        },
        run_tests=lambda targets, keyword='', maxfail=0, quiet=False: {
            'ok': True,
            'targets': targets or [],
            'keyword': keyword,
            'maxfail': maxfail,
            'quiet': quiet,
        },
    )
    deps = _make_deps(runtime_service=runtime)
    controller = DevCommandController(**deps)
    controller.lint(['cli'], 'dev', 'text', check_only=True, fix=False, unsafe_fixes=False)
    controller.test(None, 'dev', 'text', keyword='x', maxfail=1, quiet=True)

    fake = SimpleNamespace(lint=lambda *a, **k: None, test=lambda *a, **k: None)
    monkeypatch.setattr(dev_command, '_DEV_COMMAND_CONTROLLER', fake)
    dev_command.lint(None, 'dev', 'text', check_only=False, fix=True, unsafe_fixes=True)
    dev_command.test(['tests'], 'dev', 'text', keyword='', maxfail=0, quiet=False)
    DevCommandController()


# --- crypto ---


def test_crypto_controller_and_commands(monkeypatch: MonkeyPatch) -> None:
    runtime = SimpleNamespace(
        validate_crypto_config=lambda: {'ok': True},
        generate_crypto_key_pair=lambda kid, key_size: {'ok': True, 'kid': kid, 'keySize': key_size},
        build_rotation_payload=lambda next_kid, key_size: {'ok': True, 'nextKid': next_kid, 'keySize': key_size},
        export_public_key=lambda: {'ok': True, 'publicKey': {'kid': 'default'}},
    )
    deps = _make_deps(runtime_service=runtime)
    controller = CryptoCommandController(**deps)
    controller.validate('dev', 'text')
    controller.keygen('dev', 'text', kid='k', key_size=2048)
    controller.rotate('dev', 'text', False, True, True, next_kid='n', key_size=2048)
    controller.export_public('dev', 'text')

    fake = SimpleNamespace(
        validate=lambda *a, **k: None,
        keygen=lambda *a, **k: None,
        rotate=lambda *a, **k: None,
        export_public=lambda *a, **k: None,
    )
    monkeypatch.setattr(crypto_command, '_CRYPTO_COMMAND_CONTROLLER', fake)
    crypto_command.validate('dev', 'text')
    crypto_command.keygen('dev', 'text', kid='default', key_size=2048)
    crypto_command.rotate('dev', 'text', False, True, False, next_kid='rotated', key_size=2048)
    crypto_command.export_public('dev', 'text')
    CryptoCommandController()


# --- config ---


def test_config_controller_and_commands(monkeypatch: MonkeyPatch) -> None:
    runtime = SimpleNamespace(
        list_configs=lambda **kwargs: {'ok': True, 'items': [], 'count': 0, 'filters': kwargs},
        get_config=lambda key, source='both': {'ok': True, 'key': key, 'source': source},
        set_config=lambda key, value, **kwargs: {'ok': True, 'key': key, 'value': value, **kwargs},
        sync_config_cache=lambda: {'ok': True},
        diagnose_config=lambda sample_limit=10: {'ok': True, 'sampleLimit': sample_limit},
    )
    deps = _make_deps(runtime_service=runtime)
    controller = ConfigCommandController(**deps)
    controller.list_configs(
        'dev',
        'text',
        config_name='',
        config_key='',
        config_type=None,
        begin_date='',
        end_date='',
        paged=False,
        page_num=1,
        page_size=20,
    )
    controller.get_config('sys.key', 'dev', 'text', source='both')
    controller.set_config('sys.key', 'dev', 'text', False, True, True, value='v', name='n', config_type='N', remark='r')
    controller.sync_cache('dev', 'text', False, True)
    controller.doctor('dev', 'text', sample_limit=5)

    fake = SimpleNamespace(
        list_configs=lambda *a, **k: None,
        get_config=lambda *a, **k: None,
        set_config=lambda *a, **k: None,
        sync_cache=lambda *a, **k: None,
        doctor=lambda *a, **k: None,
    )
    monkeypatch.setattr(config_command, '_CONFIG_COMMAND_CONTROLLER', fake)
    config_command.list_command(
        'dev',
        'text',
        config_name='',
        config_key='',
        config_type=None,
        begin_date='',
        end_date='',
        paged=False,
        page_num=1,
        page_size=20,
    )
    config_command.get_command('sys.key', 'dev', 'text', source='db')
    config_command.set_command(
        'sys.key', 'dev', 'text', False, True, False, value='v', name=None, config_type=None, remark=None
    )
    config_command.sync_cache('dev', 'text', False, True)
    config_command.doctor('dev', 'text', sample_limit=10)
    ConfigCommandController()


# --- job ---


def test_job_controller_and_commands(monkeypatch: MonkeyPatch) -> None:
    job_runtime = SimpleNamespace(
        list_jobs=lambda **kwargs: {'ok': True, 'items': [], 'count': 0},
        run_job_once=lambda job_id: {'ok': True, 'jobId': job_id},
        get_job_detail=lambda job_id: {'ok': True, 'jobId': job_id, 'job': {'jobId': job_id}},
        list_job_logs=lambda **kwargs: {'ok': True, 'items': [], 'count': 0},
        pause_job=lambda job_id: {'ok': True, 'jobId': job_id},
        resume_job=lambda job_id: {'ok': True, 'jobId': job_id},
    )
    ops_runtime = SimpleNamespace(sync_jobs=lambda: {'ok': True})
    deps = _make_deps(job_runtime=job_runtime, operations_runtime=ops_runtime)
    controller = JobCommandController(**deps)
    controller.list('dev', 'text', job_name='', job_group='', status=None, paged=False, page_num=1, page_size=20)
    controller.run_once(1, 'dev', 'text', False, True)
    controller.detail(1, 'dev', 'text')
    controller.logs(
        'dev',
        'text',
        job_name='',
        job_group='',
        status=None,
        begin_date='',
        end_date='',
        paged=False,
        page_num=1,
        page_size=20,
    )
    controller.pause(1, 'dev', 'text', False, True)
    controller.resume(1, 'dev', 'text', False, True)
    controller.sync('dev', 'text', False, True)

    fake = SimpleNamespace(
        list=lambda *a, **k: None,
        run_once=lambda *a, **k: None,
        detail=lambda *a, **k: None,
        logs=lambda *a, **k: None,
        pause=lambda *a, **k: None,
        resume=lambda *a, **k: None,
        sync=lambda *a, **k: None,
    )
    monkeypatch.setattr(job_command, '_JOB_COMMAND_CONTROLLER', fake)
    job_command.list_command(
        'dev', 'text', job_name='', job_group='', status=None, paged=False, page_num=1, page_size=20
    )
    job_command.run_once(1, 'dev', 'text', False, True)
    job_command.detail(1, 'dev', 'text')
    job_command.logs(
        'dev',
        'text',
        job_name='',
        job_group='',
        status=None,
        begin_date='',
        end_date='',
        paged=False,
        page_num=1,
        page_size=20,
    )
    job_command.pause(1, 'dev', 'text', False, True)
    job_command.resume(1, 'dev', 'text', False, True)
    job_command.sync('dev', 'text', False, True)
    JobCommandController()


# --- gen ---


def test_gen_controller_and_commands(monkeypatch: MonkeyPatch) -> None:
    runtime = SimpleNamespace(
        import_tables=lambda names, dry_run=False: {'ok': True, 'tableNames': names, 'dryRun': dry_run},
        list_gen_tables=lambda **kwargs: {'ok': True, 'items': [], 'count': 0},
        list_gen_db_tables=lambda **kwargs: {'ok': True, 'items': [], 'count': 0},
        get_gen_table_detail=lambda table_id: {'ok': True, 'tableId': table_id, 'detail': {'info': {'className': 'X'}}},
        create_tables=lambda sql, sql_file, dry_run=False: {'ok': True, 'sql': sql, 'sqlFile': sql_file},
        preview_code=lambda table_id: {'ok': True, 'tableId': table_id, 'preview': {}},
        export_code=lambda names, mode='zip', output_file='', dry_run=False: {
            'ok': True,
            'tableNames': names,
            'mode': mode,
            'outputFile': output_file,
            'dryRun': dry_run,
        },
        sync_gen_table_from_db=lambda table_name: {'ok': True, 'tableName': table_name},
    )
    deps = _make_deps(runtime_service=runtime)
    controller = GenCommandController(**deps)
    controller.import_table(['t1'], 'dev', 'text', False, True, True)
    controller.list_tables('dev', 'text', table_name='', table_comment='', paged=False, page_num=1, page_size=20)
    controller.list_db_tables('dev', 'text', table_name='', table_comment='', paged=False, page_num=1, page_size=20)
    controller.show_detail(1, 'dev', 'text')
    controller.create_table('dev', 'text', False, True, False, sql='create', sql_file='')
    controller.preview(1, 'dev', 'text')
    controller.export(['t1'], 'dev', 'text', False, True, False, mode='zip', output_file='out.zip')
    controller.sync_db('t1', 'dev', 'text', False, True)

    fake = SimpleNamespace(
        import_table=lambda *a, **k: None,
        list_tables=lambda *a, **k: None,
        list_db_tables=lambda *a, **k: None,
        show_detail=lambda *a, **k: None,
        create_table=lambda *a, **k: None,
        preview=lambda *a, **k: None,
        export=lambda *a, **k: None,
        sync_db=lambda *a, **k: None,
    )
    monkeypatch.setattr(gen_command, '_GEN_COMMAND_CONTROLLER', fake)
    gen_command.import_table(['t1'], 'dev', 'text', False, True, False)
    gen_command.list_command('dev', 'text', table_name='', table_comment='', paged=False, page_num=1, page_size=20)
    gen_command.db_list('dev', 'text', table_name='', table_comment='', paged=False, page_num=1, page_size=20)
    gen_command.detail(1, 'dev', 'text')
    gen_command.create_table('dev', 'text', False, True, False, sql='', sql_file='a.sql')
    gen_command.preview(1, 'dev', 'text')
    gen_command.export(['t1'], 'dev', 'text', False, True, False, mode='local', output_file='')
    gen_command.sync_db('t1', 'dev', 'text', False, True)
    GenCommandController()


def test_group_packages_export_app() -> None:
    """Import group package __init__ modules that re-export Typer apps."""
    from cli.groups import app as app_pkg
    from cli.groups import cache as cache_pkg
    from cli.groups import config as config_pkg
    from cli.groups import crypto as crypto_pkg
    from cli.groups import db as db_pkg
    from cli.groups import dev as dev_pkg
    from cli.groups import gen as gen_pkg
    from cli.groups import job as job_pkg
    from cli.groups import ops as ops_pkg

    for pkg in (app_pkg, cache_pkg, config_pkg, crypto_pkg, db_pkg, dev_pkg, gen_pkg, job_pkg, ops_pkg):
        assert pkg.app is not None


def test_fake_helpers_cover_dangerous_and_result() -> None:
    factory = FakeContextFactory()
    ctx = factory.build_dangerous('prod', 'json', True, True, False, command_name='x')
    assert ctx.command_name == 'x'
    execution = FakeExecutionService(invoke_text_builders=False)
    execution.complete_payload_result(ctx, {'ok': True}, text_builder=lambda p: 't', default_exit_code=0)
    assert execution.completed_payload_result
