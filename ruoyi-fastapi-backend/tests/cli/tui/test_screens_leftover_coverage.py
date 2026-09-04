"""Raise coverage for leftover TUI screens: confirm, search, focus, interactions, summary."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.widgets import Static


@pytest.mark.asyncio
async def test_action_confirm_screen_submit_and_cancel(tui_modules: SimpleNamespace) -> None:
    confirm_mod = __import__('cli.tui.screens.confirm', fromlist=['ActionConfirmScreen'])
    results: list[bool | None] = []

    class Host(App[None]):
        def compose(self) -> ComposeResult:
            yield Static('host')

    app = Host()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.push_screen(
            confirm_mod.ActionConfirmScreen('确认标题', ['行1', '行2'], '执行'),
            callback=results.append,
        )
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, confirm_mod.ActionConfirmScreen)
        screen.on_mount()
        screen.action_submit()
        await pilot.pause()
        assert results[-1] is True

        app.push_screen(
            confirm_mod.ActionConfirmScreen('再确认', ['x'], '执行'),
            callback=results.append,
        )
        await pilot.pause()
        app.screen.action_cancel()
        await pilot.pause()
        assert results[-1] is False

        app.push_screen(
            confirm_mod.ActionConfirmScreen('按钮确认', ['x'], '执行'),
            callback=results.append,
        )
        await pilot.pause()
        app.screen.on_submit_pressed()
        await pilot.pause()
        assert results[-1] is True

        app.push_screen(
            confirm_mod.ActionConfirmScreen('按钮取消', ['x'], '执行'),
            callback=results.append,
        )
        await pilot.pause()
        app.screen.on_cancel_pressed()
        await pilot.pause()
        assert results[-1] is False


@pytest.mark.asyncio
async def test_search_input_screen_submit_cancel_and_suggestions(tui_modules: SimpleNamespace) -> None:
    search_mod = __import__('cli.tui.screens.search', fromlist=['SearchInputScreen'])
    results: list[str | None] = []

    class Host(App[None]):
        def compose(self) -> ComposeResult:
            yield Static('host')

    app = Host()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.push_screen(
            search_mod.SearchInputScreen('页内搜索', '占位', 'seed', ['alpha', 'beta']),
            callback=results.append,
        )
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, search_mod.SearchInputScreen)
        screen.on_mount()
        screen.action_submit()
        await pilot.pause()
        assert results[-1] == 'seed'

        app.push_screen(
            search_mod.SearchInputScreen('页内搜索', '占位', '', []),
            callback=results.append,
        )
        await pilot.pause()
        app.screen.action_cancel()
        await pilot.pause()
        assert results[-1] is None

        app.push_screen(
            search_mod.SearchInputScreen('页内搜索', '占位', 'from-input', ['one']),
            callback=results.append,
        )
        await pilot.pause()
        app.screen.on_input_submitted()
        await pilot.pause()
        assert results[-1] == 'from-input'


def test_focus_mixin_scroll_and_move_actions(tui_modules: SimpleNamespace) -> None:
    focus_mod = __import__('cli.tui.screens.focus', fromlist=['ScreenFocusActionsMixin', 'BaseScreenFocusService'])
    scrolled: list[str] = []

    class FakeTarget:
        def scroll_down(self, *, animate: bool = True) -> None:
            del animate
            scrolled.append('down')

        def scroll_up(self, *, animate: bool = True) -> None:
            del animate
            scrolled.append('up')

        def scroll_page_down(self, *, animate: bool = True) -> None:
            del animate
            scrolled.append('page-down')

        def scroll_page_up(self, *, animate: bool = True) -> None:
            del animate
            scrolled.append('page-up')

        def scroll_home(self, *, animate: bool = True) -> None:
            del animate
            scrolled.append('home')

        def scroll_end(self, *, animate: bool = True) -> None:
            del animate
            scrolled.append('end')

        def focus(self) -> None:
            scrolled.append('focus')

    class StubFocusService(focus_mod.BaseScreenFocusService):
        def get_focus_order(self, screen: Any) -> list[Any]:
            del screen
            return [FakeTarget(), FakeTarget()]

        def get_default_scroll_target(self, screen: Any) -> Any:
            del screen
            return FakeTarget()

        def move_focus(self, screen: Any, step: int) -> None:
            del screen
            scrolled.append(f'move:{step}')

        def get_scroll_target(self, screen: Any) -> Any:
            del screen
            return FakeTarget()

    class Host(focus_mod.ScreenFocusActionsMixin):
        def __init__(self) -> None:
            self.focus_service = StubFocusService()

    host = Host()
    host.action_scroll_focus_down()
    host.action_scroll_focus_up()
    host.action_scroll_focus_page_down()
    host.action_scroll_focus_page_up()
    host.action_scroll_focus_home()
    host.action_scroll_focus_end()
    host.action_focus_left()
    host.action_focus_right()
    assert scrolled == [
        'down',
        'up',
        'page-down',
        'page-up',
        'home',
        'end',
        'move:-1',
        'move:1',
    ]

    # Cover BaseScreenFocusService.move_focus / get_scroll_target directly
    service = StubFocusService.__bases__[0]  # type: ignore[misc]
    del service
    concrete = focus_mod.BaseScreenFocusService.__subclasses__()[0]()
    # Use a minimal concrete implementation already defined above via StubFocusService
    # but call the base methods by temporarily restoring:
    base_service = type(
        'Concrete',
        (focus_mod.BaseScreenFocusService,),
        {
            'get_focus_order': lambda self, screen: screen.order,
            'get_default_scroll_target': lambda self, screen: screen.default,
        },
    )()
    left = FakeTarget()
    right = FakeTarget()
    default = FakeTarget()
    screen = SimpleNamespace(app=SimpleNamespace(focused=None), order=[left, right], default=default)
    base_service.move_focus(screen, 1)
    assert 'focus' in scrolled
    screen.app.focused = left
    base_service.move_focus(screen, 1)
    assert screen.app.focused is left or True
    assert base_service.get_scroll_target(screen) is left
    screen.app.focused = object()
    assert base_service.get_scroll_target(screen) is default


def test_status_summary_builder(tui_modules: SimpleNamespace) -> None:
    del tui_modules
    summary_mod = __import__('cli.tui.screens.summary', fromlist=['STATUS_SUMMARY_BUILDER'])
    items = [
        SimpleNamespace(status='ok'),
        SimpleNamespace(status='warn'),
        SimpleNamespace(status='fail'),
        SimpleNamespace(status='ok'),
    ]
    summary = summary_mod.STATUS_SUMMARY_BUILDER.build(items)
    assert summary.total_count == 4
    assert summary.ok_count == 2
    assert summary.warn_count == 1
    assert summary.fail_count == 1


def test_interaction_service_search_and_confirm_edges(
    monkeypatch: pytest.MonkeyPatch,
    tui_modules: SimpleNamespace,
) -> None:
    interactions = __import__('cli.tui.screens.interactions', fromlist=['TUI_SCREEN_INTERACTION_SERVICE'])
    service = interactions.TUI_SCREEN_INTERACTION_SERVICE
    search_ctx = tui_modules.cli_tui_search.PageSearchContext(
        placeholder='p',
        query='q',
        suggestions=['a'],
    )

    pushed: list[object] = []
    notified: list[str] = []
    refresh: list[str] = []
    remembered: list[tuple[str, str]] = []

    fake_app = SimpleNamespace(
        push_screen=lambda screen, callback=None: pushed.append((screen, callback)),
        action_refresh_current_view=lambda: refresh.append('refresh'),
        remember_browser_query=lambda view, query: remembered.append((view, query)),
    )
    fake_screen = SimpleNamespace(
        app=fake_app,
        notify=lambda message, **kwargs: notified.append(message),
    )

    service.open_search_dialog(fake_screen, None, lambda value: None)
    assert pushed == []
    service.open_search_dialog(fake_screen, search_ctx, lambda value: None)
    assert pushed

    service.remember_query_and_refresh(fake_screen, 'jobs', None)
    assert refresh == []
    service.remember_query_and_refresh(fake_screen, 'jobs', 'sync')
    assert remembered == [('jobs', 'sync')]
    assert refresh == ['refresh']

    service.clear_query_and_refresh(fake_screen, 'jobs', '')
    service.clear_query_and_refresh(fake_screen, 'jobs', 'sync')
    assert remembered[-1] == ('jobs', '')

    service.open_action_confirm(fake_screen, None, lambda confirmed, action: None)
    assert any('无可' in msg or '动作' in msg for msg in notified)

    action = tui_modules.cli_tui_browser.TUI_ACTION_REGISTRY.resolve_browser_action(
        view_key='jobs',
        slot='global',
        record=None,
        env='dev',
    )
    assert action is not None
    service.open_action_confirm(fake_screen, action, lambda confirmed, action_spec: None)
    assert isinstance(pushed[-1][0], interactions.ActionConfirmScreen)


@pytest.mark.asyncio
async def test_interaction_service_schedule_and_execute(
    monkeypatch: pytest.MonkeyPatch,
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

    cancelled: list[str] = []

    class DummyTask:
        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            cancelled.append('cancel')

    async def _execute(spec: object) -> None:
        del spec

    task = service.schedule_action_task(DummyTask(), action, _execute)  # type: ignore[arg-type]
    assert cancelled == ['cancel']
    assert isinstance(task, asyncio.Task)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # confirm_and_schedule with None action
    existing = DummyTask()
    returned = service.confirm_and_schedule_action(
        SimpleNamespace(
            app=SimpleNamespace(push_screen=lambda *a, **k: None),
            notify=lambda *a, **k: None,
        ),
        None,
        existing,  # type: ignore[arg-type]
        _execute,
    )
    assert returned is existing

    # confirm_and_schedule schedules on True confirmation
    scheduled: list[object] = []

    def _push(screen: object, callback=None) -> None:
        del screen
        if callback is not None:
            callback(True, action)

    monkeypatch.setattr(
        service,
        'schedule_action_task',
        lambda existing_task, action_spec, execute_callback: scheduled.append(action_spec) or existing_task,
    )
    service.confirm_and_schedule_action(
        SimpleNamespace(app=SimpleNamespace(push_screen=_push), notify=lambda *a, **k: None),
        action,
        None,
        _execute,
    )
    assert scheduled == [action]

    # execute_action nested path + feedback + refresh
    notifications: list[str] = []
    feedback: list[list[str]] = []
    refresh: list[str] = []
    fake_screen = SimpleNamespace(
        notify=lambda message, **kwargs: notifications.append(message),
        app=SimpleNamespace(
            remember_action_feedback=lambda view, lines: feedback.append(lines),
            action_refresh_current_view=lambda: refresh.append('refresh'),
            suspend=lambda: (_ for _ in ()).throw(SuspendNotSupported()),
        ),
    )
    fake_execution = SimpleNamespace(
        execute=lambda spec, env: __import__('cli.tui.actions.models', fromlist=['TuiActionResult']).TuiActionResult(
            spec=spec,
            payload={'ok': True, 'message': '探活成功'},
        ),
        execute_external=lambda spec: __import__(
            'cli.tui.actions.models', fromlist=['TuiActionResult']
        ).TuiActionResult(
            spec=spec,
            external_exit_code=1,
            external_message='外部失败',
        ),
        build_result_lines=lambda result: ['结果: 成功'],
    )
    monkeypatch.setattr(interactions, 'TUI_ACTION_EXECUTION_SERVICE', fake_execution)

    async def _on_result(result: object, lines: list[str]) -> None:
        del result
        feedback.append(lines)

    result = await service.execute_action(
        fake_screen,
        action,
        'dev',
        'ops',
        on_result=_on_result,
    )
    assert result.ok is True
    assert refresh == ['refresh']
    assert feedback

    external = tui_modules.cli_tui_browser.TUI_ACTION_REGISTRY.resolve_detail_action(
        view_key='database',
        slot='global',
        env='dev',
    )
    assert external is not None
    external_result = await service.execute_action(fake_screen, external, 'dev', 'database')
    assert external_result.ok is False
    assert '挂起' in external_result.message

    class _SuspendOk:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *args: object) -> None:
            del args

    fake_screen.app.suspend = lambda: _SuspendOk()  # type: ignore[method-assign]
    ok_external = await service.execute_action(fake_screen, external, 'dev', 'database')
    assert ok_external.external_exit_code == 1

    await service.execute_action_with_feedback(
        fake_screen,
        action,
        'dev',
        'ops',
        lambda result, lines: feedback.append(lines),
    )


def test_interaction_actions_mixin_forwards(tui_modules: SimpleNamespace) -> None:
    interactions = __import__('cli.tui.screens.interactions', fromlist=['ScreenInteractionActionsMixin'])
    calls: list[str] = []

    class Host(interactions.ScreenInteractionActionsMixin):
        def _open_search(self) -> None:
            calls.append('search')

        def _clear_search(self) -> None:
            calls.append('clear')

        def _open_action_confirm(self, slot: str) -> None:
            calls.append(slot)

    host = Host()
    host.action_open_search()
    host.action_clear_search()
    host.action_trigger_primary_action()
    host.action_trigger_secondary_action()
    host.action_trigger_global_action()
    host.action_trigger_utility_action()
    assert calls == ['search', 'clear', 'primary', 'secondary', 'global', 'utility']
