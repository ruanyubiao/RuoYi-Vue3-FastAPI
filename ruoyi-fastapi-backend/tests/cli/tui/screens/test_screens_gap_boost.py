"""Close leftover coverage gaps in TUI dashboard/detail/search screens."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static


def test_dashboard_sidebar_handlers_skip_and_open(
    monkeypatch: pytest.MonkeyPatch,
    tui_modules: SimpleNamespace,
) -> None:
    dashboard = tui_modules.cli_tui_dashboard
    opened: list[str] = []
    screen = dashboard.DashboardScreen(
        snapshot=tui_modules.cli_tui_app.DashboardSnapshot(env='dev', metrics=[], panels=[]),
        env='dev',
        active_view='dashboard',
        navigation_items=tui_modules.cli_tui_app.NAVIGATION_ITEMS,
        refreshed_at='now',
    )
    fake_app = SimpleNamespace(open_view=lambda key: opened.append(key))
    monkeypatch.setattr(dashboard.DashboardScreen, 'app', property(lambda self: fake_app))

    screen._open_sidebar_item(SimpleNamespace(item=SimpleNamespace(item=None)))
    assert opened == []

    nav_item = tui_modules.cli_tui_app.NAVIGATION_ITEMS[0]
    screen.active_view = nav_item.view_key
    screen._open_sidebar_item(SimpleNamespace(item=SimpleNamespace(item=nav_item)))
    assert opened == []

    other = next(item for item in tui_modules.cli_tui_app.NAVIGATION_ITEMS if item.view_key != screen.active_view)
    screen.on_sidebar_selected(SimpleNamespace(item=SimpleNamespace(item=other)))
    assert opened == [other.view_key]


def test_detail_sidebar_and_section_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    tui_modules: SimpleNamespace,
) -> None:
    detail = tui_modules.cli_tui_detail
    opened: list[str] = []
    empty_snapshot = tui_modules.cli_tui_app.DetailPageSnapshot(
        title='empty',
        subtitle='s',
        sections=[],
        search=tui_modules.cli_tui_search.PageSearchContext(placeholder='p', query='', suggestions=[]),
    )
    screen = detail.DetailScreen(
        empty_snapshot,
        env='dev',
        active_view='app',
        navigation_items=tui_modules.cli_tui_app.NAVIGATION_ITEMS,
        refreshed_at='now',
    )
    fake_app = SimpleNamespace(open_view=lambda key: opened.append(key))
    monkeypatch.setattr(detail.DetailScreen, 'app', property(lambda self: fake_app))

    shown: list[object] = []

    class FakeDetailView:
        def show_section(self, section: object, query: str = '') -> None:
            shown.append((section, query))

    screen.query_one = lambda widget_type: FakeDetailView()  # type: ignore[method-assign]
    screen._update_selected_section(0)
    assert shown
    assert shown[0][0].title == tui_modules.cli_tui_copy.TUI_COPY.build_detail_empty_section_copy('title')

    filled = tui_modules.cli_tui_app.DetailPageSnapshot(
        title='jobs',
        subtitle='s',
        sections=[
            tui_modules.cli_tui_adapters.DetailSectionSnapshot(title='A', status='ok', lines=['a']),
            tui_modules.cli_tui_adapters.DetailSectionSnapshot(title='B', status='ok', lines=['b']),
        ],
    )
    screen2 = detail.DetailScreen(
        filled,
        env='dev',
        active_view='jobs',
        navigation_items=tui_modules.cli_tui_app.NAVIGATION_ITEMS,
        refreshed_at='now',
    )
    shown2: list[object] = []

    class FakeDetailView2:
        def show_section(self, section: object, query: str = '') -> None:
            shown2.append(section)

    screen2.query_one = lambda widget_type: FakeDetailView2()  # type: ignore[method-assign]
    screen2._update_selected_section(99)
    assert shown2 == []
    screen2._update_selected_section(1)
    assert shown2[-1].title == 'B'

    assert screen2._get_section_or_fallback(99).title == tui_modules.cli_tui_copy.TUI_COPY.build_detail_empty_section_copy(
        'title'
    )

    screen2._open_sidebar_item(SimpleNamespace(item=SimpleNamespace(item=object())))
    assert opened == []
    other = next(item for item in tui_modules.cli_tui_app.NAVIGATION_ITEMS if item.view_key != 'jobs')
    screen2.on_sidebar_selected(SimpleNamespace(item=SimpleNamespace(item=other)))
    assert opened[-1] == other.view_key

    dialogs: list[object] = []
    monkeypatch.setattr(
        detail.TUI_SCREEN_INTERACTION_SERVICE,
        'open_search_dialog',
        lambda screen_obj, search, callback: dialogs.append((search, callback)),
    )
    monkeypatch.setattr(
        detail.TUI_SCREEN_INTERACTION_SERVICE,
        'confirm_and_schedule_action',
        lambda screen_obj, action, task, execute: dialogs.append(('confirm', action)),
    )
    screen2._open_search()
    assert dialogs
    action = screen2._resolve_action('global')
    screen2._open_action_confirm('global')
    assert any(item[0] == 'confirm' for item in dialogs)
    del action


def test_search_service_unknown_view_and_provider_exception(tui_modules: SimpleNamespace) -> None:
    search = tui_modules.cli_tui_search
    service = search.TuiSearchService(
        search.TuiSearchSuggestionProviderRegistry(
            providers={
                'jobs': search.SearchSuggestionProviderSpec(
                    '按任务名搜索',
                    lambda incomplete: (_ for _ in ()).throw(RuntimeError('boom')),
                )
            }
        )
    )
    assert service.resolve_search_context('unknown-view', 'q') is None
    assert (
        service.resolve_search_suggestions(
            search.SearchSuggestionProviderSpec(
                'x',
                lambda incomplete: (_ for _ in ()).throw(RuntimeError('x')),
            ),
            'query',
        )
        == []
    )


@pytest.mark.asyncio
async def test_search_input_screen_empty_suggestions_compose(tui_modules: SimpleNamespace) -> None:
    del tui_modules
    search_mod = __import__('cli.tui.screens.search', fromlist=['SearchInputScreen'])

    class Host(App[None]):
        def compose(self) -> ComposeResult:
            yield Static('host')

    app = Host()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.push_screen(search_mod.SearchInputScreen('搜索', '占位', '', []))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, search_mod.SearchInputScreen)
        suggestions = screen.query_one('#search-suggestions', Static)
        assert '暂无建议' in suggestions.content
