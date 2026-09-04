"""Close small leftovers in cli.tui app/commands/diagnostics/widgets."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pytest import MonkeyPatch
from textual.css.query import NoMatches


def test_commands_reraises_non_textual_module_not_found(
    tui_base_modules: SimpleNamespace,
) -> None:
    commands = tui_base_modules.cli_tui_commands
    registration = commands.TuiCommandRegistration(
        context_factory=commands.TUI_COMMAND_REGISTRATION.context_factory,
        execution_service=commands.TUI_COMMAND_REGISTRATION.execution_service,
        dependency_result_factory=commands.TUI_COMMAND_REGISTRATION.dependency_result_factory,
        module_loader=SimpleNamespace(
            load=lambda: (_ for _ in ()).throw(
                ModuleNotFoundError("No module named 'not_a_tui_dep'", name='not_a_tui_dep')
            ),
            is_missing_dependency_error=commands.TuiAppModuleLoader().is_missing_dependency_error,
        ),
    )
    with pytest.raises(ModuleNotFoundError, match='not_a_tui_dep'):
        registration.handle_tui_command('dev')


def test_commands_missing_dependency_return_and_successful_run(
    tui_base_modules: SimpleNamespace,
) -> None:
    commands = tui_base_modules.cli_tui_commands
    completed: list[object] = []
    run_calls: list[str] = []

    missing_loader = SimpleNamespace(
        load=lambda: (_ for _ in ()).throw(
            ModuleNotFoundError("No module named 'textual'", name='textual')
        ),
        is_missing_dependency_error=commands.TuiAppModuleLoader().is_missing_dependency_error,
    )
    missing_registration = commands.TuiCommandRegistration(
        context_factory=commands.TUI_COMMAND_REGISTRATION.context_factory,
        execution_service=SimpleNamespace(
            complete_result=lambda ctx, result: completed.append((ctx, result)),
        ),
        dependency_result_factory=commands.TUI_COMMAND_REGISTRATION.dependency_result_factory,
        module_loader=missing_loader,
    )
    missing_registration.handle_tui_command('dev')
    assert completed

    ok_registration = commands.TuiCommandRegistration(
        context_factory=commands.TUI_COMMAND_REGISTRATION.context_factory,
        execution_service=commands.TUI_COMMAND_REGISTRATION.execution_service,
        dependency_result_factory=commands.TUI_COMMAND_REGISTRATION.dependency_result_factory,
        module_loader=SimpleNamespace(
            load=lambda: SimpleNamespace(
                TUI_APP_RUNNER=SimpleNamespace(run=lambda env: run_calls.append(env)),
            ),
            is_missing_dependency_error=commands.TuiAppModuleLoader().is_missing_dependency_error,
        ),
    )
    ok_registration.handle_tui_command('prod')
    assert run_calls == ['prod']


def test_diagnostics_subtitle_branch_leftovers() -> None:
    diagnostics = __import__('cli.tui.diagnostics', fromlist=['TUI_DIAGNOSTIC_SERVICE'])
    service = diagnostics.TUI_DIAGNOSTIC_SERVICE

    assert '应用基础信息读取异常' in service.build_app_diagnostic_subtitle(
        None, None, {'ok': True}, {'ok': True}, {'ok': True}
    )
    assert '启动前检查异常' in service.build_app_diagnostic_subtitle(
        {'ok': True}, {'ok': True}, {'ok': False}, {'ok': True}, {'ok': True}
    )
    assert '补全诊断读取异常' in service.build_app_diagnostic_subtitle(
        {'ok': True}, {'ok': True}, {'ok': True}, {'ok': True}, {'ok': False}
    )
    assert '路由摘要读取异常' in service.build_app_diagnostic_subtitle(
        {'ok': True}, {'ok': True}, {'ok': True}, {'ok': False}, {'ok': True}
    )
    assert '迁移分叉风险' in service.build_database_diagnostic_subtitle(
        {'ok': True, 'currentRevision': 'r1'},
        {'ok': True},
        {'ok': True, 'items': [{'revision': 'a'}, {'revision': 'b'}]},
    )
    assert '数据库异常' in service.build_database_diagnostic_subtitle(
        {'ok': False, 'currentRevision': '-'},
        {'ok': False},
        {'ok': True, 'items': [{'revision': 'a'}]},
    )
    assert '运维依赖存在异常' in service.build_ops_diagnostic_subtitle(
        {'ok': True}, {'ok': False}, {'ok': True}
    )
    assert '服务器信息采集异常' in service.build_ops_diagnostic_subtitle(
        {'ok': True}, {'ok': True}, {'ok': False}
    )
    assert '运行校验失败' in service.build_crypto_diagnostic_subtitle({'ok': False}, {'ok': True})
    assert '公钥导出结果异常' in service.build_crypto_diagnostic_subtitle(
        {'ok': True}, {'ok': False}
    )


def test_app_view_registry_state_store_and_action_leftovers(
    monkeypatch: MonkeyPatch,
    tui_modules: SimpleNamespace,
) -> None:
    app_mod = tui_modules.cli_tui_app
    registry = app_mod.TUI_VIEW_REGISTRY

    assert registry.get_navigation_index('jobs') >= 0
    assert registry.get_navigation_index('nope') == 0
    previous = registry.get_relative_view_key('dashboard', -1)
    next_view = registry.get_relative_view_key('dashboard', 1)
    assert previous and next_view

    store = app_mod.TuiViewStateStore.create_default()
    store.remember_action_feedback('jobs', ['done'])
    assert store.get_action_feedback_lines('jobs') == ['done']
    store.remember_browser_query('jobs', 'alpha')
    assert store.get_browser_query('jobs') == 'alpha'
    store.remember_browser_query('jobs', '  ')
    assert store.get_browser_query('jobs') == ''

    app = app_mod.RuoyiTuiApp('dev')
    opened: list[str] = []
    monkeypatch.setattr(app, 'open_view', lambda view: opened.append(view))
    monkeypatch.setattr(app, 'show_view', lambda view: opened.append(f'refresh:{view}'))

    app.remember_action_feedback('cache', ['ok'])
    assert app.get_action_feedback_lines('cache') == ['ok']

    app.action_show_previous_view()
    app.action_show_next_view()
    app.action_refresh_current_view()
    app.action_show_dashboard()
    assert 'dashboard' in opened
    assert any(item.startswith('refresh:') for item in opened)

    class _Screen:
        def query_one(self, _widget_type: object) -> None:
            raise NoMatches('missing sidebar')

    monkeypatch.setattr(type(app), 'screen', property(lambda self: _Screen()), raising=False)
    app.action_focus_sidebar()


def test_status_panel_and_workspace_leading_empty_are_pruned(
    tui_modules: SimpleNamespace,
) -> None:
    del tui_modules
    status = __import__('cli.tui.widgets.status_panel', fromlist=['*'])
    workspace = __import__('cli.tui.widgets.workspace', fromlist=['*'])

    # trailing empty is reachable; leading-empty prune stays defensive
    body = status.STATUS_PANEL_RENDERING.render_structured_body('hello\n\n')
    assert body.startswith('• hello')
    rendered = workspace.WORKSPACE_RENDERING.render_structured_lines(
        ['keep', '## Title', '> child'],
        'empty',
    )
    assert '【Title】' in rendered
    assert '│ child' in rendered
