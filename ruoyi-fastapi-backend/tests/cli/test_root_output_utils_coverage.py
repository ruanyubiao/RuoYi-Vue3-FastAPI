"""Coverage boost for cli root leftovers: output, utils, guards, bootstrap, main."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import click
import pytest
import typer
from pytest import MonkeyPatch

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _load(name: str):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


class _FakeStream:
    def __init__(self, *, is_tty: bool) -> None:
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


# ---------------------------------------------------------------------------
# output.py leftovers
# ---------------------------------------------------------------------------


def test_output_status_styler_auto_color_and_edge_styles(monkeypatch: MonkeyPatch) -> None:
    output = _load('cli.output')
    renderer = output.OutputRenderer(color_mode='auto', icon_mode='emoji')

    monkeypatch.setenv('NO_COLOR', '1')
    assert renderer.supports_color(_FakeStream(is_tty=True)) is False
    monkeypatch.delenv('NO_COLOR', raising=False)

    monkeypatch.setenv('TERM', 'dumb')
    assert renderer.supports_color(_FakeStream(is_tty=True)) is False
    monkeypatch.delenv('TERM', raising=False)

    assert renderer.supports_color(_FakeStream(is_tty=False)) is False
    assert renderer.supports_color(_FakeStream(is_tty=True)) is True

    assert renderer.style_scalar_text('null')
    assert renderer.style_scalar_text('false')
    assert renderer.style_scalar_text('plain') == 'plain'
    assert renderer.style_inline_status_value('true') != 'true'
    assert ' | ' in renderer.style_inline_status_value('true | exported')

    assert renderer.style_named_value('ok', 'true')
    assert renderer.style_named_value('ok', 'false')
    assert renderer.style_named_value('message', 'hello')
    assert renderer.style_named_value('custom_field', 'plain-value')
    assert renderer.style_line('') == ''
    assert renderer.style_line('   ') == '   '
    assert 'SUCCESS' in renderer.style_line(renderer.build_result_header(True))
    assert 'FAILED' in renderer.style_line(renderer.build_result_header(False))
    assert renderer.style_line('- item')
    assert renderer.style_line('section:')
    assert renderer.style_line('|')
    assert renderer.style_line('no-colon-line') == 'no-colon-line'


def test_output_structured_renderer_nested_and_decorate() -> None:
    output = _load('cli.output')
    renderer = output.OutputRenderer(color_mode='never', icon_mode='none')

    assert renderer.render_text_output('already text') == 'already text'
    assert renderer.format_scalar(None) == 'null'
    assert renderer.format_scalar(True) == 'true'
    assert renderer.format_field_name('') == ''
    assert renderer.format_field_name('FooBar') == 'foo_bar'

    lines: list[str] = []
    renderer.append_multiline_text(lines, 'note:', 'a\nb', '  ')
    assert lines[0].endswith('|')

    nested_empty = renderer.render_nested_lines('items:', {}, 0)
    assert nested_empty == ['items: {}']
    nested_list = renderer.render_nested_lines('items:', [1, 2], 0)
    assert nested_list[0] == 'items:'

    assert renderer.render_mapping_lines({}, indent_level=0) == ['{}']
    mapping = renderer.render_mapping_lines(
        {'ok': True, 'note': 'line1\nline2', 'nested': {}, 'items': []},
        indent_level=0,
    )
    assert any('ok:' in line for line in mapping)

    assert renderer.render_list_lines([], indent_level=0) == ['[]']
    list_lines = renderer.render_list_lines(
        ['plain', 'multi\nline', {'a': 1}, [2]],
        indent_level=0,
    )
    assert any(line.startswith('-') for line in list_lines)

    assert renderer.render_text_lines('multi\nline', indent_level=1)
    assert renderer.render_text_lines(42, indent_level=0) == ['42']

    assert renderer.decorate_text_output('') == ''
    assert renderer.decorate_text_output('\n\n') == '\n\n'
    assert renderer.decorate_text_output('plain message') == 'plain message'
    decorated = renderer.decorate_text_output('\nok: true\nmessage: x')
    assert 'SUCCESS' in decorated


def test_output_emitter_and_renderer_facade(capsys: pytest.CaptureFixture[str]) -> None:
    output = _load('cli.output')
    renderer = output.OutputRenderer(color_mode='never', icon_mode='ascii')

    assert renderer.color_mode == 'never'
    assert renderer.icon_mode == 'ascii'
    assert renderer.style_text('x', fg='red')
    assert renderer.build_status_token('ok')
    assert renderer.style_status_token('ok', fg='green')
    assert renderer.style_status_message('info', 'hi')
    assert renderer.build_result_header(True)
    assert renderer.style_scalar_text('true')
    assert renderer.style_inline_status_segment('error: boom')
    assert renderer.style_inline_status_value('true')
    assert renderer.style_named_value('hint', 'use --yes')
    assert renderer.style_line('hint: use --yes')
    assert renderer.render_text_output({'ok': True})
    assert renderer.colorize_text_output('ok: true', _FakeStream(is_tty=False)) == 'ok: true'
    assert renderer.decorate_text_output('ok: false')
    assert renderer.format_scalar(False) == 'false'
    assert renderer.format_field_name('camelCase') == 'camel_case'
    lines: list[str] = []
    renderer.append_multiline_text(lines, 'p:', 'a\nb', ' ')
    assert renderer.render_nested_lines('k:', {'a': 1}, 0)
    assert renderer.render_mapping_lines({'a': 1}, indent_level=0)
    assert renderer.render_list_lines([1], indent_level=0)
    assert renderer.render_text_lines({'a': 1})

    renderer.emit_output(None, 'text')
    renderer.emit_output({'ok': True}, 'json')
    renderer.emit_output({'ok': True, 'message': 'hi'}, 'text')
    renderer.emit_error('boom', 'json', exit_code=7)
    renderer.emit_error('boom', 'text', exit_code=7)
    captured = capsys.readouterr()
    assert 'ok' in captured.out
    assert 'boom' in captured.err

    ctx = SimpleNamespace(output='json')
    with pytest.raises(typer.Exit) as exited:
        renderer.complete_command(output.CommandResult(data={'ok': True}, exit_code=0), ctx)
    assert exited.value.exit_code == 0

    with pytest.raises(typer.Exit):
        renderer.complete_command(
            output.CommandResult(data={'ok': True}, exit_code=0, already_printed=True),
            ctx,
        )


# ---------------------------------------------------------------------------
# utils.py leftovers
# ---------------------------------------------------------------------------


def test_utils_shell_formatter_and_env_and_exec(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    utils = _load('cli.utils')

    assert utils.SHELL_TEXT_FORMATTER.format_shell_command(['echo', 'a b'])
    assert utils.SHELL_TEXT_FORMATTER.truncate_text(None, 10) == ''
    assert utils.SHELL_TEXT_FORMATTER.truncate_text('short', 10) == 'short'
    assert utils.SHELL_TEXT_FORMATTER.truncate_text('abcdefghijkl', 8).endswith('...')
    assert utils.SHELL_TEXT_FORMATTER.to_snake_case(None) == ''
    assert utils.SHELL_TEXT_FORMATTER.to_snake_case('') == ''
    assert utils.SHELL_TEXT_FORMATTER.to_snake_case('Foo-Bar Baz') == 'foo__bar__baz'

    project = tmp_path / 'backend'
    project.mkdir()
    monkeypatch.delenv('PYTHONPATH', raising=False)
    env = utils.NestedCliEnvironmentBuilder.build_process_env(project)
    assert env['PYTHONPATH'] == str(project)
    monkeypatch.setenv('PYTHONPATH', 'existing')
    env2 = utils.NestedCliEnvironmentBuilder.build_process_env(project)
    assert str(project) in env2['PYTHONPATH']
    assert 'existing' in env2['PYTHONPATH']

    monkeypatch.setattr(
        utils.RUNTIME_ENVIRONMENT,
        'is_backend_project_dir',
        lambda _p: True,
    )
    assert utils.NestedCliProjectLocator.is_backend_project_dir(project) is True

    recorded: dict[str, object] = {}

    def _fake_execvp(executable: str, args: list[str]) -> None:
        recorded['executable'] = executable
        recorded['args'] = args

    monkeypatch.setattr(utils.os, 'chdir', lambda _p: None)
    monkeypatch.setattr(utils.os, 'execvp', _fake_execvp)
    monkeypatch.setattr(
        utils.NESTED_CLI_SUPPORT,
        'project_locator',
        SimpleNamespace(resolve_project_dir=lambda: project),
    )
    utils.NESTED_CLI_SUPPORT.exec('app', 'env')
    assert recorded['executable']
    assert 'cli.main' in recorded['args']


# ---------------------------------------------------------------------------
# guards.py leftovers
# ---------------------------------------------------------------------------


def test_guards_confirmation_and_prod_block(monkeypatch: MonkeyPatch) -> None:
    guards = _load('cli.guards')
    builder = guards.DangerousCommandResultBuilder()
    reject = builder.build_guard_reject_result('msg', 'hint')
    assert reject.data['ok'] is False

    confirmation = guards.DangerousCommandConfirmationService(builder)
    ctx_yes = SimpleNamespace(env='dev', yes=True, dry_run=False, allow_prod=False)
    assert confirmation.confirm(ctx_yes, command_name='cache clear') is None

    class _Broken:
        def isatty(self) -> bool:
            raise RuntimeError('broken')

    monkeypatch.setattr(guards.sys, 'stdin', _Broken())
    monkeypatch.setattr(guards.sys, 'stdout', _Broken())
    assert confirmation._can_prompt() is False

    class _Tty:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(guards.sys, 'stdin', _Tty())
    monkeypatch.setattr(guards.sys, 'stdout', _Tty())
    assert confirmation._can_prompt() is True

    ctx_no = SimpleNamespace(env='dev', yes=False, dry_run=True, allow_prod=False)
    monkeypatch.setattr(guards.sys, 'stdin', SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(guards.sys, 'stdout', SimpleNamespace(isatty=lambda: True))
    blocked = confirmation.confirm(ctx_no, command_name='db upgrade')
    assert blocked is not None
    assert blocked.data['ok'] is False

    monkeypatch.setattr(guards.sys, 'stdin', _Tty())
    monkeypatch.setattr(guards.sys, 'stdout', _Tty())
    monkeypatch.setattr(guards.typer, 'confirm', lambda *a, **k: True)
    assert confirmation.confirm(ctx_no, command_name='db upgrade') is None

    monkeypatch.setattr(guards.typer, 'confirm', lambda *a, **k: False)
    denied = confirmation.confirm(ctx_no, command_name='db upgrade')
    assert denied is not None

    def _abort(*_a, **_k):
        raise click.Abort()

    monkeypatch.setattr(guards.typer, 'confirm', _abort)
    aborted = confirmation.confirm(ctx_no, command_name='db upgrade')
    assert aborted is not None

    guard = guards.DEFAULT_DANGEROUS_COMMAND_GUARD
    prod_ctx = SimpleNamespace(env='prod', allow_prod=False, yes=True, dry_run=False)
    rule = guards.DEFAULT_DANGEROUS_COMMAND_RULE_REGISTRY.require_rule('cache clear')
    prod_reject = guard.guard(prod_ctx, rule=rule)
    assert prod_reject is not None

    prod_ok = SimpleNamespace(env='prod', allow_prod=True, yes=True, dry_run=False)
    assert guard.guard(prod_ok, rule=rule) is None


# ---------------------------------------------------------------------------
# bootstrap.py leftovers
# ---------------------------------------------------------------------------


def test_bootstrap_build_and_exec(monkeypatch: MonkeyPatch) -> None:
    bootstrap = _load('cli.bootstrap')
    runtime = SimpleNamespace(
        get_backend_dir=lambda: str(BACKEND_DIR),
        get_python_executable=lambda: sys.executable,
    )
    service = bootstrap.AppBootstrapService(runtime_environment=runtime)
    entry = service.get_app_entry_path()
    assert entry.endswith('app.py')
    command = service.build_app_run_command('dev')
    assert command[0] == sys.executable
    assert '--env' in command

    recorded: list[object] = []

    def _fake_execvp(exe: str, args: list[str]) -> None:
        recorded.extend([exe, args])

    monkeypatch.setattr(bootstrap.os, 'execvp', _fake_execvp)
    service.exec_app_run_command('prod')
    assert recorded[0] == sys.executable


# ---------------------------------------------------------------------------
# main.py leftovers
# ---------------------------------------------------------------------------


def test_main_import_argv_scope_and_runner(monkeypatch: MonkeyPatch) -> None:
    main = _load('cli.main')
    monkeypatch.setattr(sys, 'argv', ['ruoyi', '--env', 'prod', 'app', 'env'])

    seen: list[list[str]] = []

    def _callback() -> str:
        seen.append(list(sys.argv))
        return 'built'

    result = main.CLI_MAIN_RUNNER.import_argv_scope.run(_callback)
    assert result == 'built'
    assert seen[0][:3] == ['ruoyi', '--env', 'prod']

    built_calls: list[object] = []

    class _Cli:
        def __call__(self, *, prog_name: str) -> None:
            built_calls.append(prog_name)

    cli_obj = _Cli()
    fake_locator = SimpleNamespace(ensure_backend_dir_on_sys_path=lambda: BACKEND_DIR)
    fake_builder = SimpleNamespace(build=lambda: cli_obj)
    fake_dispatcher = SimpleNamespace(dispatch=lambda _cli: None)
    runner = main.CliMainRunner(
        project_runtime_locator=fake_locator,
        completion_dispatcher=fake_dispatcher,
        application_builder=fake_builder,
        import_argv_scope=main.CliImportArgvScope(
            project_runtime_locator=SimpleNamespace(extract_import_argv=lambda argv: argv[:1])
        ),
    )
    runner.run()
    assert built_calls == ['ruoyi']

    monkeypatch.setattr(main, 'CLI_MAIN_RUNNER', SimpleNamespace(run=lambda: built_calls.append('main')))
    main.main()
    assert 'main' in built_calls
