"""Raise coverage for cli.tui.actions factories, builders, registry, and execution edges."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch

BACKEND_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BACKEND_DIR))

actions_module = importlib.import_module('cli.tui.actions')
action_assembly_module = importlib.import_module('cli.tui.actions.assembly')
action_bootstrap_module = importlib.import_module('cli.tui.actions.bootstrap')
action_builders_module = importlib.import_module('cli.tui.actions.builders')
action_execution_module = importlib.import_module('cli.tui.actions.execution')
adapters_module = importlib.import_module('cli.tui.adapters')


def _job_record(*, key: str = 'job:7', status: str = 'ok') -> object:
    return adapters_module.BrowserRecordSnapshot(
        key=key,
        title='任务七',
        status=status,
        summary='摘要',
        metadata_lines=[],
        detail_sections=[],
    )


def _gen_record() -> object:
    return adapters_module.BrowserRecordSnapshot(
        key='gen:9',
        title='sys_demo',
        status='ok',
        summary='模块 demo',
        metadata_lines=[],
        detail_sections=[],
    )


def test_parse_record_suffix_returns_empty_for_mismatched_prefix() -> None:
    record = _job_record(key='cache:sys_config')
    assert action_builders_module.TuiActionSpecFactory.parse_record_suffix(record, 'job') == ''


def test_job_factory_null_record_edges() -> None:
    jobs = action_bootstrap_module._JOB_ACTION_TEMPLATE_FACTORY
    assert jobs.build_run_once_command(None, 'dev') is None
    assert jobs.build_run_once_summary(None, 'dev') == []
    assert jobs.build_toggle_command(None, 'dev') is None
    assert jobs.build_toggle_summary(None, 'dev') == []
    assert jobs.build_toggle_action_id(None, 'dev') == 'job-pause'
    assert jobs.build_toggle_label(None, 'dev') == '暂停任务'
    assert jobs.build_run_once_command(_job_record(key='job:abc'), 'dev') is None
    assert jobs.build_toggle_command(_job_record(key='job:abc'), 'dev') is None


def test_gen_factory_null_record_and_empty_title_edges() -> None:
    gen = action_bootstrap_module._GEN_ACTION_TEMPLATE_FACTORY
    assert gen.build_export_wizard_command(None, 'dev') is None
    assert gen.build_import_wizard_command(None, 'dev') is None
    assert gen.build_export_dry_run_command(None, 'dev') is None
    assert gen.build_sync_db_command(None, 'dev') is None
    assert gen.build_export_wizard_summary(None, 'dev') == []
    assert gen.build_import_wizard_summary(None, 'dev') == []
    assert gen.build_export_dry_run_summary(None, 'dev') == []
    assert gen.build_sync_db_summary(None, 'dev') == []

    blank = adapters_module.BrowserRecordSnapshot(
        key='gen:1',
        title='  ',
        status='ok',
        summary='x',
        metadata_lines=[],
        detail_sections=[],
    )
    assert gen.build_export_wizard_command(blank, 'dev') is None


def test_cache_factory_clear_command_without_record() -> None:
    cache = action_bootstrap_module._CACHE_ACTION_TEMPLATE_FACTORY
    args = cache.build_clear_command(None, 'prod')
    assert '--default-env=prod' in args
    assert '--default-cache-name=' in args
    assert cache.build_clear_summary(None, 'prod')


def test_static_factory_command_builders_cover_all_commands() -> None:
    static = action_bootstrap_module._STATIC_ACTION_TEMPLATE_FACTORY
    assert static.build_job_sync_command(None, 'dev') == ('job', 'sync')
    assert static.build_config_sync_command(None, 'dev') == ('config', 'sync-cache')
    assert static.build_cache_warmup_command(None, 'dev') == ('cache', 'warmup')
    assert static.build_db_upgrade_wizard_command(None, 'staging')[3] == '--default-env=staging'
    assert static.build_db_init_dry_run_command(None, 'dev') == ('db', 'init', '--dry-run')
    assert static.build_app_run_wizard_command(None, 'dev') == ('wizard', 'app-run')
    assert static.build_completion_install_command(None, 'dev') == ('completion', 'install', '--activate')
    assert static.build_prod_check_wizard_command(None, 'prod')[3] == '--default-env=prod'
    assert static.build_crypto_rotate_dry_run_command(None, 'dev') == ('crypto', 'rotate', '--dry-run')
    assert static.build_app_run_command(None, 'dev') == ('app', 'run', '--env=dev')
    assert static.build_crypto_keygen_command(None, 'dev') == ('crypto', 'keygen', '--env=dev', '--output=text')
    assert static.build_ops_ping_db_command(None, 'dev') == ('ops', 'ping-db')
    assert static.build_ops_ping_redis_command(None, 'dev') == ('ops', 'ping-redis')


def test_template_support_null_helpers() -> None:
    support = action_bootstrap_module._ACTION_TEMPLATE_SUPPORT
    assert support.extract_job_id(None) is None
    assert support.require_record_title(None) is None
    assert support.require_record_title(
        adapters_module.BrowserRecordSnapshot(
            key='x',
            title='',
            status='ok',
            summary='',
            metadata_lines=[],
            detail_sections=[],
        )
    ) is None


def test_action_template_build_returns_none_when_command_builder_fails() -> None:
    template = action_builders_module.TuiActionTemplate(
        action_id='noop',
        label='noop',
        command_builder=lambda record, env: None,
        summary_builder=lambda record, env: [],
    )
    assert (
        template.build(
            record=_gen_record(),
            env='dev',
            spec_factory=action_bootstrap_module._ACTION_SPEC_FACTORY,
        )
        is None
    )


def test_registry_unknown_view_and_unknown_slot_return_none() -> None:
    assert (
        actions_module.TUI_ACTION_REGISTRY.resolve_browser_action(
            view_key='unknown-view',
            slot='primary',
            record=_job_record(),
            env='dev',
        )
        is None
    )
    assert (
        actions_module.TUI_ACTION_REGISTRY.resolve_browser_action(
            view_key='jobs',
            slot='utility',
            record=_job_record(),
            env='dev',
        )
        is None
    )
    assert (
        actions_module.TUI_ACTION_REGISTRY.resolve_detail_action(
            view_key='missing',
            slot='primary',
            env='dev',
        )
        is None
    )


def test_presentation_skips_unresolved_browser_action_slots() -> None:
    lines = actions_module.TUI_ACTION_PRESENTATION_SERVICE.build_browser_action_lines(
        view_key='jobs',
        record=_job_record(key='not-a-job'),
        env='dev',
    )
    assert lines
    assert any('同步' in line or '动作' in line or '暂无' in line for line in lines)


def test_execution_external_failure_and_extra_payload_fields(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        action_execution_module.NESTED_CLI_SUPPORT,
        'run_live',
        lambda *args: SimpleNamespace(returncode=7),
    )
    external_spec = actions_module.TuiActionSpec(
        action_id='wizard-x',
        label='外部动作',
        command_args=('wizard', 'x'),
        preview_title='外部动作',
        preview_lines=['a'],
        execution_mode='external',
    )
    external_result = actions_module.TUI_ACTION_EXECUTION_SERVICE.execute_external(external_spec)
    assert external_result.ok is False
    assert '退出码 7' in external_result.message

    nested_spec = actions_module.TuiActionSpec(
        action_id='ops-ping-db',
        label='数据库探活',
        command_args=('ops', 'ping-db'),
        preview_title='数据库探活',
        preview_lines=['a'],
        append_yes=False,
    )
    result = actions_module.TuiActionResult(
        spec=nested_spec,
        payload={
            'ok': True,
            'message': 'ok',
            'count': 3,
            'operationLabel': '探活别名',
        },
    )
    lines = actions_module.TUI_ACTION_EXECUTION_SERVICE.build_result_lines(result)
    assert any('影响数量: 3' in line for line in lines)
    assert any('操作标签: 探活别名' in line for line in lines)


def test_registry_builder_reassembles_independent_instance() -> None:
    registry = action_assembly_module.TuiActionRegistryBuilder(
        jobs=action_bootstrap_module._JOB_ACTION_TEMPLATE_FACTORY,
        cache=action_bootstrap_module._CACHE_ACTION_TEMPLATE_FACTORY,
        gen=action_bootstrap_module._GEN_ACTION_TEMPLATE_FACTORY,
        static=action_bootstrap_module._STATIC_ACTION_TEMPLATE_FACTORY,
        spec_factory=action_bootstrap_module._ACTION_SPEC_FACTORY,
    ).build()
    action = registry.resolve_browser_action(
        view_key='configs',
        slot='global',
        record=None,
        env='dev',
    )
    assert action is not None
    assert action.command_args == ('config', 'sync-cache')
