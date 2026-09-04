"""Close leftover coverage gaps in cli.completion.providers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch

from cli.completion.providers import (
    COMPLETION_PROVIDER_GATEWAY,
    CompletionContextResolver,
    CompletionProviderGateway,
    CompletionProviderRegistry,
    DynamicCompletionService,
    PathCompletionProvider,
    StaticCompletionProvider,
)


def test_context_resolver_env_and_cache_from_ctx_and_comp_words(monkeypatch: MonkeyPatch) -> None:
    resolver = CompletionContextResolver()

    ctx = SimpleNamespace(params={'env': '  prod  ', 'cache_name': '  sys_config  '})
    assert resolver.resolve_completion_env(ctx) == 'prod'
    assert resolver.resolve_cache_name_for_completion(ctx) == 'sys_config'

    monkeypatch.setenv('COMP_WORDS', 'ruoyi --env=dockerpg cache get')
    assert resolver.resolve_completion_env(None) == 'dockerpg'

    monkeypatch.setenv('COMP_WORDS', 'ruoyi --env staging app')
    assert resolver.resolve_completion_env(None) == 'staging'

    monkeypatch.delenv('COMP_WORDS', raising=False)
    assert resolver.resolve_completion_env(None) == 'dev'

    monkeypatch.setenv('COMP_WORDS', 'ruoyi cache get sys_dict site')
    assert resolver.resolve_cache_name_for_completion(None) == 'sys_dict'

    monkeypatch.setenv('COMP_WORDS', 'ruoyi cache ttl login_tokens k')
    assert resolver.resolve_cache_name_for_completion(None) == 'login_tokens'

    monkeypatch.setenv('COMP_WORDS', 'ruoyi cache get')
    assert resolver.resolve_cache_name_for_completion(None) == ''

    monkeypatch.setenv('COMP_WORDS', 'ruoyi app run')
    assert resolver.resolve_cache_name_for_completion(None) == ''

    monkeypatch.setenv('COMP_WORDS', 'ruoyi cache clear sys_config')
    assert resolver.resolve_cache_name_for_completion(None) == ''

    monkeypatch.setenv('COMP_WORDS', 'ruoyi cache get --flag')
    assert resolver.resolve_cache_name_for_completion(None) == ''

    monkeypatch.delenv('COMP_WORDS', raising=False)
    assert resolver.resolve_cache_name_for_completion(None) == ''


def test_to_display_path_falls_back_outside_project(tmp_path: Path) -> None:
    resolver = CompletionContextResolver()
    outside = tmp_path / 'outside.txt'
    outside.write_text('x', encoding='utf-8')
    project = tmp_path / 'project'
    project.mkdir()
    assert resolver.to_display_path(outside, project_dir=project) == outside.as_posix()


def test_dynamic_extract_helpers_cover_edge_cases() -> None:
    service = DynamicCompletionService()

    assert service.extract_completion_items('bad', 'k') == []
    assert service.extract_completion_items({'ok': False}, 'k') == []
    assert service.extract_completion_items({'ok': True, 'items': 'x'}, 'k') == []
    assert service.extract_completion_items({'ok': True, 'page': {'rows': 'x'}}, 'k') == []
    assert service.extract_completion_items({'ok': True, 'items': ['x', {'k': '  a  '}, {'k': 1}]}, 'k') == ['a']
    assert service.extract_completion_items(
        {'ok': True, 'page': {'rows': [{'k': 'b'}, {'k': ''}, 'skip']}},
        'k',
    ) == ['b']

    assert service.extract_completion_values('bad', 'k') == []
    assert service.extract_completion_values({'ok': False}, 'k') == []
    assert service.extract_completion_values({'ok': True, 'items': 'x'}, 'k') == []
    assert service.extract_completion_values({'ok': True, 'page': {'rows': None}}, 'k') == []
    assert service.extract_completion_values(
        {'ok': True, 'items': [{'k': 'a'}, {'k': 3}, {'k': ''}, 'x', {'k': 3}]},
        'k',
    ) == ['3', 'a']
    assert service.extract_completion_values(
        {'ok': True, 'page': {'rows': [{'k': 9}]}},
        'k',
    ) == ['9']

    assert service.extract_completion_list('bad', 'keys') == []
    assert service.extract_completion_list({'ok': False}, 'keys') == []
    assert service.extract_completion_list({'ok': True, 'keys': 'x'}, 'keys') == []
    assert service.extract_completion_list({'ok': True, 'keys': [' a ', '', 1, 'b']}, 'keys') == ['a', 'b']


def test_static_provider_shell_env_and_cache_name_fallbacks(monkeypatch: MonkeyPatch) -> None:
    registry = CompletionProviderRegistry()
    static = registry.static_provider
    gateway = CompletionProviderGateway(provider_registry=registry)

    assert 'bash' in static.list_completion_shells()
    assert gateway.list_completion_shells()
    assert COMPLETION_PROVIDER_GATEWAY.list_completion_shells()

    monkeypatch.setattr(
        registry.dynamic_service,
        'load_runtime_module',
        lambda module_name: (_ for _ in ()).throw(ImportError('missing')),
    )
    assert static.list_static_cache_names() == []
    assert gateway.list_static_cache_names() == []

    object.__setattr__(
        static,
        'environment_option_service',
        SimpleNamespace(discover_env_names=lambda: ['dev', 'prod', 'dockerpg']),
    )
    assert static.complete_env_values(None, None, 'do') == ['dockerpg']
    assert gateway.complete_env_values(None, None, 'p') == ['prod']
    assert static.complete_shell_names(None, None, 'ba') == ['bash']
    assert gateway.complete_shell_names(None, None, 'z') == ['zsh']


def test_path_provider_skips_hidden_and_covers_output_branches(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    (tmp_path / 'app.py').write_text('', encoding='utf-8')
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'env.py').write_text('', encoding='utf-8')
    (tmp_path / 'cli').mkdir()
    sql_ok = tmp_path / 'sql'
    sql_ok.mkdir()
    (sql_ok / 'ok.sql').write_text('select 1;', encoding='utf-8')
    hidden = tmp_path / '.git' / 'sql'
    hidden.mkdir(parents=True)
    (hidden / 'secret.sql').write_text('x', encoding='utf-8')
    cache = tmp_path / '__pycache__'
    cache.mkdir()
    (cache / 'x.sql').write_text('x', encoding='utf-8')

    monkeypatch.chdir(tmp_path)

    class LocalResolver:
        def normalize_completion_prefix(self, incomplete: str) -> str:
            return CompletionContextResolver.normalize_completion_prefix(incomplete)

        def to_display_path(self, path: Path, *, project_dir: Path) -> str:
            return CompletionContextResolver.to_display_path(path, project_dir=project_dir)

        def resolve_project_dir(self) -> Path:
            return tmp_path.resolve()

        def resolve_user_cwd(self) -> Path:
            return tmp_path.resolve()

    path_provider = PathCompletionProvider(context_resolver=LocalResolver())  # type: ignore[arg-type]

    sqls = path_provider.complete_sql_files(None, None, '')
    assert 'sql/ok.sql' in sqls
    assert not any('secret.sql' in item for item in sqls)
    assert not any('__pycache__' in item for item in sqls)

    build = tmp_path / 'build'
    build.mkdir()
    (build / 'out.zip').write_text('z', encoding='utf-8')
    (build / 'notes.txt').write_text('t', encoding='utf-8')
    nested = build / 'nested'
    nested.mkdir()

    assert path_provider.complete_output_paths(None, None, 'missing/') == []
    assert path_provider.complete_output_paths(None, None, 'missing-file') == []

    trailing = path_provider.complete_output_paths(None, None, 'build/')
    assert 'build/out.zip' in trailing
    assert any(item.endswith('nested/') for item in trailing)
    assert 'build/notes.txt' not in trailing

    partial = path_provider.complete_output_paths(None, None, 'build/ou')
    assert 'build/out.zip' in partial

    absolute_dir = str(build).replace('\\', '/') + '/'
    absolute = path_provider.complete_output_paths(None, None, absolute_dir)
    assert any(item.endswith('out.zip') or item.endswith('nested/') for item in absolute)

    absolute_partial = path_provider.complete_output_paths(None, None, str(build / 'ou').replace('\\', '/'))
    assert any(item.endswith('out.zip') for item in absolute_partial)


def test_domain_cache_keys_returns_empty_without_cache_name() -> None:
    gateway = CompletionProviderGateway()
    assert gateway.complete_cache_keys(None, None, 'site') == []
    assert gateway.provider_registry.domain_provider.complete_cache_keys(None, None, 'site') == []


def test_static_provider_standalone_construction() -> None:
    provider = StaticCompletionProvider()
    assert isinstance(provider.list_completion_shells(), list)
