"""Close leftover coverage gaps in cli.completion.installers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
from pytest import MonkeyPatch

from cli.completion.installers import (
    COMPLETION_INSTALLER,
    CompletionInstallerService,
    CompletionInstallerShellSupport,
    CompletionShellRuntimePolicy,
    CompletionShellRuntimePolicyRegistry,
)
from cli.exit_codes import ARGUMENT_ERROR, RUNTIME_ERROR
from cli.metadata import CompletionShellSpec, CompletionShellSpecRegistry


def _shell_spec(
    name: str = 'bash',
    *,
    supported: bool = True,
    generator: str = 'click',
    default_target: str = '.local/share/ruoyi/completion/ruoyi.bash',
    default_rc_file: str | None = '.bashrc',
    auto_discovery: bool = False,
) -> CompletionShellSpec:
    return CompletionShellSpec(
        name=name,
        description=f'{name} spec',
        generator=generator,  # type: ignore[arg-type]
        default_target=default_target,
        default_rc_file=default_rc_file,
        auto_discovery=auto_discovery,
        supported=supported,
    )


def test_bash_compatibility_keeps_passthrough_lines() -> None:
    script = 'echo keep-me\ncompopt -o dirnames\nother line'
    result = CompletionInstallerShellSupport.make_bash_completion_script_compatible(script)
    assert 'echo keep-me' in result
    assert 'other line' in result
    assert CompletionInstallerShellSupport.keep_script_text('raw') == 'raw'


def test_resolve_shell_spec_and_runtime_policy_errors() -> None:
    installer = CompletionInstallerService(
        completion_provider_gateway=SimpleNamespace(list_completion_shells=lambda: ['bash']),
        shell_spec_registry=CompletionShellSpecRegistry(specs={'bash': _shell_spec()}),
        shell_runtime_policy_registry=CompletionShellRuntimePolicyRegistry(policies={}),
    )
    with pytest.raises(typer.BadParameter, match='不支持的 shell'):
        installer.resolve_completion_shell_spec('tcsh')

    with pytest.raises(typer.BadParameter, match='未实现'):
        installer.resolve_shell_runtime_policy('bash')


def test_render_completion_script_rejects_unsupported_generator() -> None:
    installer = CompletionInstallerService(
        shell_spec_registry=CompletionShellSpecRegistry(
            specs={'bash': _shell_spec(generator='unsupported', supported=True)}
        )
    )
    with pytest.raises(typer.BadParameter, match='未实现'):
        installer.render_completion_script(typer.Typer(), 'bash')


def test_resolve_target_and_rc_paths(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', lambda: home)

    installer = CompletionInstallerService(
        shell_spec_registry=CompletionShellSpecRegistry(
            specs={
                'bash': _shell_spec(),
                'fish': _shell_spec(
                    'fish',
                    default_target='.config/fish/completions/ruoyi.fish',
                    default_rc_file=None,
                    auto_discovery=True,
                ),
            }
        )
    )

    explicit = tmp_path / 'custom.bash'
    assert installer.resolve_completion_target('bash', explicit) == explicit.resolve()
    default_target = installer.resolve_completion_target('bash')
    assert default_target == (home / '.local/share/ruoyi/completion/ruoyi.bash').resolve()

    rc_explicit = tmp_path / 'rc'
    assert installer.resolve_completion_rc_file('bash', rc_explicit) == rc_explicit.resolve()
    assert installer.resolve_completion_rc_file('bash') == (home / '.bashrc').resolve()
    assert installer.resolve_completion_rc_file('fish') is None


def test_detect_and_resolve_install_shell(monkeypatch: MonkeyPatch) -> None:
    installer = CompletionInstallerService(
        completion_provider_gateway=SimpleNamespace(list_completion_shells=lambda: ['bash', 'zsh']),
        shell_spec_registry=CompletionShellSpecRegistry(specs={'bash': _shell_spec(), 'zsh': _shell_spec('zsh')}),
    )

    monkeypatch.delenv('SHELL', raising=False)
    assert installer.detect_active_shell() == ''
    with pytest.raises(typer.BadParameter, match='未检测到'):
        installer.resolve_install_shell(None)

    monkeypatch.setenv('SHELL', '/usr/bin/zsh')
    assert installer.detect_active_shell() == 'zsh'
    assert installer.resolve_install_shell(None) == 'zsh'
    assert installer.resolve_install_shell('  bash ') == 'bash'

    monkeypatch.setenv('SHELL', '/bin/tcsh')
    with pytest.raises(typer.BadParameter, match='不在支持列表'):
        installer.resolve_install_shell('')


def test_append_activation_line_writes_and_skips(tmp_path: Path) -> None:
    rc = tmp_path / 'nested' / '.bashrc'
    source = 'source /tmp/ruoyi.bash'

    assert CompletionInstallerService.append_activation_line(rc, source) is True
    assert source in rc.read_text(encoding='utf-8')
    assert CompletionInstallerService.append_activation_line(rc, source) is False

    rc.write_text('existing-without-newline', encoding='utf-8')
    assert CompletionInstallerService.append_activation_line(rc, 'source /other') is True
    text = rc.read_text(encoding='utf-8')
    assert 'existing-without-newline\n' in text
    assert text.endswith('source /other\n')


def test_install_completion_script_paths(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', lambda: home)
    monkeypatch.setenv('SHELL', '/bin/bash')

    target = tmp_path / 'completions' / 'ruoyi.bash'
    rc = tmp_path / '.bashrc'

    class DummyComplete:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        @staticmethod
        def source() -> str:
            return 'SCRIPT-BODY\n'

    registry = CompletionShellSpecRegistry(
        specs={
            'bash': _shell_spec(auto_discovery=False),
            'fish': _shell_spec(
                'fish',
                default_target='.config/fish/completions/ruoyi.fish',
                default_rc_file=None,
                auto_discovery=True,
            ),
            'nosupport': _shell_spec('nosupport', supported=False, generator='unsupported'),
        }
    )
    policies = CompletionShellRuntimePolicyRegistry(
        policies={
            'bash': CompletionShellRuntimePolicy(
                name='bash',
                click_completion_class=DummyComplete,
                script_transformer=lambda text: text,
                source_command_builder=lambda path: f'source {path.as_posix()}',
            ),
            'fish': CompletionShellRuntimePolicy(
                name='fish',
                click_completion_class=DummyComplete,
                script_transformer=lambda text: text,
                source_command_builder=lambda path: f'source {path.as_posix()}',
            ),
        }
    )
    installer = CompletionInstallerService(
        completion_provider_gateway=SimpleNamespace(list_completion_shells=lambda: ['bash', 'fish']),
        shell_spec_registry=registry,
        shell_runtime_policy_registry=policies,
    )
    monkeypatch.setattr(installer, 'build_completion_click_command', lambda root_cli: object())

    unsupported = installer.install_completion_script(typer.Typer(), 'nosupport')
    assert unsupported['ok'] is False
    assert unsupported['exit_code'] == ARGUMENT_ERROR

    target.parent.mkdir(parents=True)
    target.write_text('DIFFERENT\n', encoding='utf-8')
    conflict = installer.install_completion_script(typer.Typer(), 'bash', target_file=target, force=False)
    assert conflict['ok'] is False
    assert conflict['exit_code'] == RUNTIME_ERROR

    installed = installer.install_completion_script(
        typer.Typer(),
        'bash',
        target_file=target,
        activate=True,
        rc_file=rc,
        force=True,
    )
    assert installed['ok'] is True
    assert installed['activated'] is True
    assert installed['rcFileUpdated'] is True
    assert '重启' in installed['nextStep'] or 'source' in installed['nextStep']
    assert target.read_text(encoding='utf-8') == 'SCRIPT-BODY\n'

    no_activate = installer.install_completion_script(
        typer.Typer(),
        'bash',
        target_file=target,
        activate=False,
        force=True,
    )
    assert no_activate['activationRequired'] is True
    assert '--activate' in no_activate['nextStep']

    fish_target = tmp_path / 'ruoyi.fish'
    fish = installer.install_completion_script(typer.Typer(), 'fish', target_file=fish_target, force=True)
    assert fish['ok'] is True
    assert fish['autoDiscovery'] is True
    assert '自动发现' in fish['nextStep']

    assert COMPLETION_INSTALLER is not None
