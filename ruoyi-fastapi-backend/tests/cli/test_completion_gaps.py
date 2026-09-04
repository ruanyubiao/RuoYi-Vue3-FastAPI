"""Coverage boost for cli.completion leftovers (doctor/controller/presenter/shells/commands)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import typer
from click.shell_completion import CompletionItem
from pytest import MonkeyPatch

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _load(name: str):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


def test_completion_doctor_payload(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    doctor_mod = _load('cli.completion.doctor')
    shell_specs = _load('cli.metadata.command_specs')

    target = tmp_path / 'ruoyi.bash'
    target.write_text('# complete', encoding='utf-8')
    rc = tmp_path / '.bashrc'
    rc.write_text('# rc', encoding='utf-8')

    installer = SimpleNamespace(
        detect_active_shell=lambda: 'bash',
        resolve_completion_target=lambda shell: target if shell == 'bash' else tmp_path / f'{shell}.comp',
        resolve_completion_rc_file=lambda shell: rc if shell == 'bash' else None,
        build_source_command=lambda target_file, shell: f'source {target_file}',
    )
    env_service = SimpleNamespace(discover_env_names=lambda: ['dev', 'prod'])
    monkeypatch.setattr(
        doctor_mod.RUNTIME_ENVIRONMENT,
        'get_backend_dir',
        lambda: str(BACKEND_DIR),
    )

    service = doctor_mod.CompletionDoctorService(
        installer_service=installer,
        shell_spec_registry=shell_specs.COMPLETION_SHELL_SPEC_REGISTRY,
        environment_option_service=env_service,
    )
    payload = service.build_completion_doctor_payload()
    assert payload['ok'] is True
    assert payload['activeShell'] == 'bash'
    assert 'bash' in payload['shells']
    assert payload['shells']['bash']['detected'] is True
    assert payload['shells']['bash']['targetFileExists'] is True
    assert 'activate' in payload['recommendedInstallCommand']

    # unknown active shell → recommendedInstallCommand None
    installer_unknown = SimpleNamespace(
        detect_active_shell=lambda: 'tcsh',
        resolve_completion_target=lambda shell: tmp_path / shell,
        resolve_completion_rc_file=lambda shell: None,
        build_source_command=lambda *_a: 'source x',
    )
    service2 = doctor_mod.CompletionDoctorService(
        installer_service=installer_unknown,
        shell_spec_registry=shell_specs.COMPLETION_SHELL_SPEC_REGISTRY,
        environment_option_service=env_service,
    )
    payload2 = service2.build_completion_doctor_payload()
    assert payload2['recommendedInstallCommand'] is None


def test_completion_presenter_text() -> None:
    presenter_mod = _load('cli.completion.presenter')
    presenter = presenter_mod.CompletionCommandPresenter()

    doctor_text = presenter.build_completion_doctor_text(
        {
            'ok': True,
            'message': 'done',
            'activeShell': 'bash',
            'projectDir': '/tmp',
            'completeEnvVar': '_RUOYI_COMPLETE',
            'recommendedInstallCommand': 'ruoyi completion install --shell=bash --activate',
            'envChoices': ['dev', 'prod'],
            'shells': {
                'bash': {
                    'supported': True,
                    'detected': True,
                    'targetFile': '/t',
                    'targetFileExists': True,
                    'rcFile': '/rc',
                    'rcFileExists': False,
                    'autoDiscovery': False,
                    'sourceCommand': 'source /t',
                    'recommendedInstallCommand': 'ruoyi completion install --shell=bash --activate',
                },
                'bad': 'skip-me',
            },
        }
    )
    assert 'active_shell: bash' in doctor_text
    assert 'env_choices:' in doctor_text
    assert '  bash:' in doctor_text

    minimal = presenter.build_completion_doctor_text({'ok': False})
    assert 'ok: false' in minimal

    install_text = presenter.build_completion_install_text(
        {
            'ok': True,
            'message': 'installed',
            'shell': 'bash',
            'detectedShell': 'bash',
            'targetFile': '/t',
            'activated': True,
            'activateRequested': True,
            'rcFile': '/rc',
            'rcFileUpdated': True,
            'sourceCommand': 'source /t',
            'autoDiscovery': False,
            'activationRequired': True,
            'nextStep': 'reload',
            'completeEnvVar': '_RUOYI_COMPLETE',
        }
    )
    assert 'target_file: /t' in install_text
    assert 'next_step: reload' in install_text


def test_completion_controller_methods(monkeypatch: MonkeyPatch) -> None:
    controller_mod = _load('cli.completion.controller')
    root = typer.Typer()
    ctx = SimpleNamespace(output='text', env='dev')
    context_factory = SimpleNamespace(build_readonly=MagicMock(return_value=ctx))
    execution = SimpleNamespace(complete_payload_result=MagicMock())
    presenter = SimpleNamespace(
        build_completion_install_text=lambda p: 'install',
        build_completion_doctor_text=lambda p: 'doctor',
    )
    installer = SimpleNamespace(
        render_completion_script=MagicMock(return_value='SCRIPT'),
        install_completion_script=MagicMock(return_value={'ok': True, 'shell': 'bash'}),
    )
    doctor = SimpleNamespace(build_completion_doctor_payload=MagicMock(return_value={'ok': True}))

    controller = controller_mod.CompletionCommandController(
        root,
        context_factory=context_factory,
        execution_service=execution,
        presenter=presenter,
        installer_service=installer,
        doctor_service=doctor,
    )

    echoed: list[str] = []

    def _echo(text: str, nl: bool = True) -> None:
        del nl
        echoed.append(text)

    monkeypatch.setattr(typer, 'echo', _echo)
    controller.show('bash')
    installer.render_completion_script.assert_called_once()
    assert echoed == ['SCRIPT']

    controller.install(
        'json',
        shell='bash',
        target_file=None,
        activate=True,
        rc_file=None,
        force=False,
    )
    execution.complete_payload_result.assert_called()
    controller.doctor('text')
    doctor.build_completion_doctor_payload.assert_called_once()


def test_powershell_complete_and_registration(monkeypatch: MonkeyPatch) -> None:
    shells = _load('cli.completion.shells')
    shells.ensure_custom_completion_classes_registered()
    shells.ensure_custom_completion_classes_registered()  # idempotent

    monkeypatch.setenv('COMP_WORDS', 'ruoyi app en')
    monkeypatch.setenv('COMP_CWORD', 'en')
    ps = shells.PowerShellComplete(cli=MagicMock(), ctx_args={}, prog_name='ruoyi', complete_var='_RUOYI_COMPLETE')
    args, incomplete = ps.get_completion_args()
    assert incomplete == 'en'
    assert 'app' in args or args == ['app']

    monkeypatch.setenv('COMP_WORDS', 'ruoyi')
    monkeypatch.setenv('COMP_CWORD', '')
    args2, incomplete2 = ps.get_completion_args()
    assert incomplete2 == ''
    assert args2 == []

    formatted = ps.format_completion(CompletionItem('plain', type='plain', help='help text'))
    assert formatted == 'plain\tplain\thelp text'
    formatted2 = ps.format_completion(CompletionItem('x', type='file'))
    assert formatted2.endswith('\tx')


def test_completion_commands_builder_registers_and_invokes(monkeypatch: MonkeyPatch) -> None:
    commands = _load('cli.completion.commands')
    root = typer.Typer()

    show_calls: list[str] = []
    install_calls: list[object] = []
    doctor_calls: list[str] = []

    fake_controller = SimpleNamespace(
        show=lambda shell: show_calls.append(shell),
        install=lambda output, **kwargs: install_calls.append((output, kwargs)),
        doctor=lambda output: doctor_calls.append(output),
    )
    monkeypatch.setattr(
        commands,
        'CompletionCommandController',
        lambda root_cli: fake_controller,
    )

    app = commands.CompletionCommandBuilder().build(root)
    from typer.testing import CliRunner

    runner = CliRunner()
    result_show = runner.invoke(app, ['show', 'bash'])
    assert result_show.exit_code == 0
    assert show_calls == ['bash']

    result_install = runner.invoke(app, ['install', '--shell=zsh', '--output=json', '--activate', '--force'])
    assert result_install.exit_code == 0
    assert install_calls
    assert install_calls[0][0] == 'json'

    result_doctor = runner.invoke(app, ['doctor', '--output=text'])
    assert result_doctor.exit_code == 0
    assert doctor_calls == ['text']

    regs = commands.CompletionSubcommandRegistrar.build_registrations()
    assert {r.name for r in regs} == {'show', 'install', 'doctor'}
