"""Coverage boost for cli.tui.adapters miss branches (failure/empty/warn paths)."""

from __future__ import annotations

from types import ModuleType, SimpleNamespace

import pytest
from pytest import MonkeyPatch


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _payload(ok: bool = True, **extra: object) -> dict:
    return {'ok': ok, **extra}


# ---------------------------------------------------------------------------
# __init__ registry + models + base
# ---------------------------------------------------------------------------


def test_snapshot_collector_registry_normalize_get_and_missing_key(
    load_adapter_module,
) -> None:
    registry_mod = load_adapter_module('cli.tui.adapters')
    registry = registry_mod.TUI_SNAPSHOT_COLLECTOR_REGISTRY
    assert registry.normalize_view_key('  APP ') == 'app'
    assert registry.get_collector('app') is not None
    assert registry.get_collector('nope') is None
    with pytest.raises(KeyError):
        registry.collect('missing-view', 'dev')

    # successful collect path (line 72) without hitting real CLI
    registry.collectors['dashboard'] = lambda env: SimpleNamespace(env=env, panels=[])
    snap = registry.collect('dashboard', 'dev')
    assert snap.env == 'dev'


def test_model_renderer_message_loading_and_failure_detail_branches(
    load_adapter_module,
) -> None:
    models = load_adapter_module('cli.tui.adapters.models')
    renderer = models.TUI_ADAPTER_MODEL_RENDERER

    assert renderer.extract_payload_message(None) == '-'
    assert renderer.extract_payload_message({'error': 'boom'}) == 'boom'
    assert renderer.extract_payload_message({}) == '-'

    loading = renderer.build_loading_lines(
        loading_label='加载',
        loading_value='中',
        detail='请稍候',
    )
    assert any('加载: 中' in line for line in loading)

    fail_none = renderer.build_failure_lines(None, empty_label='X', empty_value='无')
    assert any('结果消息: -' in line for line in fail_none)

    fail_rich = renderer.build_failure_lines(
        {
            'ok': False,
            'message': '失败',
            'hint': '检查配置',
            'error': 'E1',
            'stderr': 'err-out',
            'stdout': 'std-out',
        },
        empty_label='Y',
        empty_value='无',
    )
    assert any('建议提示:' in line for line in fail_rich)
    assert any('错误信息:' in line for line in fail_rich)
    assert any('标准错误:' in line for line in fail_rich)
    assert any('标准输出:' in line for line in fail_rich)

    record = models.BrowserRecordSnapshot(
        key='k',
        title='t',
        status='ok',
        summary='s',
        metadata_lines=[],
        detail_sections=[
            models.DetailSectionSnapshot(title='d', status='ok', lines=['a']),
        ],
        detail_loader=None,
    )
    assert record.resolve_detail_sections()[0].title == 'd'


def test_base_build_empty_record_filtered_and_empty_paths(
    load_adapter_module,
) -> None:
    base = load_adapter_module('cli.tui.adapters.base')

    class _Adapter(base.BaseBrowserAdapter):
        def collect_snapshot(self, env: str, query: str = ''):
            raise NotImplementedError

    adapter = _Adapter(page_title='测', search_view_key='x', filter_options=())
    filtered = adapter.build_empty_record(
        key='x:none',
        subject='项',
        empty_label='项',
        has_source_rows=True,
        filtered_summary='筛选无匹配',
        empty_summary='无源数据',
        filtered_empty_value='暂无匹配',
        empty_empty_value='暂无',
        filtered_detail='筛选无匹配说明',
        empty_detail='无源数据说明',
    )
    assert '筛选无匹配' in filtered.summary
    empty = adapter.build_empty_record(
        key='x:empty',
        subject='项',
        empty_label='项',
        has_source_rows=False,
        filtered_summary='筛选无匹配',
        empty_summary='无源数据',
        filtered_empty_value='暂无匹配',
        empty_empty_value='暂无',
        filtered_detail='筛选无匹配说明',
        empty_detail='无源数据说明',
    )
    assert '无源数据' in empty.summary


# ---------------------------------------------------------------------------
# app adapter
# ---------------------------------------------------------------------------


def test_app_section_builder_failure_warn_and_preview_branches(
    app_adapter: ModuleType,
) -> None:
    builder = app_adapter.AppSectionBuilder()

    assert builder.resolve_completion_preview_shell(None) == 'bash'
    assert builder.resolve_completion_preview_shell({'ok': True, 'shells': {}}) == 'bash'
    assert (
        builder.resolve_completion_preview_shell(
            {
                'ok': True,
                'activeShell': 'unsupported',
                'shells': {
                    'unsupported': {'supported': False},
                    'zsh': {'supported': True},
                },
            }
        )
        == 'zsh'
    )
    assert (
        builder.resolve_completion_preview_shell(
            {'ok': True, 'activeShell': 'fish', 'shells': {'fish': {'supported': True}}}
        )
        == 'fish'
    )

    assert builder.build_env_section(None).status == 'fail'
    assert builder.build_config_section({'ok': False}).status == 'fail'
    assert builder.build_dependency_section(None).status == 'fail'
    assert builder.build_routes_section({'ok': False}).status == 'fail'
    assert builder.build_completion_section(None).status == 'fail'
    assert builder.build_doctor_section(None).status == 'fail'

    routes = builder.build_routes_section(
        {
            'ok': True,
            'count': 2,
            'groupedRoutes': {},
            'routes': [
                {'path': '/a', 'methods': ['GET'], 'summary': 'alpha'},
                'skip-me',
                {'path': '/b', 'methods': ['POST'], 'summary': 'beta'},
            ],
        }
    )
    assert any('/a' in line for line in routes.lines)
    assert any('暂无标签分组' in line for line in routes.lines)

    empty_preview = builder.build_completion_preview_section(
        'bash',
        SimpleNamespace(returncode=0, stdout='   \n  ', stderr=''),
    )
    assert empty_preview.status == 'info'

    fail_preview = builder.build_completion_preview_section(
        'bash',
        SimpleNamespace(returncode=1, stdout='', stderr='gen failed'),
    )
    assert fail_preview.status == 'fail'

    overview_env_fail = builder.build_overview_section(None, {'ok': True}, {'ok': True}, {'ok': True}, {'ok': True})
    assert overview_env_fail.status == 'fail'

    overview_doctor = builder.build_overview_section(
        {'ok': True, 'runtime': {}},
        {'ok': True, 'config': {}},
        {'ok': False},
        {'ok': True, 'count': 1},
        {'ok': True},
    )
    assert overview_doctor.status == 'fail'
    assert '启动前检查异常' in overview_doctor.lines[1]

    overview_completion = builder.build_overview_section(
        {'ok': True, 'runtime': {}},
        {'ok': True, 'config': {}},
        {'ok': True},
        {'ok': True, 'count': 1},
        {'ok': False},
    )
    assert overview_completion.status == 'warn'

    overview_routes = builder.build_overview_section(
        {'ok': True, 'runtime': {}},
        {'ok': True, 'config': {}},
        {'ok': True},
        {'ok': False},
        {'ok': True},
    )
    assert overview_routes.status == 'warn'

    overview_zero = builder.build_overview_section(
        {'ok': True, 'runtime': {}},
        {'ok': True, 'config': {}},
        {'ok': True},
        {'ok': True, 'count': 0},
        {'ok': True},
    )
    assert overview_zero.status == 'info'


# ---------------------------------------------------------------------------
# cache adapter
# ---------------------------------------------------------------------------


def test_cache_extractor_judgement_ttl_and_empty_paths(
    monkeypatch: MonkeyPatch,
    cache_adapter: ModuleType,
) -> None:
    extractor = cache_adapter.CacheRowExtractor()
    assert extractor.extract_cache_name_rows(None) == []
    assert extractor.extract_cache_name_rows({'cacheNames': 'bad'}) == []
    assert extractor.extract_cache_name_rows({'cacheNames': ['plain', {'cacheName': 'x'}]}) == [
        {'cacheName': 'plain', 'remark': ''},
        {'cacheName': 'x'},
    ]

    adapter = cache_adapter.CACHE_BROWSER_ADAPTER
    builder = adapter.section_builder

    fail_judgement = builder.build_overview_judgement_section(None, [])
    assert fail_judgement.status == 'fail'

    empty_names = builder.build_overview_judgement_section({'ok': True, 'cacheNames': []}, [])
    assert empty_names.status == 'info'
    assert '没有登记' in empty_names.lines[1]

    no_match = builder.build_overview_judgement_section(
        {'ok': True, 'cacheNames': [{'cacheName': 'a'}]},
        [],
    )
    assert no_match.status == 'info'
    assert '没有命中' in no_match.lines[1]

    assert builder.build_keys_summary_section({'ok': False}).status == 'fail'
    empty_keys = builder.build_keys_summary_section({'ok': True, 'cacheName': 'c', 'keys': []})
    assert any('没有键' in line for line in empty_keys.lines)
    assert builder.build_keys_section(None).status == 'fail'

    assert builder.render_ttl_text(None) != ''
    assert builder.render_ttl_text({'ok': True, 'persistent': True}) == '永久'
    assert builder.render_ttl_text({'ok': True, 'expires': False, 'ttlSeconds': -1}) == '-1'
    assert builder.build_key_detail_sections('c', [], 'dev') == []

    def fake_run(*arguments: str, parse_json: bool = False) -> SimpleNamespace:
        del parse_json
        if arguments[0:2] == ('cache', 'get'):
            return SimpleNamespace(payload={'ok': False, 'message': 'no value'})
        if arguments[0:2] == ('cache', 'ttl'):
            return SimpleNamespace(payload={'ok': False, 'message': 'no ttl'})
        if arguments[0:2] == ('cache', 'keys'):
            return SimpleNamespace(payload={'ok': True, 'keys': ['k1'], 'cacheName': 'c'})
        return SimpleNamespace(payload={'ok': False})

    monkeypatch.setattr(cache_adapter.NESTED_CLI_SUPPORT, 'run', fake_run)
    details = builder.build_key_detail_sections('c', ['k1'], 'dev')
    assert details[0].status == 'fail'
    assert any('TTL 结果' in line for line in details[0].lines)

    def fake_partial(*arguments: str, parse_json: bool = False) -> SimpleNamespace:
        del parse_json
        if arguments[0:2] == ('cache', 'get'):
            return SimpleNamespace(payload={'ok': True, 'cacheValue': None})
        return SimpleNamespace(payload={'ok': False, 'message': 'ttl fail'})

    monkeypatch.setattr(cache_adapter.NESTED_CLI_SUPPORT, 'run', fake_partial)
    warn_details = builder.build_key_detail_sections('c', ['k2'], 'dev')
    assert warn_details[0].status == 'warn'
    assert any('> -' in line for line in warn_details[0].lines)

    failure_record = adapter.record_builder.build_failure_record({'ok': False, 'message': 'down'})
    assert failure_record.key == 'cache:unavailable'

    def fake_stats(*_a: str, parse_json: bool = False) -> SimpleNamespace:
        del parse_json
        return SimpleNamespace(payload={'ok': False, 'message': 'stats fail'})

    monkeypatch.setattr(cache_adapter.NESTED_CLI_SUPPORT, 'run', fake_stats)
    fail_snap = adapter.collect_snapshot('dev')
    assert fail_snap.records[0].key == 'cache:unavailable'

    def fake_empty_stats(*_a: str, parse_json: bool = False) -> SimpleNamespace:
        del parse_json
        return SimpleNamespace(
            payload={'ok': True, 'dbSize': 0, 'info': {}, 'commandStats': [], 'cacheNames': []}
        )

    monkeypatch.setattr(cache_adapter.NESTED_CLI_SUPPORT, 'run', fake_empty_stats)
    empty_snap = adapter.collect_snapshot('dev', query='zzz')
    assert empty_snap.records[0].key == 'cache:none'


# ---------------------------------------------------------------------------
# crypto adapter
# ---------------------------------------------------------------------------


def test_crypto_section_failure_and_overview_warn_branches(
    crypto_adapter: ModuleType,
) -> None:
    builder = crypto_adapter.CryptoSectionBuilder()
    assert builder.build_validate_section(None).status == 'fail'
    validate_err = builder.build_validate_section({'ok': False, 'message': 'bad', 'error': 'E'})
    assert any('错误:' in line for line in validate_err.lines)
    assert builder.build_public_identity_section(None).status == 'fail'
    assert builder.build_supported_kids_section({'ok': True}).status == 'fail'
    assert builder.build_public_preview_section(None).status == 'fail'
    empty_preview = builder.build_public_preview_section(
        {'ok': True, 'publicKey': {'publicKey': '', 'kid': 'k1'}}
    )
    assert empty_preview.status == 'info'

    overview_fail = builder.build_overview_section({'ok': False}, {'ok': True, 'publicKey': {'kid': 'a'}})
    assert overview_fail.status == 'fail'
    overview_warn = builder.build_overview_section({'ok': True}, {'ok': False})
    assert overview_warn.status == 'warn'


# ---------------------------------------------------------------------------
# ops adapter
# ---------------------------------------------------------------------------


def test_ops_section_failure_missing_deps_and_disk_skip(
    ops_adapter: ModuleType,
) -> None:
    builder = ops_adapter.OpsSectionBuilder()
    assert builder.build_health_section(None).status == 'fail'
    assert builder.build_ping_db_section(None).status == 'fail'
    assert builder.build_ping_redis_section(None).status == 'fail'
    assert builder.build_dependency_section(None).status == 'fail'
    assert builder.build_server_section(None).status == 'fail'
    assert builder.build_disk_section({'ok': False}).status == 'fail'

    deps = builder.build_dependency_section(
        {
            'ok': False,
            'message': '缺依赖',
            'missingRequired': ['fastapi', 'redis'],
            'packages': {'python': {'installed': True, 'version': '3.13'}},
        }
    )
    assert any('缺失项' in line for line in deps.lines)

    disk = builder.build_disk_section(
        {
            'ok': True,
            'server': {
                'sysFiles': [
                    'skip',
                    {'dirName': '/data', 'used': '1', 'total': '2', 'usage': '50%', 'free': '1'},
                ]
            },
        }
    )
    assert disk.status == 'ok'
    assert any('/data' in line for line in disk.lines)

    overview_deps = builder.build_overview_section(
        {'ok': True},
        {'ok': False, 'missingRequired': ['x']},
        {'ok': True, 'server': {'cpu': {}, 'mem': {}}},
    )
    assert overview_deps.status == 'warn'

    overview_server = builder.build_overview_section(
        {'ok': True},
        {'ok': True, 'missingRequired': []},
        {'ok': False},
    )
    assert overview_server.status == 'warn'


# ---------------------------------------------------------------------------
# gen adapter
# ---------------------------------------------------------------------------


def test_gen_section_failure_risk_empty_preview_and_overview(
    monkeypatch: MonkeyPatch,
    gen_adapter: ModuleType,
) -> None:
    adapter = gen_adapter.GEN_BROWSER_ADAPTER
    builder = adapter.section_builder

    assert builder.build_gen_focus_section(None).status == 'fail'
    assert builder.build_gen_generation_section({'ok': False}).status == 'fail'
    assert builder.build_gen_column_summary_section(None).status == 'fail'
    assert builder.build_gen_columns_section({'ok': True, 'detail': {'rows': []}}).status == 'fail'
    columns = builder.build_gen_columns_section(
        {
            'ok': True,
            'detail': {
                'rows': [
                    'skip',
                    {
                        'columnName': 'id',
                        'columnType': 'bigint',
                        'isPk': '1',
                        'isRequired': 'y',
                        'queryType': 'EQ',
                        'columnComment': '主键',
                    },
                ]
            },
        }
    )
    assert any('id' in line for line in columns.lines)

    precheck = builder.build_gen_precheck_section(
        {
            'ok': True,
            'detail': {
                'info': {'className': '', 'moduleName': '', 'businessName': ''},
                'rows': [],
            },
        },
        {'ok': True, 'preview': {}},
    )
    assert precheck.status == 'warn'
    assert any('生成类名缺失' in line for line in precheck.lines)
    assert any('所属模块缺失' in line for line in precheck.lines)
    assert any('业务标识缺失' in line for line in precheck.lines)
    assert any('字段列表为空' in line for line in precheck.lines)
    assert any('未识别到主键字段' in line for line in precheck.lines)
    assert any('未生成可预览模板' in line for line in precheck.lines)

    assert builder.build_gen_sync_precheck_section('t', None).status == 'fail'
    sync_miss = builder.build_gen_sync_precheck_section('demo', {'ok': True, 'page': {'rows': []}})
    assert sync_miss.status == 'warn'

    assert builder.build_gen_preview_section({'ok': False}).status == 'fail'
    empty_preview = builder.build_gen_preview_section({'ok': True, 'preview': {}, 'templateCount': 0})
    assert empty_preview.status == 'info'

    assert builder.build_gen_export_preview_section(None).status == 'fail'
    export_ok = builder.build_gen_export_preview_section(
        {
            'ok': True,
            'mode': 'zip',
            'dryRun': True,
            'tableNames': ['t1'],
            'message': 'ok',
            'outputFile': '/tmp/out.zip',
            'genPath': '/tmp/gen',
            'results': [
                'skip',
                {'tableName': 't1', 'ok': True, 'message': 'done'},
            ],
        }
    )
    assert any('输出文件:' in line for line in export_ok.lines)
    assert any('输出目录:' in line for line in export_ok.lines)

    assert builder.build_importable_tables_section({'ok': False}).status == 'fail'

    overview_incomplete = builder.build_gen_overview_section(
        [{'tableName': 'a', 'className': '', 'moduleName': '', 'businessName': ''}],
        [],
        [],
    )
    assert overview_incomplete.status == 'warn'

    overview_importable = builder.build_gen_overview_section([], [], [{'tableName': 'phys'}])
    assert overview_importable.status == 'info'

    failure_record = adapter.record_builder.build_failure_record({'ok': False, 'message': 'x'})
    assert failure_record.key == 'gen:unavailable'

    def fake_list_fail(*arguments: str, parse_json: bool = False) -> SimpleNamespace:
        del parse_json
        if arguments[0:2] == ('gen', 'list'):
            return SimpleNamespace(payload={'ok': False, 'message': 'list fail'})
        return SimpleNamespace(payload={'ok': True, 'page': {'rows': []}})

    monkeypatch.setattr(gen_adapter.NESTED_CLI_SUPPORT, 'run', fake_list_fail)
    fail_snap = adapter.collect_snapshot('dev')
    assert fail_snap.records[0].key == 'gen:unavailable'

    def fake_list_empty(*arguments: str, parse_json: bool = False) -> SimpleNamespace:
        del parse_json
        if arguments[0:2] == ('gen', 'list'):
            return SimpleNamespace(
                payload={'ok': True, 'page': {'rows': [{'tableName': 'keep', 'tableId': 1}]}}
            )
        return SimpleNamespace(payload={'ok': True, 'page': {'rows': []}})

    monkeypatch.setattr(gen_adapter.NESTED_CLI_SUPPORT, 'run', fake_list_empty)
    empty_snap = adapter.collect_snapshot('dev', query='no-match')
    assert empty_snap.records[0].key == 'gen:none'


# ---------------------------------------------------------------------------
# health / dashboard adapter
# ---------------------------------------------------------------------------


def test_health_formatting_panels_and_risk_branches(
    health_adapter: ModuleType,
) -> None:
    formatting = health_adapter.DashboardFormattingSupport()
    assert formatting.render_signal_bar(0, 0) == '[--------]'
    assert formatting.extract_payload_message(None) == '-'
    assert formatting.extract_payload_message({'error': 'e'}) == 'e'
    assert formatting.extract_payload_message({}) == '-'
    empty_lines = formatting.build_empty_lines(
        summary_label='风险热区',
        summary_value='0 个',
        detail='无',
    )
    assert any('风险热区: 0 个' in line for line in empty_lines)

    compressor = health_adapter.DashboardPanelCompressor(formatting)
    compact = compressor.compact_panel_lines(
        ['a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7', 'a8', 'a9']
    )
    assert len(compact) == health_adapter.DASHBOARD_PANEL_MAX_LINES
    assert compact[-1] == health_adapter.DASHBOARD_PANEL_MORE_HINT
    compact_trim = compressor.compact_panel_lines(
        ['a1', 'a2', 'a3', 'a4', 'a5', 'a6', '', 'a8', 'a9', 'a10']
    )
    assert compact_trim[-1] == health_adapter.DASHBOARD_PANEL_MORE_HINT
    assert compressor.compact_panel_lines(['keep', '', '']) == ['keep']

    panels = health_adapter.DashboardPanelBuilder(formatting)
    assert panels.build_app_env_panel('dev', None, None).status == 'fail'
    assert panels.build_health_panel(None).status == 'fail'
    assert panels.build_cache_panel(None).status == 'fail'
    assert panels.build_dependency_panel(None).status == 'fail'
    assert panels.build_server_info_panel(None).status == 'fail'

    redis_entry = panels.build_recommended_entry_panel(
        {'database': {'ok': True}, 'redis': {'ok': False}, 'crypto': {'ok': True}},
        {'currentRevision': 'abc'},
        {'dbSize': 3},
    )
    assert redis_entry.status == 'fail'
    assert any('缓存' in line for line in redis_entry.lines)

    crypto_entry = panels.build_recommended_entry_panel(
        {'database': {'ok': True}, 'redis': {'ok': True}, 'crypto': {'ok': False}},
        {'currentRevision': 'abc'},
        {'dbSize': 3},
    )
    assert crypto_entry.status == 'warn'

    redis_conclusion = panels.build_inspection_conclusion_panel(
        {'database': {'ok': True}, 'redis': {'ok': False}, 'crypto': {'ok': True}},
        {'currentRevision': 'r1'},
        {'dbSize': 1},
    )
    assert redis_conclusion.status == 'fail'
    assert '缓存服务存在异常' in redis_conclusion.lines[1]

    crypto_conclusion = panels.build_inspection_conclusion_panel(
        {'database': {'ok': True}, 'redis': {'ok': True}, 'crypto': {'ok': False}},
        {'currentRevision': 'r1'},
        {'dbSize': 1},
    )
    assert crypto_conclusion.status == 'warn'

    empty_heat = panels.build_risk_heatmap_panel([])
    assert any('0 个' in line for line in empty_heat.lines)


# ---------------------------------------------------------------------------
# database adapter
# ---------------------------------------------------------------------------


def test_database_section_failure_and_overview_warn(
    database_adapter: ModuleType,
) -> None:
    builder = database_adapter.DATABASE_DETAIL_ADAPTER.section_builder
    assert builder.build_revision_section(None).status == 'fail'
    assert builder.build_profile_section({'ok': True}).status == 'fail'
    assert builder.build_check_section({'ok': False}).status == 'fail'
    assert builder.build_history_section(None).status == 'fail'

    overview_fail = builder.build_overview_section(
        {'ok': False},
        {'ok': False},
        {'ok': True, 'items': [{'revision': 'a'}]},
        {'ok': True, 'items': []},
    )
    assert overview_fail.status == 'fail'

    overview_warn = builder.build_overview_section(
        {'ok': True, 'currentRevision': 'r'},
        {'ok': True},
        {'ok': True, 'items': [{'revision': 'a'}, {'revision': 'b'}]},
        {'ok': True, 'items': []},
    )
    assert overview_warn.status == 'warn'


# ---------------------------------------------------------------------------
# jobs adapter
# ---------------------------------------------------------------------------


def test_jobs_rendering_filters_overview_and_empty_records(
    monkeypatch: MonkeyPatch,
    jobs_adapter: ModuleType,
) -> None:
    rendering = jobs_adapter.JOBS_BROWSER_ADAPTER.rendering
    assert rendering.render_job_status('0') == '正常'
    assert rendering.render_job_status('1') == '暂停'
    assert rendering.render_job_status('') == '-'
    assert rendering.render_job_log_status('1') == '失败'
    assert rendering.render_job_log_status('') == '-'
    assert rendering.render_job_log_timeline_title({'jobLogId': 9, 'status': '0'}) == '日志 9 · 成功'
    assert rendering.render_signal_bar(1, 0) == '[--------]'

    row_filter = jobs_adapter.JOBS_BROWSER_ADAPTER.row_filter
    rows = [
        {'jobName': 'ok-job', 'status': '0', 'jobGroup': 'DEFAULT'},
        {'jobName': 'paused-job', 'status': '1', 'jobGroup': 'DEFAULT'},
        {'jobName': 'failed-job', 'status': '0', 'jobGroup': 'SYS'},
    ]
    assert len(row_filter.apply_job_filter(rows, {'failed-job'}, 'failed')) == 1
    assert len(row_filter.apply_job_filter(rows, set(), 'paused')) == 1
    assert len(row_filter.apply_job_filter(rows, {'failed-job'}, 'ok')) == 1

    adapter = jobs_adapter.JOBS_BROWSER_ADAPTER
    overview_paused = adapter.section_builder.build_jobs_overview_section(
        rows,
        rows,
        set(),
        1,
        {'ok': True, 'page': {'rows': []}},
        '全部',
    )
    assert overview_paused.status == 'warn'
    assert '暂停任务' in overview_paused.lines[1]

    assert adapter.section_builder.build_job_focus_section(None).status == 'fail'
    assert adapter.section_builder.build_job_schedule_section({'ok': True}).status == 'fail'
    assert adapter.section_builder.build_job_logs_section({'ok': False}, title='最近执行').status == 'fail'
    assert adapter.section_builder.build_job_log_summary_section(None, None).status == 'fail'

    def fake_jobs(*arguments: str, parse_json: bool = False) -> SimpleNamespace:
        del parse_json
        if arguments[0:2] == ('job', 'list'):
            return SimpleNamespace(
                payload={
                    'ok': True,
                    'page': {
                        'rows': [
                            {
                                'jobId': 1,
                                'jobName': 'alpha',
                                'jobGroup': 'DEFAULT',
                                'status': '0',
                            }
                        ]
                    },
                }
            )
        if arguments[0:2] == ('job', 'logs'):
            return SimpleNamespace(payload={'ok': True, 'page': {'rows': []}})
        return SimpleNamespace(payload={'ok': True, 'page': {'rows': []}})

    monkeypatch.setattr(jobs_adapter.NESTED_CLI_SUPPORT, 'run', fake_jobs)
    empty = adapter.collect_snapshot('dev', query='zzz')
    assert empty.records[0].key == 'job:none'


# ---------------------------------------------------------------------------
# configs adapter
# ---------------------------------------------------------------------------


def test_configs_overview_consistency_source_and_empty(
    monkeypatch: MonkeyPatch,
    configs_adapter: ModuleType,
) -> None:
    adapter = configs_adapter.CONFIGS_BROWSER_ADAPTER
    builder = adapter.section_builder

    drift_overview = builder.build_configs_overview_section(
        [{'configKey': 'a'}],
        [],
        {'mismatch': set(), 'missing-cache': {'a'}, 'orphan-cache': set()},
        '全部',
    )
    assert drift_overview.status == 'warn'
    assert '缓存漂移' in drift_overview.lines[1]

    assert builder.build_config_consistency_section(None).status == 'fail'
    db_only = builder.build_config_consistency_section(
        {'ok': True, 'key': 'k', 'source': 'database', 'inSync': False}
    )
    assert db_only.status == 'warn'
    cache_only = builder.build_config_consistency_section(
        {'ok': True, 'key': 'k', 'source': 'cache', 'inSync': False}
    )
    assert cache_only.status == 'warn'
    both_mismatch = builder.build_config_consistency_section(
        {'ok': True, 'key': 'k', 'source': 'both', 'inSync': False}
    )
    assert both_mismatch.status == 'fail'

    missing_source = builder.build_config_source_section('数据库值', None, missing_text='缺失')
    assert missing_source.status == 'info'

    def fake_configs(*arguments: str, parse_json: bool = False) -> SimpleNamespace:
        del parse_json
        if arguments[0:2] == ('config', 'list'):
            return SimpleNamespace(
                payload={
                    'ok': True,
                    'page': {'rows': [{'configKey': 'sys.name', 'configValue': 'x'}]},
                }
            )
        if arguments[0:2] == ('config', 'doctor'):
            return SimpleNamespace(
                payload={
                    'ok': False,
                    'message': 'doctor down',
                    'mismatchCount': 0,
                    'missingInCacheCount': 0,
                    'orphanInCacheCount': 0,
                    'mismatch': [],
                    'missingInCache': [],
                    'orphanInCache': [],
                }
            )
        return SimpleNamespace(payload={'ok': True})

    monkeypatch.setattr(configs_adapter.NESTED_CLI_SUPPORT, 'run', fake_configs)
    snap = adapter.collect_snapshot('dev', query='nope')
    assert snap.records[0].key == 'config:none'
    assert 'doctor down' in snap.subtitle
