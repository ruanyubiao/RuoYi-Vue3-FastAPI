"""Raise coverage for cli.tui.widgets rendering helpers and view widgets."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static


def _workspace():
    return __import__('cli.tui.widgets.workspace', fromlist=['*'])


def _status_panel():
    return __import__('cli.tui.widgets.status_panel', fromlist=['*'])


def test_workspace_rendering_status_and_structured_lines(tui_modules: SimpleNamespace) -> None:
    del tui_modules
    support = _workspace().WORKSPACE_RENDERING

    assert support.resolve_status_class('FAIL') == 'is-fail'
    assert support.resolve_status_class('warning') == 'is-warn'
    assert support.resolve_status_class('mystery') == 'is-info'
    assert support.strip_line_markup('## Heading') == 'Heading'
    assert support.strip_line_markup('> note') == 'note'
    assert support.strip_line_markup('plain') == 'plain'
    assert support.build_preview_line(['', '  ', '> first'], 'fallback') == 'first'
    assert support.build_preview_line(['', ''], 'fallback') == 'fallback'

    rendered = support.render_structured_lines(
        ['', '## Title', '> child', 'body', '', ''],
        'empty',
    )
    assert '【Title】' in rendered
    assert '│ child' in rendered
    assert '• body' in rendered
    assert support.render_structured_lines([], 'empty') == '- empty'


def test_workspace_sidebar_falls_back_when_active_view_missing(tui_modules: SimpleNamespace) -> None:
    del tui_modules
    workspace = _workspace()
    items = [
        workspace.NavigationItem('jobs', '任务', '1', 'desc'),
        workspace.NavigationItem('cache', '缓存', '2', 'desc'),
    ]
    sidebar = workspace.WorkspaceSidebar('dev', items, active_view='missing')
    assert sidebar._resolve_initial_index() == 0


def test_workspace_hero_title_and_pulse(tui_modules: SimpleNamespace) -> None:
    del tui_modules
    workspace = _workspace()
    hero = workspace.WorkspaceHero(
        title='标题',
        subtitle='副标题',
        env='dev',
        active_view='jobs',
        summary='摘要',
        refreshed_at='2026-01-01 00:00:00',
    )
    title = workspace.WorkspaceHero._build_title_text('AB')
    assert title.plain == 'AB'
    text = hero._build_render_text()
    assert '标题' in text.plain
    hero._pulse_border()


def test_workspace_header_scanline_and_short_render(
    monkeypatch: pytest.MonkeyPatch,
    tui_modules: SimpleNamespace,
) -> None:
    del tui_modules
    workspace = _workspace()
    header = workspace.WorkspaceHeader('dev', 'jobs')
    scan = workspace.WorkspaceHeader.build_scanline_text(0.5, 16)
    assert len(scan.plain) == 16
    centered = header.build_centered_title_line('中心标题')
    assert '中心标题' in centered.plain

    monkeypatch.setattr(
        workspace.TUI_COPY,
        'build_workspace_header_lines',
        lambda **kwargs: ['only-one-line'],
    )
    rendered = header.render()
    assert 'only-one-line' in rendered.plain


def test_record_detail_and_summary_render_paths(tui_modules: SimpleNamespace) -> None:
    workspace = _workspace()
    adapters = tui_modules.cli_tui_adapters
    record = adapters.BrowserRecordSnapshot(
        key='job:1',
        title='任务',
        status='warn',
        summary='暂停',
        metadata_lines=['## Meta', '> field', 'value'],
        detail_sections=[],
    )
    shared = [
        adapters.DetailSectionSnapshot(title='共享', status='ok', lines=['## Block', 'line']),
    ]
    detail = workspace.RecordDetailView(record, shared, query='任务')
    detail_text = str(detail.render())
    assert '任务' in detail_text
    assert '共享' in detail_text

    empty_record = adapters.BrowserRecordSnapshot(
        key='job:2',
        title='空记录',
        status='info',
        summary='无分区',
        metadata_lines=[],
        detail_sections=[],
    )
    detail.show_record(empty_record, [], query='')
    empty_text = str(detail.render())
    assert '空记录' in empty_text

    section = adapters.DetailSectionSnapshot(title='分区A', status='fail', lines=['x'])
    summary = workspace.RecordSummaryView(record)
    summary.show_record(record, selected_section=section, action_lines=['动作反馈行'], query='暂停')
    summary_text = str(summary.render())
    assert '分区A' in summary_text
    assert '动作反馈行' in summary_text


@pytest.mark.asyncio
async def test_section_navigator_show_sections_and_watch_index(tui_modules: SimpleNamespace) -> None:
    workspace = _workspace()
    adapters = tui_modules.cli_tui_adapters
    sections = [
        adapters.DetailSectionSnapshot(title='A', status='ok', lines=['a']),
        adapters.DetailSectionSnapshot(title='B', status='warn', lines=['b']),
    ]
    records = [
        adapters.BrowserRecordSnapshot(
            key='job:1',
            title='R1',
            status='ok',
            summary='s',
            metadata_lines=[],
            detail_sections=[],
        )
    ]

    class Host(App):
        def compose(self) -> ComposeResult:
            yield workspace.SectionNavigator(sections, initial_index=0)
            yield workspace.RecordNavigator(records)
            yield workspace.SectionDetailView(sections[0])
            yield Static('host')

    app = Host()
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        navigator = app.query_one(workspace.SectionNavigator)
        await navigator.show_sections(sections, initial_index=1, query='A')
        assert navigator.index == 1
        await navigator.show_sections([], initial_index=0)
        assert navigator.index is None

        record_nav = app.query_one(workspace.RecordNavigator)
        changed = workspace.RecordNavigator.Changed(record_nav, 0, record_nav._nodes[0])
        assert changed.control is record_nav
        section_changed = workspace.SectionNavigator.Changed(
            navigator,
            0,
            navigator._nodes[0] if navigator._nodes else sections[0],  # type: ignore[arg-type]
        )
        assert section_changed.control is navigator

        detail = app.query_one(workspace.SectionDetailView)
        detail.show_section(sections[1], query='B')
        assert detail.section.title == 'B'

        navigator.watch_index(0, None)
        record_nav.watch_index(0, None)
        # Re-populate and exercise Changed.control after a valid index change
        await navigator.show_sections(sections, initial_index=0)
        if navigator._nodes:
            navigator.watch_index(None, 0)


def test_status_panel_rendering_empty_and_pulse(tui_modules: SimpleNamespace) -> None:
    del tui_modules
    status_mod = _status_panel()
    support = status_mod.STATUS_PANEL_RENDERING
    assert support.resolve_status_class('down') == 'is-fail'
    assert support.resolve_status_class('degraded') == 'is-warn'
    empty = support.render_structured_body('\n\n')
    assert empty.startswith('-')
    body = support.render_structured_body('\n## T\n> note\nplain\n\n')
    assert '【T】' in body
    assert '│ note' in body
    rail_text = support.build_signal_rail_text(['alpha', '', 'beta'], 1)
    assert 'alpha' in rail_text

    rail = status_mod.SignalRail(['signal-a'])
    rail._advance_pulse()
    assert rail._pulse_index == 1
