"""Raise coverage for BrowserScreen branches not hit by existing screen tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pytest import MonkeyPatch


def _make_screen(tui_modules: SimpleNamespace, snapshot: object, *, active_view: str = 'jobs'):
    return tui_modules.cli_tui_browser.BrowserScreen(
        snapshot,
        env='dev',
        active_view=active_view,
        navigation_items=tui_modules.cli_tui_app.NAVIGATION_ITEMS,
        refreshed_at='2026-04-30 10:00:00',
    )


def test_browser_filter_shortcut_noop_and_apply(
    monkeypatch: MonkeyPatch,
    tui_modules: SimpleNamespace,
) -> None:
    snapshot = tui_modules.cli_tui_adapters.BrowserPageSnapshot(
        title='任务',
        subtitle='subtitle',
        records=[],
        shared_sections=[],
        filters=list(tui_modules.cli_tui_search.JOB_FILTER_OPTIONS),
        active_filter_key='all',
    )
    screen = _make_screen(tui_modules, snapshot)
    refresh: list[str] = []
    monkeypatch.setattr(
        tui_modules.cli_tui_browser.BrowserScreen,
        'app',
        property(
            lambda self: SimpleNamespace(
                remember_browser_filter=lambda *a, **k: None,
                action_refresh_current_view=lambda: refresh.append('r'),
            )
        ),
    )

    empty = _make_screen(
        tui_modules,
        tui_modules.cli_tui_adapters.BrowserPageSnapshot(
            title='缓存',
            subtitle='s',
            records=[],
            shared_sections=[],
        ),
        active_view='cache',
    )
    empty.action_apply_filter_1()
    # unknown shortcut
    screen._apply_filter_shortcut('9')
    # same key as active ('1' -> all)
    screen._apply_filter_shortcut('1')
    assert refresh == []

    screen.action_apply_filter_3()
    assert refresh == ['r']
    refresh.clear()
    screen.snapshot = tui_modules.cli_tui_adapters.BrowserPageSnapshot(
        title='任务',
        subtitle='subtitle',
        records=[],
        shared_sections=[],
        filters=list(tui_modules.cli_tui_search.JOB_FILTER_OPTIONS),
        active_filter_key='paused',
    )
    screen.action_apply_filter_4()
    assert refresh == ['r']


def test_browser_get_sections_and_fallback_paths(tui_modules: SimpleNamespace) -> None:
    adapters = tui_modules.cli_tui_adapters
    loaded = [
        adapters.DetailSectionSnapshot(title='预置', status='ok', lines=['a']),
    ]
    cached_sections = (
        adapters.DetailSectionSnapshot(title='缓存分区', status='warn', lines=['c']),
    )

    def _loader() -> list[object]:
        return [adapters.DetailSectionSnapshot(title='懒加载', status='ok', lines=['l'])]

    def _boom() -> list[object]:
        raise RuntimeError('load fail')

    cached_record = adapters.BrowserRecordSnapshot(
        key='job:2',
        title='仅缓存',
        status='ok',
        summary='s',
        metadata_lines=[],
        detail_sections=[],
    )
    object.__setattr__(cached_record, '_cached_detail_sections', cached_sections)

    records = [
        adapters.BrowserRecordSnapshot(
            key='job:1',
            title='有预置',
            status='ok',
            summary='s',
            metadata_lines=[],
            detail_sections=loaded,
        ),
        cached_record,
        adapters.BrowserRecordSnapshot(
            key='job:3',
            title='懒加载中',
            status='ok',
            summary='s',
            metadata_lines=[],
            detail_sections=[],
            detail_loader=_loader,
        ),
        adapters.BrowserRecordSnapshot(
            key='job:4',
            title='无详情',
            status='ok',
            summary='s',
            metadata_lines=[],
            detail_sections=[],
        ),
        adapters.BrowserRecordSnapshot(
            key='job:5',
            title='eager失败',
            status='ok',
            summary='s',
            metadata_lines=[],
            detail_sections=[],
            detail_loader=_boom,
        ),
    ]
    snapshot = adapters.BrowserPageSnapshot(
        title='任务',
        subtitle='s',
        records=records,
        shared_sections=[adapters.DetailSectionSnapshot(title='共享', status='ok', lines=['x'])],
    )
    screen = _make_screen(tui_modules, snapshot)

    assert screen._get_record_or_fallback(99).title
    assert screen._build_loading_section().status
    assert any('预置' in s.title for s in screen._get_sections_for_record(0))
    assert any('缓存分区' in s.title for s in screen._get_sections_for_record(1))
    lazy = screen._get_sections_for_record(2)
    assert any('加载' in s.title for s in lazy)
    assert screen._get_sections_for_record(3)[-1].title == '共享'
    eager_ok = screen._get_sections_for_record(2, eager=True)
    assert any('懒加载' in s.title for s in eager_ok)
    eager_fail = screen._get_sections_for_record(4, eager=True)
    assert eager_fail[0].status == 'fail'
    assert screen._get_section_or_fallback(0, 99).title


def test_browser_open_search_and_action_confirm(
    monkeypatch: MonkeyPatch,
    tui_modules: SimpleNamespace,
) -> None:
    snapshot = tui_modules.cli_tui_adapters.BrowserPageSnapshot(
        title='任务',
        subtitle='s',
        records=[
            tui_modules.cli_tui_adapters.BrowserRecordSnapshot(
                key='job:1',
                title='Job',
                status='ok',
                summary='正常 · Cron x',
                metadata_lines=[],
                detail_sections=[],
            )
        ],
        shared_sections=[],
        search=tui_modules.cli_tui_search.PageSearchContext(
            placeholder='搜索',
            query='',
            suggestions=['a'],
        ),
        filters=list(tui_modules.cli_tui_search.JOB_FILTER_OPTIONS),
        active_filter_key='all',
    )
    screen = _make_screen(tui_modules, snapshot)
    calls: list[str] = []
    monkeypatch.setattr(
        tui_modules.cli_tui_browser.TUI_SCREEN_INTERACTION_SERVICE,
        'open_search_dialog',
        lambda *args, **kwargs: calls.append('search'),
    )
    monkeypatch.setattr(
        tui_modules.cli_tui_browser.TUI_SCREEN_INTERACTION_SERVICE,
        'confirm_and_schedule_action',
        lambda *args, **kwargs: calls.append('confirm') or None,
    )
    screen._open_search()
    screen._open_action_confirm('primary')
    assert calls == ['search', 'confirm']
    assert screen._build_filter_bar_text()


@pytest.mark.asyncio
async def test_browser_update_record_section_and_schedule(tui_modules: SimpleNamespace) -> None:
    adapters = tui_modules.cli_tui_adapters
    section_a = adapters.DetailSectionSnapshot(title='A', status='ok', lines=['a'])
    section_b = adapters.DetailSectionSnapshot(title='B', status='warn', lines=['b'])
    records = [
        adapters.BrowserRecordSnapshot(
            key='job:1',
            title='R1',
            status='ok',
            summary='s1',
            metadata_lines=[],
            detail_sections=[section_a, section_b],
        ),
        adapters.BrowserRecordSnapshot(
            key='job:2',
            title='R2',
            status='ok',
            summary='s2',
            metadata_lines=[],
            detail_sections=[section_a],
            detail_loader=lambda: [section_b],
        ),
    ]
    snapshot = adapters.BrowserPageSnapshot(
        title='任务',
        subtitle='s',
        records=records,
        shared_sections=[],
        filters=list(tui_modules.cli_tui_search.JOB_FILTER_OPTIONS),
        active_filter_key='all',
    )

    tui_app = tui_modules.cli_tui_app.RuoyiTuiApp('dev')
    tui_app.action_show_dashboard = lambda: None  # type: ignore[method-assign]
    tui_app.current_view = 'jobs'
    real_screen = tui_app.screen_factory.build(
        snapshot=snapshot,
        env=tui_app.env,
        active_view=tui_app.current_view,
        navigation_items=tui_modules.cli_tui_app.NAVIGATION_ITEMS,
        action_feedback_lines=[],
    )
    async with tui_app.run_test(size=(140, 50)) as pilot:
        tui_app.screen_navigator.show(real_screen)
        await pilot.pause()
        await pilot.pause()
        screen = tui_app.screen

        # section switch while still on record 0 (two sections)
        screen._update_selected_section(1)
        assert screen.selected_section_index == 1
        screen._update_selected_section(1)  # same
        screen._update_selected_section(99)  # oob
        screen._is_syncing_sections = True
        screen._update_selected_section(0)
        screen._is_syncing_sections = False

        await screen._update_selected_record(1)
        await pilot.pause()
        assert screen.selected_record_index == 1
        await screen._update_selected_record(1)
        await screen._update_selected_record(99)

        # empty sections branch
        empty_snapshot = adapters.BrowserPageSnapshot(
            title='任务',
            subtitle='s',
            records=[
                adapters.BrowserRecordSnapshot(
                    key='job:9',
                    title='空',
                    status='ok',
                    summary='s',
                    metadata_lines=[],
                    detail_sections=[],
                )
            ],
            shared_sections=[],
        )
        screen.snapshot = empty_snapshot
        screen.selected_record_index = 0
        screen.selected_section_index = 0
        screen._update_selected_section(0)

        # schedule loaders
        screen.snapshot = snapshot
        screen.selected_record_index = 1
        object.__setattr__(records[1], '_cached_detail_sections', None)
        screen._schedule_record_detail_load(1)
        await pilot.pause()
        object.__setattr__(records[1], '_cached_detail_sections', (section_b,))
        screen._schedule_record_detail_load(1)
        screen._schedule_record_detail_load(0)

        screen.snapshot = adapters.BrowserPageSnapshot(
            title='任务',
            subtitle='s',
            records=[],
            shared_sections=[],
        )
        await screen._update_selected_record(0)

        nav_item = tui_modules.cli_tui_widgets.NavigationItem('cache', '缓存', '3', 'd')
        opened: list[str] = []
        tui_app.open_view = lambda key: opened.append(key)  # type: ignore[method-assign]
        screen._open_sidebar_item(SimpleNamespace(item=SimpleNamespace(item=nav_item)))
        screen._open_sidebar_item(SimpleNamespace(item=SimpleNamespace(item=object())))
        screen._open_sidebar_item(
            SimpleNamespace(
                item=SimpleNamespace(
                    item=tui_modules.cli_tui_widgets.NavigationItem('jobs', '任务', '1', 'd')
                )
            )
        )
        assert opened == ['cache']
        screen.on_sidebar_selected(SimpleNamespace(item=SimpleNamespace(item=nav_item)))
        screen.on_sidebar_highlighted(SimpleNamespace(item=SimpleNamespace(item=nav_item)))


@pytest.mark.asyncio
async def test_browser_load_async_stale_and_index_guards(tui_modules: SimpleNamespace) -> None:
    adapters = tui_modules.cli_tui_adapters
    record = adapters.BrowserRecordSnapshot(
        key='job:1',
        title='R1',
        status='ok',
        summary='s',
        metadata_lines=[],
        detail_sections=[],
        detail_loader=lambda: [adapters.DetailSectionSnapshot(title='L', status='ok', lines=['x'])],
    )
    snapshot = adapters.BrowserPageSnapshot(
        title='任务',
        subtitle='s',
        records=[record],
        shared_sections=[],
    )
    screen = _make_screen(tui_modules, snapshot)
    rendered: list[bool] = []

    async def fake_render(*, eager: bool = False) -> None:
        del eager
        rendered.append(True)

    screen._render_record_detail = fake_render  # type: ignore[method-assign]

    # stale request id
    screen._record_detail_request_id = 1
    await screen._load_record_detail_async(0, request_id=0)
    assert rendered == []

    # wrong selected index
    screen.selected_record_index = 1
    screen._record_detail_request_id = 3
    await screen._load_record_detail_async(0, request_id=3)
    assert rendered == []

    # success path
    screen.selected_record_index = 0
    screen._record_detail_request_id = 4
    await screen._load_record_detail_async(0, request_id=4)
    assert rendered == [True]


@pytest.mark.asyncio
async def test_browser_execute_action_and_clear_search(
    monkeypatch: MonkeyPatch,
    tui_modules: SimpleNamespace,
) -> None:
    snapshot = tui_modules.cli_tui_adapters.BrowserPageSnapshot(
        title='任务',
        subtitle='s',
        records=[
            tui_modules.cli_tui_adapters.BrowserRecordSnapshot(
                key='job:1',
                title='Job',
                status='ok',
                summary='正常 · Cron x',
                metadata_lines=[],
                detail_sections=[],
            )
        ],
        shared_sections=[],
        search=tui_modules.cli_tui_search.PageSearchContext(
            placeholder='搜索',
            query='sync',
            suggestions=['a'],
        ),
    )
    screen = _make_screen(tui_modules, snapshot)
    action = screen._resolve_action('global')
    assert action is not None

    remembered: list[tuple[str, str]] = []
    refresh: list[str] = []
    monkeypatch.setattr(
        tui_modules.cli_tui_browser.BrowserScreen,
        'app',
        property(
            lambda self: SimpleNamespace(
                remember_browser_query=lambda view, query: remembered.append((view, query)),
                action_refresh_current_view=lambda: refresh.append('r'),
            )
        ),
    )
    screen._handle_search_submitted('new')
    screen._clear_search()
    assert remembered[-1] == ('jobs', '')

    rendered: list[bool] = []

    async def fake_render(*, eager: bool = False) -> None:
        del eager
        rendered.append(True)

    screen._render_record_detail = fake_render  # type: ignore[method-assign]
    result_cls = __import__('cli.tui.actions.models', fromlist=['TuiActionResult']).TuiActionResult

    async def fake_execute_with_feedback(screen_obj, action_spec, env, view, callback):
        result = result_cls(spec=action_spec, payload={'ok': True, 'message': 'ok'})
        await callback(result, ['结果: 成功'])
        return result

    monkeypatch.setattr(
        tui_modules.cli_tui_browser.TUI_SCREEN_INTERACTION_SERVICE,
        'execute_action_with_feedback',
        fake_execute_with_feedback,
    )
    await screen._execute_action(action)
    assert rendered == [True]
    assert screen._last_action_result is not None

    # cancel already-done task is a no-op
    class DoneTask:
        def done(self) -> bool:
            return True

        def cancel(self) -> None:
            raise AssertionError('should not cancel')

    screen._cancel_task(None)
    screen._cancel_task(DoneTask())  # type: ignore[arg-type]


def test_browser_support_filter_helpers(tui_modules: SimpleNamespace) -> None:
    support = tui_modules.cli_tui_browser.BrowserScreenSupport()
    snapshot = tui_modules.cli_tui_adapters.BrowserPageSnapshot(
        title='任务',
        subtitle='s',
        records=[],
        shared_sections=[],
        filters=list(tui_modules.cli_tui_search.JOB_FILTER_OPTIONS),
        active_filter_key='failed',
        search=tui_modules.cli_tui_search.PageSearchContext(placeholder='p', query='q', suggestions=[]),
    )
    assert support.build_filter_bar_text(snapshot)
    assert support.current_search_query(snapshot) == 'q'


def test_interaction_confirm_callback_false_branch(
    monkeypatch: MonkeyPatch,
    tui_modules: SimpleNamespace,
) -> None:
    interactions = __import__('cli.tui.screens.interactions', fromlist=['TUI_SCREEN_INTERACTION_SERVICE'])
    service = interactions.TUI_SCREEN_INTERACTION_SERVICE
    action = tui_modules.cli_tui_browser.TUI_ACTION_REGISTRY.resolve_detail_action(
        view_key='ops',
        slot='primary',
        env='dev',
    )
    assert action is not None
    scheduled: list[object] = []

    def _push(screen: object, callback=None) -> None:
        del screen
        if callback is not None:
            callback(False, action)

    monkeypatch.setattr(
        service,
        'schedule_action_task',
        lambda *args, **kwargs: scheduled.append('x'),
    )
    service.confirm_and_schedule_action(
        SimpleNamespace(app=SimpleNamespace(push_screen=_push), notify=lambda *a, **k: None),
        action,
        None,
        lambda spec: None,  # type: ignore[arg-type, return-value]
    )
    assert scheduled == []


def test_workspace_structured_lines_title_separator_branch(tui_modules: SimpleNamespace) -> None:
    del tui_modules
    support = __import__('cli.tui.widgets.workspace', fromlist=['WORKSPACE_RENDERING']).WORKSPACE_RENDERING
    text = support.render_structured_lines(['body', '## Next', 'tail'], 'empty')
    assert '【Next】' in text
    hero = __import__('cli.tui.widgets.workspace', fromlist=['WorkspaceHero']).WorkspaceHero(
        title='Glow',
        subtitle='s',
        env='dev',
        active_view='jobs',
        summary='sum',
        refreshed_at='t',
    )
    assert 'Glow' in hero._build_render_text().plain


def test_status_panel_leading_blank_trim(tui_modules: SimpleNamespace) -> None:
    del tui_modules
    support = __import__('cli.tui.widgets.status_panel', fromlist=['STATUS_PANEL_RENDERING']).STATUS_PANEL_RENDERING
    text = support.render_structured_body('\n\n## Head\nbody\n\n')
    assert text.startswith('【Head】')
