"""Close leftover coverage gaps in cli.wizard commands and flows."""

from __future__ import annotations

from types import ModuleType, SimpleNamespace

import pytest
from pytest import MonkeyPatch
from typer.testing import CliRunner


def test_wizard_command_builder_invokes_flow_loaders(monkeypatch: MonkeyPatch) -> None:
    from cli.wizard import commands as wizard_commands

    calls: list[tuple[str, tuple, dict]] = []

    def fake_load(module_name: str, function_name: str):
        def _runner(*args, **kwargs):
            calls.append((f'{module_name}:{function_name}', args, kwargs))

        return _runner

    monkeypatch.setattr(wizard_commands.WizardFlowLoader, 'load_runner', lambda self, m, f: fake_load(m, f))
    app = wizard_commands.WizardCommandBuilder().build()
    runner = CliRunner()

    assert runner.invoke(app, ['app-run']).exit_code == 0
    assert runner.invoke(app, ['db-upgrade', '--output=text']).exit_code == 0
    assert runner.invoke(app, ['cache-clear', '--output=json']).exit_code == 0
    assert runner.invoke(app, ['gen-export', '--output=text']).exit_code == 0
    assert runner.invoke(app, ['gen-import', '--output=text']).exit_code == 0
    assert runner.invoke(app, ['prod-check', '--output=json']).exit_code == 0
    assert len(calls) == 6
    assert any('app_run' in name for name, *_ in calls)
    assert any('prod_check' in name for name, *_ in calls)


def test_app_run_prepare_execution_and_preview_notes(
    monkeypatch: MonkeyPatch,
    app_run_flow: ModuleType,
) -> None:
    flow = app_run_flow.AppRunWizardFlow()
    selection = app_run_flow.AppRunWizardSelection(env='dev', run_doctor=True)

    monkeypatch.setattr(
        flow,
        'run_nested_command',
        lambda *args, **kwargs: SimpleNamespace(payload={'ok': False, 'message': 'doctor failed'}),
    )
    flow.prepare_execution_state(selection, 'text')
    assert flow.doctor_payload == {'ok': False, 'message': 'doctor failed'}
    notes = flow.build_preview_notes(selection)
    assert notes == ['doctor failed']

    monkeypatch.setattr(
        flow,
        'run_nested_command',
        lambda *args, **kwargs: SimpleNamespace(payload='not-dict'),
    )
    flow.prepare_execution_state(selection, 'text')
    assert flow.doctor_payload is None


def test_cache_clear_modes_and_allow_prod(
    monkeypatch: MonkeyPatch,
    cache_clear_flow: ModuleType,
) -> None:
    flow = cache_clear_flow.CacheClearWizardFlow(default_mode='cache-key', default_cache_key='site')

    # cache-key mode + prod allow
    answers = iter(['prod', 'cache-key', 'site.name', False, True])
    monkeypatch.setattr(
        flow,
        'prompt_service',
        SimpleNamespace(
            prompt_env=lambda default_env='dev': next(answers),
            prompt_choice=lambda *a, **k: next(answers),
            prompt_required_text=lambda *a, **k: next(answers),
            prompt_optional_text=lambda *a, **k: '',
            prompt_confirm=lambda *a, **k: next(answers),
        ),
    )
    selection = flow.collect_selection()
    assert selection.mode == 'cache-key'
    assert selection.cache_key == 'site.name'
    assert selection.allow_prod is True
    preview = flow.build_preview_command(selection)
    assert '--cache-key=site.name' in preview
    assert '--allow-prod' in preview
    execute = flow.build_execute_arguments(selection, 'json')
    assert '--cache-key=site.name' in execute
    assert '--allow-prod' in execute

    # all mode without dry-run
    answers_all = iter(['dev', 'all', '', False])
    monkeypatch.setattr(
        flow,
        'prompt_service',
        SimpleNamespace(
            prompt_env=lambda default_env='dev': next(answers_all),
            prompt_choice=lambda *a, **k: next(answers_all),
            prompt_required_text=lambda *a, **k: '',
            prompt_optional_text=lambda *a, **k: next(answers_all),
            prompt_confirm=lambda *a, **k: next(answers_all),
        ),
    )
    selection_all = flow.collect_selection()
    assert selection_all.mode == 'all'
    assert '--all' in flow.build_preview_command(selection_all)
    assert '--dry-run' not in flow.build_preview_command(selection_all)
    assert '--all' in flow.build_execute_arguments(selection_all, 'text')

    named = cache_clear_flow.CacheClearWizardSelection(
        env='dev',
        mode='cache-name',
        cache_name='sys_config',
        cache_key='',
        dry_run=True,
        allow_prod=False,
    )
    named_args = flow.build_execute_arguments(named, 'text')
    assert '--cache-name=sys_config' in named_args
    assert '--dry-run' in named_args


def test_db_upgrade_allow_prod_flags(db_upgrade_flow: ModuleType) -> None:
    selection = db_upgrade_flow.DbUpgradeWizardSelection(
        env='prod',
        revision='head',
        dry_run=False,
        allow_prod=True,
    )
    flow = db_upgrade_flow.DbUpgradeWizardFlow()
    assert '--allow-prod' in flow.build_preview_command(selection)
    assert '--allow-prod' in flow.build_execute_arguments(selection, 'json')
    assert '--dry-run' not in flow.build_preview_command(selection)


def test_gen_export_retry_empty_tables_and_allow_prod(
    monkeypatch: MonkeyPatch,
    gen_export_flow: ModuleType,
) -> None:
    flow = gen_export_flow.GenExportWizardFlow()
    answers = iter(['prod', ',', 'sys_user', 'local', False, True])
    echoes: list[str] = []
    monkeypatch.setattr(gen_export_flow.typer, 'echo', lambda msg: echoes.append(msg))
    monkeypatch.setattr(
        flow,
        'prompt_service',
        SimpleNamespace(
            prompt_env=lambda default_env='dev': next(answers),
            prompt_required_text=lambda *a, **k: next(answers),
            prompt_choice=lambda *a, **k: next(answers),
            prompt_optional_text=lambda *a, **k: '',
            prompt_confirm=lambda *a, **k: next(answers),
        ),
    )
    selection = flow.collect_selection()
    assert selection.table_names == ['sys_user']
    assert selection.mode == 'local'
    assert selection.allow_prod is True
    assert echoes
    assert '--allow-prod' in flow.build_preview_command(selection)
    assert '--allow-prod' in flow.build_execute_arguments(selection, 'text')


def test_gen_import_retry_empty_tables_and_allow_prod(
    monkeypatch: MonkeyPatch,
    gen_import_flow: ModuleType,
) -> None:
    flow = gen_import_flow.GenImportWizardFlow()
    answers = iter(['prod', '  ,  ', 'sys_user', False, True])
    echoes: list[str] = []
    monkeypatch.setattr(gen_import_flow.typer, 'echo', lambda msg: echoes.append(msg))
    monkeypatch.setattr(
        flow,
        'prompt_service',
        SimpleNamespace(
            prompt_env=lambda default_env='dev': next(answers),
            prompt_required_text=lambda *a, **k: next(answers),
            prompt_confirm=lambda *a, **k: next(answers),
        ),
    )
    selection = flow.collect_selection()
    assert selection.table_names == ['sys_user']
    assert selection.allow_prod is True
    assert echoes
    assert '--allow-prod' in flow.build_preview_command(selection)
    assert '--allow-prod' in flow.build_execute_arguments(selection, 'json')


def test_prod_check_build_execute_arguments_empty(prod_check_flow: ModuleType) -> None:
    flow = prod_check_flow.ProdCheckWizardFlow()
    selection = prod_check_flow.ProdCheckWizardSelection(env='prod', include_config=False)
    assert flow.build_execute_arguments(selection, 'json') == []
