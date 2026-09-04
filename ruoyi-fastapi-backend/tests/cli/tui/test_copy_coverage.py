"""Raise coverage for cli.tui.copy mixins and rarely used builders."""

from __future__ import annotations

from types import SimpleNamespace


def test_action_copy_confirm_and_capability_fallbacks(tui_modules: SimpleNamespace) -> None:
    copy = tui_modules.cli_tui_copy.TUI_COPY
    assert copy.build_action_confirm_hint()
    assert copy.build_action_confirm_cancel_label()
    assert copy.build_action_unavailable_message()
    assert copy.build_action_empty_line()
    assert (
        copy.build_capability_hint_text([], '交互提示', fallback='缺省 {interaction_hint}')
        == '缺省 交互提示'
    )
    assert '动作键' in copy.build_capability_hint_text(['[X] 执行'], '交互提示', fallback='x')


def test_navigation_copy_empty_status_and_bindings(tui_modules: SimpleNamespace) -> None:
    copy = tui_modules.cli_tui_copy.TUI_COPY
    assert copy.render_status_label('   ', fallback='兜底') == '兜底'
    assert copy.render_status_label('custom-status') == 'CUSTOM-STATUS'
    assert copy.build_confirm_binding_label('cancel')
    assert copy.build_confirm_binding_label('submit')
    assert copy.build_app_binding_label('quit')
    assert copy.build_internal_binding_label('action_global')
    assert copy.build_tui_command_help()
    assert copy.build_missing_dependency_message()
    assert copy.build_missing_dependency_hint()


def test_workspace_copy_state_and_subtitle_helpers(tui_modules: SimpleNamespace) -> None:
    copy = tui_modules.cli_tui_copy.TUI_COPY
    assert copy.build_status_panel_empty_text()
    assert copy.build_signal_rail_empty_text()
    assert copy.build_more_detail_hint()
    assert copy.build_empty_state_suggestion()
    assert copy.build_loading_state_suggestion()
    assert copy.build_failure_state_suggestion()
    assert copy.build_dashboard_failure_suggestion()
    assert copy.build_dashboard_empty_suggestion()
    assert copy.build_empty_record_title('缓存')
    assert '不可用' in copy.build_unavailable_subtitle('任务', 'timeout')
    assert copy.build_empty_record_summary('详情说明') == '详情说明'
    assert '已加载 2 条' in copy.build_loaded_collection_subtitle(2, '条', '可筛选')
    assert '主摘要 | 补充' in copy.build_summary_with_message('主摘要', '补充')
    assert '前缀 3 项后缀' in copy.build_count_detail_subtitle('前缀', 3, '项', '后缀')
    assert '前缀 head后缀' in copy.build_value_detail_subtitle('前缀', 'head', '后缀')
    assert copy.build_refresh_page_suggestion('任务页', '稍后再试')
    assert copy.build_dashboard_page_suggestion('总览', '检查依赖')
    assert copy.build_unavailable_record_title('配置')
    assert copy.build_load_failure_section_title('配置')
    assert copy.build_cli_command_hint('job', 'sync')
    assert copy.build_command_hint_lines(scenario='场景', command='pgt job sync', guide='说明')
    panel = copy.build_browser_action_panel_lines(['动作A'], ['反馈B'])
    assert any('反馈B' in line for line in panel)
    assert '分区' in copy.build_detail_summary_text(3, 1, 1, 1)
