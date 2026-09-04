"""Coverage boost for cli.core (non-execution leftovers) and cli.metadata."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer
from pytest import MonkeyPatch

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _load(name: str):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------


def test_completion_shell_spec_registry_lists_and_gets() -> None:
    specs = _load('cli.metadata.command_specs')
    registry = specs.COMPLETION_SHELL_SPEC_REGISTRY

    names = registry.list_shell_names()
    assert 'bash' in names
    assert 'powershell' in names
    assert registry.get_spec('bash') is not None
    assert registry.get_spec('nope') is None


def test_environment_option_service_discovers_env_files(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    option_specs = _load('cli.metadata.option_specs')
    service = option_specs.EnvironmentOptionService(default_environments=('dev',))

    project = tmp_path / 'proj'
    config_dir = project / 'config'
    config_dir.mkdir(parents=True)
    (project / '.env.staging').write_text('X=1', encoding='utf-8')
    (config_dir / '.env.qa').write_text('Y=1', encoding='utf-8')
    (config_dir / '.env.').write_text('Z=1', encoding='utf-8')  # empty suffix ignored
    missing = tmp_path / 'missing'
    # also hit default-search path branch
    monkeypatch.setattr(
        'config.paths.dotenv_search_dirs',
        lambda: [project, config_dir, missing],
    )

    discovered = service.discover_env_names(project)
    assert 'dev' in discovered
    assert 'staging' in discovered
    assert 'qa' in discovered

    via_default = service.discover_env_names(None)
    assert 'dev' in via_default
    assert 'staging' in via_default


def test_command_risk_spec_registry_builder_and_lookup() -> None:
    risk_specs = _load('cli.metadata.risk_specs')
    guards = _load('cli.guards')
    registry = risk_specs.COMMAND_RISK_SPEC_REGISTRY

    upgrade = registry.get_spec('db upgrade')
    assert upgrade is not None
    assert upgrade.risk_level == 'high'
    assert upgrade.supports_dry_run is True
    assert registry.get_spec('unknown') is None

    rebuilt = risk_specs.CommandRiskSpecRegistryBuilder.build(guards.DEFAULT_DANGEROUS_COMMAND_RULE_REGISTRY)
    assert rebuilt.get_spec('cache clear') is not None


# ---------------------------------------------------------------------------
# core.app_builder
# ---------------------------------------------------------------------------


def test_project_runtime_locator_path_and_argv(monkeypatch: MonkeyPatch) -> None:
    app_builder = _load('cli.core.app_builder')
    locator = app_builder.ProjectRuntimeLocator()

    monkeypatch.setattr(
        app_builder.RUNTIME_ENVIRONMENT,
        'get_backend_dir',
        lambda: str(BACKEND_DIR),
    )
    monkeypatch.setattr(app_builder.RUNTIME_ENVIRONMENT, 'is_backend_project_dir', lambda _p: False)
    with pytest.raises(typer.Exit) as exited:
        locator.ensure_backend_dir_on_sys_path()
    assert exited.value.exit_code == 2

    monkeypatch.setattr(app_builder.RUNTIME_ENVIRONMENT, 'is_backend_project_dir', lambda _p: True)
    # already first on path
    monkeypatch.setattr(sys, 'path', [str(BACKEND_DIR.resolve())] + sys.path[1:])
    assert locator.ensure_backend_dir_on_sys_path() == BACKEND_DIR.resolve()

    # not first — insert
    monkeypatch.setattr(
        sys,
        'path',
        [str(BACKEND_DIR.parent)] + [p for p in sys.path if p != str(BACKEND_DIR.resolve())],
    )
    inserted = locator.ensure_backend_dir_on_sys_path()
    assert inserted == BACKEND_DIR.resolve()
    assert sys.path[0] == str(BACKEND_DIR.resolve())

    assert locator.extract_import_argv(['prog']) == ['prog']
    assert locator.extract_import_argv(['prog', '--env=prod', 'x']) == ['prog', '--env', 'prod']
    assert locator.extract_import_argv(['prog', '--env', 'dockermy']) == ['prog', '--env', 'dockermy']
    assert locator.extract_import_argv(['prog', 'app', 'env']) == ['prog']


def test_cli_extension_mount_support_and_registrars() -> None:
    app_builder = _load('cli.core.app_builder')
    cli = typer.Typer()

    completion_module = SimpleNamespace(
        COMPLETION_COMMAND_BUILDER=SimpleNamespace(build=lambda root: typer.Typer(name='completion'))
    )
    wizard_module = SimpleNamespace(
        WIZARD_COMMAND_BUILDER=SimpleNamespace(build=lambda: typer.Typer(name='wizard'))
    )
    tui_module = SimpleNamespace(TUI_COMMAND_REGISTRATION=SimpleNamespace(register=MagicMock()))

    app_builder.CliExtensionMountSupport.attach_completion(cli, completion_module)
    app_builder.CliExtensionMountSupport.attach_wizard(cli, wizard_module)
    app_builder.CliExtensionMountSupport.attach_tui(cli, tui_module)
    tui_module.TUI_COMMAND_REGISTRATION.register.assert_called_once_with(cli)

    loaded: list[str] = []

    def _fake_load(path: str) -> object:
        loaded.append(path)
        return SimpleNamespace(app=typer.Typer())

    group_reg = app_builder.CliCommandGroupRegistrar(
        command_group_registry=app_builder.CliCommandGroupRegistry(command_modules={'demo': 'pkg.demo'}),
        module_loader=SimpleNamespace(load=_fake_load),
    )
    group_reg.register(cli)
    assert loaded == ['pkg.demo']

    ext_calls: list[str] = []

    def _attach(root: typer.Typer, module: object) -> None:
        del root, module
        ext_calls.append('ok')

    ext_reg = app_builder.CliExtensionRegistrar(
        extension_registry=app_builder.CliExtensionRegistry(
            registrations=(app_builder.CliExtensionRegistration('pkg.ext', _attach),)
        ),
        module_loader=SimpleNamespace(load=lambda _p: SimpleNamespace()),
    )
    ext_reg.register(cli)
    assert ext_calls == ['ok']

    renderer = MagicMock()
    initializer = app_builder.CliRootOptionInitializer(output_renderer=renderer)
    initializer.initialize(color='never', icon='ascii')
    renderer.set_color_mode.assert_called_once_with('never')
    renderer.set_icon_mode.assert_called_once_with('ascii')

    assert app_builder.CliModuleLoader.load('cli.exit_codes') is not None

    # root callback + build path with mocked registrars
    renderer = MagicMock()
    builder = app_builder.CliApplicationBuilder(
        output_renderer=renderer,
        command_group_registrar=SimpleNamespace(register=MagicMock()),
        extension_registrar=SimpleNamespace(register=MagicMock()),
    )
    built = builder.build()
    assert isinstance(built, typer.Typer)
    builder.command_group_registrar.register.assert_called_once_with(built)
    builder.extension_registrar.register.assert_called_once_with(built)
    builder.root_option_initializer.initialize(color='auto', icon='none')
    from typer.testing import CliRunner

    runner = CliRunner()
    # invoke root callback via help to exercise registered callback options
    result = runner.invoke(built, ['--help'])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# core.completion_dispatcher
# ---------------------------------------------------------------------------


def test_completion_instruction_support_and_dispatcher(monkeypatch: MonkeyPatch) -> None:
    dispatcher_mod = _load('cli.core.completion_dispatcher')
    support = dispatcher_mod.CompletionInstructionSupport()
    assert support.is_click_style_instruction('bash_complete') is True
    assert support.is_click_style_instruction('complete_bash') is False
    assert support.is_typer_style_instruction('complete_zsh') is True
    assert support.is_typer_style_instruction('zsh_complete') is False

    reader = dispatcher_mod.CompletionInstructionReader(support)
    monkeypatch.delenv(support.complete_env_var, raising=False)
    assert reader.read_instruction() == ''
    monkeypatch.setenv(support.complete_env_var, '  bash_complete  ')
    assert reader.read_instruction() == 'bash_complete'

    dispatcher = dispatcher_mod.CompletionDispatcher(support=support)
    cli = typer.Typer()

    @cli.callback()
    def _root() -> None:
        return None

    @cli.command()
    def ping() -> None:
        return None

    monkeypatch.setattr(dispatcher_mod, 'ensure_custom_completion_classes_registered', lambda: None)
    monkeypatch.delenv(support.complete_env_var, raising=False)
    dispatcher.dispatch(cli)  # no instruction → return

    monkeypatch.setenv(support.complete_env_var, 'bash_complete')
    monkeypatch.setattr(dispatcher_mod, 'click_shell_complete', lambda *a, **k: 0)
    with pytest.raises(SystemExit) as click_exit:
        dispatcher.dispatch(cli)
    assert click_exit.value.code == 0

    monkeypatch.setenv(support.complete_env_var, 'complete_bash')
    monkeypatch.setattr(dispatcher_mod, 'typer_shell_complete', lambda *a, **k: 3)
    with pytest.raises(SystemExit) as typer_exit:
        dispatcher.dispatch(cli)
    assert typer_exit.value.code == 3

    monkeypatch.setenv(support.complete_env_var, 'weird_instruction')
    with pytest.raises(SystemExit) as bad_exit:
        dispatcher.dispatch(cli)
    assert bad_exit.value.code == 1


# ---------------------------------------------------------------------------
# core.context_factory
# ---------------------------------------------------------------------------


def test_cli_runtime_state_and_context_factory(monkeypatch: MonkeyPatch) -> None:
    ctx_factory_mod = _load('cli.core.context_factory')
    state = ctx_factory_mod.CliRuntimeState()

    fake_logger = SimpleNamespace(remove=MagicMock())
    monkeypatch.setattr(state, 'get_logger', lambda: fake_logger)
    state.suppress_logs()
    state.suppress_logs()  # idempotent
    fake_logger.remove.assert_called_once()

    env_mod = SimpleNamespace(DataBaseConfig=SimpleNamespace(db_echo=True))
    monkeypatch.setattr(ctx_factory_mod, 'import_module', lambda name: env_mod if name == 'config.env' else importlib.import_module(name))
    state.suppress_sqlalchemy_logs()
    state.suppress_sqlalchemy_logs()
    assert env_mod.DataBaseConfig.db_echo is False

    # no DataBaseConfig attr path
    state2 = ctx_factory_mod.CliRuntimeState()
    monkeypatch.setattr(
        ctx_factory_mod,
        'import_module',
        lambda name: SimpleNamespace() if name == 'config.env' else (
            SimpleNamespace(logger=SimpleNamespace(remove=MagicMock()))
            if name == 'utils.log_util'
            else importlib.import_module(name)
        ),
    )
    assert state2.get_logger() is not None
    state2.suppress_sqlalchemy_logs()

    renderer = MagicMock()
    rule_registry = MagicMock()
    rule_registry.require_rule.return_value = SimpleNamespace(command_name='cache clear')
    guard_service = MagicMock()
    guard_service.guard.return_value = SimpleNamespace(data={'ok': False}, exit_code=1)
    support = ctx_factory_mod.DangerousCommandContextSupport(
        dangerous_command_rule_registry=rule_registry,
        dangerous_command_guard_service=guard_service,
        output_renderer=renderer,
    )
    ctx = SimpleNamespace(env='dev', output='json', allow_prod=False, yes=True, dry_run=False)
    assert support.guard_context(ctx, command_name='cache clear') is ctx
    renderer.complete_command.assert_called_once()

    guard_service.guard.return_value = None
    renderer.reset_mock()
    support.guard_context(ctx, command_name='cache clear')
    renderer.complete_command.assert_not_called()

    factory = ctx_factory_mod.CliContextFactory(
        runtime_state=ctx_factory_mod.CliRuntimeState(),
        output_renderer=MagicMock(),
        cli_context_builder=SimpleNamespace(
            build=lambda *a: SimpleNamespace(env=a[0], output=a[1], allow_prod=a[2], yes=a[3], dry_run=a[4])
        ),
        dangerous_command_rule_registry=rule_registry,
        dangerous_command_guard_service=MagicMock(guard=lambda *a, **k: None),
    )
    monkeypatch.setattr(factory.runtime_state, 'suppress_logs', lambda: None)
    monkeypatch.setattr(factory.runtime_state, 'suppress_sqlalchemy_logs', lambda: None)

    assert factory.get_log_policy() is factory.get_log_policy()
    assert factory.get_dangerous_command_support() is factory.get_dangerous_command_support()
    readonly = factory.build_readonly('dev', 'json')
    assert readonly.env == 'dev'
    dangerous = factory.build_dangerous('dev', 'text', False, True, False, command_name='cache clear')
    assert dangerous.env == 'dev'


# ---------------------------------------------------------------------------
# core.execution leftovers (beyond build_result)
# ---------------------------------------------------------------------------


def test_cli_execution_service_complete_paths() -> None:
    execution = _load('cli.core.execution')
    renderer = MagicMock()
    service = execution.CliExecutionService(output_renderer=renderer)

    async def _coro() -> str:
        return 'async-ok'

    assert service.run_async(_coro()) == 'async-ok'

    ctx_json = SimpleNamespace(output='json')
    ctx_text = SimpleNamespace(output='text')
    payload = {'ok': True, 'message': 'done'}

    service.complete_payload(ctx_json, payload)
    renderer.complete_command.assert_called()

    renderer.reset_mock()
    service.complete_result(ctx_json, execution.CommandResult(data=payload, exit_code=0))
    renderer.complete_command.assert_called_once()

    renderer.reset_mock()
    service.complete_payload_with_text(
        ctx_json,
        payload,
        text_builder=lambda d: 'TEXT',
    )
    # json path → complete_payload, no text builder
    assert renderer.complete_command.call_count == 1

    renderer.reset_mock()
    service.complete_payload_with_text(
        ctx_text,
        payload,
        text_builder=lambda d: f"TXT:{d['message']}",
        text_condition=lambda d: True,
    )
    result_arg = renderer.complete_command.call_args[0][0]
    assert result_arg.data == 'TXT:done'

    renderer.reset_mock()
    service.complete_payload_with_text(
        ctx_text,
        payload,
        text_builder=lambda d: 'SHOULD_NOT',
        text_condition=lambda d: False,
    )
    assert renderer.complete_command.call_args[0][0].data == payload

    renderer.reset_mock()
    service.complete_payload_result(ctx_json, payload)
    assert renderer.complete_command.call_count == 1

    renderer.reset_mock()
    service.complete_payload_result(
        ctx_text,
        payload,
        text_builder=lambda d: 'built',
        text_condition=None,
    )
    assert renderer.complete_command.call_args[0][0].data == 'built'
