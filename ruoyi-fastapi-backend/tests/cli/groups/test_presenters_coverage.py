"""Presenter unit coverage for cli.groups."""

from __future__ import annotations

from cli.groups.app.presenter import AppCommandPresenter
from cli.groups.cache.presenter import CacheCommandPresenter
from cli.groups.config.presenter import ConfigCommandPresenter
from cli.groups.crypto.presenter import CryptoCommandPresenter
from cli.groups.db.presenter import DbCommandPresenter
from cli.groups.dev.presenter import DevCommandPresenter
from cli.groups.gen.presenter import GenCommandPresenter
from cli.groups.job.presenter import JobCommandPresenter
from cli.groups.ops.presenter import OpsCommandPresenter


def test_cache_presenter_covers_all_branches() -> None:
    presenter = CacheCommandPresenter()

    stats_full = presenter.build_cache_stats_text(
        {
            'ok': True,
            'dbSize': 10,
            'info': {
                'redis_version': '7.0',
                'connected_clients': 2,
                'used_memory_human': '1M',
                'uptime_in_seconds': 99,
                'keyspace_hits': 1,
                'keyspace_misses': 0,
            },
            'commandStats': [{'name': 'get', 'value': 3}, 'skip'],
            'cacheNames': [{'cacheName': 'sys', 'remark': '  '}, {'cacheName': 'x', 'remark': None}],
        }
    )
    assert 'command_stats_top10:' in stats_full
    assert 'cache_name_samples:' in stats_full

    stats_empty = presenter.build_cache_stats_text({'ok': False, 'dbSize': 0})
    assert 'command_stats_top10: none' in stats_empty
    assert 'cache_names: 0' in stats_empty

    assert 'keys: none' in presenter.build_cache_keys_text({'ok': True, 'cacheName': 'a', 'count': 0})
    assert '- k1' in presenter.build_cache_keys_text({'ok': True, 'cacheName': 'a', 'count': 1, 'keys': ['k1']})

    empty_value = presenter.build_cache_value_text({'ok': True, 'cacheName': 'a', 'cacheKey': 'b', 'fullCacheKey': 'a:b'})
    assert '  -' in empty_value
    single = presenter.build_cache_value_text(
        {'ok': True, 'cacheName': 'a', 'cacheKey': 'b', 'fullCacheKey': 'a:b', 'cacheValue': 'hello'}
    )
    assert 'hello' in single
    multi = presenter.build_cache_value_text(
        {'ok': True, 'cacheName': 'a', 'cacheKey': 'b', 'fullCacheKey': 'a:b', 'cacheValue': 'line1\nline2'}
    )
    assert '  |' in multi

    ttl = presenter.build_cache_ttl_text(
        {
            'ok': True,
            'cacheName': 'a',
            'cacheKey': 'b',
            'fullCacheKey': 'a:b',
            'message': 'ok',
            'ttlSeconds': 10,
            'persistent': False,
            'expires': True,
        }
    )
    assert 'ttl_seconds: 10' in ttl


def test_app_presenter_covers_all_branches() -> None:
    presenter = AppCommandPresenter()

    assert 'routes: none' in presenter.build_routes_text({'ok': True, 'env': 'dev', 'count': 0})
    filters_none = presenter.build_routes_text(
        {'ok': True, 'env': 'dev', 'count': 0, 'filters': {'pathPrefix': '', 'method': '', 'groupBy': 'none'}}
    )
    assert 'filters: none' in filters_none

    routes_text = presenter.build_routes_text(
        {
            'ok': True,
            'env': 'dev',
            'count': 1,
            'filters': {'pathPrefix': '/api', 'method': 'GET', 'groupBy': 'none', 'includeHidden': True},
            'routes': [{'methods': ['GET'], 'path': '/api/x', 'tags': ['t'], 'summary': 's', 'name': 'n'}],
        }
    )
    assert 'routes:' in routes_text

    grouped = presenter.build_routes_text(
        {
            'ok': True,
            'env': 'dev',
            'count': 1,
            'filters': {'groupBy': 'tag'},
            'groupedRoutes': {
                'alpha': [{'methods': ['POST'], 'path': '/a', 'tags': ['alpha'], 'summary': '', 'name': ''}],
                'beta': 'bad',
            },
        }
    )
    assert 'groups: 2' in grouped
    assert 'groups: none' in presenter.build_routes_text(
        {'ok': True, 'env': 'dev', 'count': 0, 'filters': {'groupBy': 'tag'}, 'groupedRoutes': {}}
    )

    assert 'config: none' in presenter.build_app_config_text({'ok': True, 'env': 'dev'})
    config_text = presenter.build_app_config_text(
        {
            'ok': True,
            'env': 'dev',
            'config': {
                'name': 'app',
                'host': '0.0.0.0',
                'port': 8000,
                'rootPath': '',
                'reload': False,
                'workers': 1,
                'disableSwagger': False,
                'disableRedoc': False,
                'dbType': 'mysql',
                'dbHost': 'h',
                'dbPort': 3306,
                'dbDatabase': 'd',
                'redisHost': 'r',
                'redisPort': 6379,
                'logLevel': 'INFO',
                'transportCryptoEnabled': False,
                'transportCryptoMode': 'off',
            },
        }
    )
    assert 'application:' in config_text

    assert 'runtime: none' in presenter.build_app_env_text({'ok': True, 'env': 'dev'})
    env_text = presenter.build_app_env_text(
        {
            'ok': True,
            'env': 'dev',
            'runtime': {
                'cliEnv': 'dev',
                'configEnv': 'dev',
                'appEnv': 'dev',
                'envFile': '.env.dev',
                'envFileExists': True,
                'backendDir': '/tmp',
                'pythonExecutable': 'python',
            },
        }
    )
    assert 'runtime:' in env_text

    doctor = presenter.build_doctor_text(
        {
            'ok': False,
            'env': 'dev',
            'database': {'ok': False, 'message': 'down', 'error': 'boom'},
            'redis': {'ok': True, 'message': 'up'},
            'crypto': None,
        }
    )
    assert 'database: false' in doctor
    assert 'crypto: unknown' in doctor


def test_ops_presenter_covers_all_branches() -> None:
    presenter = OpsCommandPresenter()

    health = presenter.build_health_text(
        {
            'ok': False,
            'env': 'dev',
            'database': None,
            'redis': {'ok': False, 'message': 'x', 'error': 'e'},
        }
    )
    assert 'database: unknown' in health

    assert 'server: none' in presenter.build_server_info_text({'ok': True})
    server = presenter.build_server_info_text(
        {
            'ok': True,
            'server': {
                'sys': {
                    'computerName': 'n',
                    'computerIp': '1.1.1.1',
                    'osName': 'Windows',
                    'osArch': 'amd64',
                    'userDir': '/u',
                },
                'cpu': {'cpuNum': 8, 'used': 1, 'sys': 2, 'free': 97},
                'mem': {'total': '16G', 'used': '8G', 'free': '8G', 'usage': 50},
                'py': {
                    'name': 'python',
                    'version': '3.13',
                    'startTime': 't',
                    'runTime': '1h',
                    'home': '/py',
                    'used': '100M',
                    'total': '200M',
                    'usage': 50,
                },
                'sysFiles': [{'dirName': 'C:', 'used': '1', 'total': '2', 'usage': '50%'}, 'skip'],
            },
        }
    )
    assert 'disk_samples:' in server

    deps_empty = presenter.build_dependencies_text({'ok': True, 'message': 'ok', 'includeDev': False})
    assert 'packages: none' in deps_empty
    assert 'missing_required: none' in deps_empty

    deps = presenter.build_dependencies_text(
        {
            'ok': False,
            'message': 'missing',
            'includeDev': True,
            'missingRequired': ['typer'],
            'packages': {
                'typer': {'installed': False, 'version': None, 'required': True, 'distribution': ''},
                'bad': None,
            },
        }
    )
    assert 'missing_required:' in deps
    assert 'typer: false' in deps
    assert presenter._build_dependency_line('bad', None) == '  bad: not-installed'


def test_db_presenter_covers_all_branches() -> None:
    presenter = DbCommandPresenter()
    assert 'current_revision: abc' in presenter.build_current_revision_text(
        {'ok': True, 'env': 'dev', 'currentRevision': 'abc'}
    )

    empty = presenter.build_alembic_revisions_text({'ok': True, 'env': 'dev', 'message': 'm', 'count': 0})
    assert 'items: none' in empty

    filled = presenter.build_alembic_revisions_text(
        {
            'ok': True,
            'env': 'dev',
            'message': 'm',
            'count': 1,
            'totalCount': 2,
            'limit': 1,
            'items': [
                {
                    'revision': 'r1',
                    'downRevisions': ['r0'],
                    'branchLabels': ['main'],
                    'dependsOn': [],
                    'doc': '',
                    'path': 'x.py',
                },
                'skip',
            ],
        }
    )
    assert 'total_count: 2' in filled
    assert 'down_revisions: r0' in filled


def test_dev_presenter_covers_all_branches() -> None:
    presenter = DevCommandPresenter()

    lint_none = presenter.build_dev_lint_text({'ok': True, 'env': 'dev'})
    assert 'targets: none' in lint_none
    assert 'format: none' in lint_none

    lint = presenter.build_dev_lint_text(
        {
            'ok': True,
            'env': 'dev',
            'checkOnly': False,
            'fix': True,
            'unsafeFixes': False,
            'targets': ['cli'],
            'format': {
                'ok': True,
                'returnCode': 0,
                'command': ['ruff', 'format'],
                'stdout': 'ok\nline',
                'stderr': 'warn',
            },
            'check': {'ok': True, 'returnCode': 0, 'command': 'not-a-list'},
        }
    )
    assert 'targets:' in lint
    assert 'stdout:' in lint
    assert 'command: -' in lint

    test_text = presenter.build_dev_test_text(
        {
            'ok': False,
            'env': 'dev',
            'keyword': '',
            'maxfail': 0,
            'quiet': True,
            'targets': None,
            'test': {'ok': False, 'returnCode': 1, 'command': []},
        }
    )
    assert 'targets: none' in test_text
    assert 'keyword: -' in test_text

    test_with_targets = presenter.build_dev_test_text(
        {
            'ok': True,
            'env': 'dev',
            'keyword': 'k',
            'maxfail': 1,
            'quiet': False,
            'targets': ['tests/cli'],
            'test': {'ok': True, 'returnCode': 0, 'command': ['pytest']},
        }
    )
    assert '  - tests/cli' in test_with_targets


def test_crypto_presenter_covers_all_branches() -> None:
    presenter = CryptoCommandPresenter()

    keygen_empty = presenter.build_crypto_keygen_text({'ok': True, 'env': 'dev', 'kid': 'k', 'keySize': 2048})
    assert 'env_patch_keys: none' in keygen_empty
    assert 'public_key: -' in keygen_empty

    keygen = presenter.build_crypto_keygen_text(
        {
            'ok': True,
            'env': 'dev',
            'kid': 'k',
            'keySize': 2048,
            'publicKey': 'PUB\nKEY',
            'privateKey': 'PRIV',
            'envPatch': {'A': '1', 'B': '2'},
        }
    )
    assert 'env_patch_keys:' in keygen
    assert 'public_key:' in keygen

    assert 'public_key: none' in presenter.build_export_public_text({'ok': True, 'env': 'dev'})
    export_empty_kids = presenter.build_export_public_text(
        {
            'ok': True,
            'env': 'dev',
            'publicKey': {
                'kid': 'default',
                'alg': 'RSA',
                'envelopeVersion': 1,
                'expireAt': '-',
                'supportedKids': [],
                'publicKey': None,
            },
        }
    )
    assert 'supported_kids: none' in export_empty_kids

    export = presenter.build_export_public_text(
        {
            'ok': True,
            'env': 'dev',
            'publicKey': {
                'kid': 'default',
                'alg': 'RSA',
                'envelopeVersion': 1,
                'expireAt': '-',
                'supportedKids': ['default'],
                'publicKey': 'PEM',
            },
        }
    )
    assert 'supported_kids:' in export


def test_config_presenter_covers_all_branches() -> None:
    presenter = ConfigCommandPresenter()

    empty_filters = presenter.build_config_list_text({'ok': True, 'env': 'dev', 'filters': {'configName': ''}, 'count': 0})
    assert 'filters: none' in empty_filters
    assert 'configs: none' in empty_filters

    paged_empty = presenter.build_config_list_text(
        {
            'ok': True,
            'env': 'dev',
            'filters': {'configName': 'x'},
            'page': {'pageNum': 1, 'pages': 1, 'pageSize': 20, 'total': 0, 'rows': []},
        }
    )
    assert 'configs: none' in paged_empty

    paged = presenter.build_config_list_text(
        {
            'ok': True,
            'env': 'dev',
            'page': {
                'pageNum': 1,
                'pages': 1,
                'pageSize': 20,
                'total': 1,
                'rows': [
                    {
                        'configId': 1,
                        'configKey': 'k',
                        'configName': 'n',
                        'configType': 'N',
                        'configValue': 'v',
                        'remark': '',
                    },
                    'skip',
                ],
            },
        }
    )
    assert 'configs:' in paged

    items = presenter.build_config_list_text(
        {
            'ok': True,
            'env': 'dev',
            'count': 1,
            'items': [{'configId': 2, 'configKey': 'k2', 'configName': 'n2', 'configType': 'Y', 'configValue': 'v2'}],
        }
    )
    assert '[2]' in items

    get_both = presenter.build_config_get_text(
        {
            'ok': True,
            'env': 'dev',
            'key': 'k',
            'source': 'both',
            'inSync': True,
            'database': {
                'configId': 1,
                'configKey': 'k',
                'configName': 'n',
                'configValue': 'v',
                'configType': 'N',
                'remark': 'r',
            },
            'cache': None,
        }
    )
    assert 'in_sync: true' in get_both
    assert 'cache: none' in get_both

    doctor = presenter.build_config_doctor_text(
        {
            'ok': False,
            'env': 'dev',
            'message': 'drift',
            'databaseCount': 1,
            'cacheCount': 1,
            'missingInCacheCount': 1,
            'orphanInCacheCount': 0,
            'mismatchCount': 1,
            'sampleLimit': 10,
            'missingInCache': ['a'],
            'orphanInCache': [],
            'mismatchKeys': ['b'],
        }
    )
    assert 'missing_in_cache:' in doctor
    assert 'orphan_in_cache: none' in doctor


def test_job_presenter_covers_all_branches() -> None:
    presenter = JobCommandPresenter()

    empty = presenter.build_job_list_text({'ok': True, 'filters': {'jobName': ''}, 'count': 0})
    assert 'filters: none' in empty
    assert 'jobs: none' in empty

    paged_empty = presenter.build_job_list_text(
        {'ok': True, 'filters': {'jobName': 'x'}, 'page': {'pageNum': 1, 'pages': 1, 'pageSize': 10, 'total': 0, 'rows': None}}
    )
    assert 'jobs: none' in paged_empty

    paged = presenter.build_job_list_text(
        {
            'ok': True,
            'page': {
                'pageNum': 1,
                'pages': 1,
                'pageSize': 10,
                'total': 1,
                'rows': [
                    {
                        'jobId': 1,
                        'jobName': 'j',
                        'jobGroup': 'g',
                        'status': '0',
                        'cronExpression': '* * * * *',
                        'invokeTarget': 't',
                        'jobExecutor': 'e',
                    }
                ],
            },
        }
    )
    assert 'jobs:' in paged

    items = presenter.build_job_list_text(
        {
            'ok': True,
            'count': 1,
            'items': [
                {
                    'jobId': 2,
                    'jobName': 'j2',
                    'jobGroup': 'g',
                    'status': '1',
                    'cronExpression': '',
                    'invokeTarget': '',
                    'jobExecutor': '',
                }
            ],
        }
    )
    assert '[2]' in items

    assert 'job: none' in presenter.build_job_detail_text({'ok': True, 'jobId': 9})
    detail = presenter.build_job_detail_text(
        {
            'ok': True,
            'job': {
                'jobId': 1,
                'jobName': 'n',
                'jobGroup': 'DEFAULT',
                'jobExecutor': 'default',
                'status': '0',
                'cronExpression': '0 0 * * *',
                'invokeTarget': 'mod.fn',
                'jobArgs': '',
                'jobKwargs': '',
                'misfirePolicy': '1',
                'concurrent': '1',
                'remark': '',
                'createBy': 'a',
                'createTime': 't',
                'updateBy': 'b',
                'updateTime': 'u',
            },
        }
    )
    assert 'job_name: n' in detail

    logs_empty = presenter.build_job_logs_text({'ok': True, 'count': 0})
    assert 'logs: none' in logs_empty

    logs_paged = presenter.build_job_logs_text(
        {
            'ok': True,
            'filters': {'status': '0'},
            'page': {
                'pageNum': 1,
                'pages': 1,
                'pageSize': 10,
                'total': 1,
                'rows': [
                    {
                        'jobLogId': 1,
                        'jobName': 'n',
                        'jobGroup': 'g',
                        'status': '0',
                        'jobTrigger': 't',
                        'jobMessage': 'm',
                        'exceptionInfo': '',
                        'createTime': 'now',
                    }
                ],
            },
        }
    )
    assert 'logs:' in logs_paged

    logs_items = presenter.build_job_logs_text(
        {
            'ok': True,
            'count': 1,
            'items': [
                {
                    'jobLogId': 2,
                    'jobName': 'n',
                    'jobGroup': 'g',
                    'status': '1',
                    'jobTrigger': '',
                    'jobMessage': '',
                    'exceptionInfo': 'err',
                    'createTime': '-',
                }
            ],
        }
    )
    assert '[2]' in logs_items

    logs_paged_empty = presenter.build_job_logs_text(
        {'ok': True, 'page': {'pageNum': 1, 'pages': 1, 'pageSize': 10, 'total': 0, 'rows': []}}
    )
    assert 'logs: none' in logs_paged_empty


def test_gen_presenter_covers_all_branches() -> None:
    presenter = GenCommandPresenter()

    assert 'templates: none' in presenter.build_gen_preview_text({'ok': True, 'env': 'dev', 'tableId': 1, 'templateCount': 0})
    preview = presenter.build_gen_preview_text(
        {
            'ok': True,
            'env': 'dev',
            'tableId': 1,
            'templateCount': 2,
            'preview': {'a.py': 'print(1)', 'b.py': '  ', 'c.py': None},
        }
    )
    assert 'templates:' in preview
    assert 'b.py: -' in preview

    export_empty = presenter.build_gen_export_text({'ok': True, 'env': 'dev', 'mode': 'zip', 'dryRun': False, 'message': 'm'})
    assert 'table_names: none' in export_empty

    export = presenter.build_gen_export_text(
        {
            'ok': True,
            'env': 'dev',
            'mode': 'zip',
            'dryRun': True,
            'message': 'ok',
            'tableNames': ['t1'],
            'outputFile': 'out.zip',
            'genPath': '/gen',
            'size': 12,
            'results': [{'tableName': 't1', 'ok': True, 'message': 'done'}, 'skip'],
        }
    )
    assert 'output_file: out.zip' in export
    assert 'results:' in export

    list_empty = presenter.build_gen_table_list_text({'ok': True, 'filters': {'tableName': ''}, 'count': 0})
    assert 'items: none' in list_empty

    list_paged = presenter.build_gen_table_list_text(
        {
            'ok': True,
            'filters': {'tableName': 'sys'},
            'page': {
                'pageNum': 1,
                'pages': 1,
                'pageSize': 10,
                'total': 1,
                'rows': [
                    {
                        'tableId': 1,
                        'tableName': 'sys_user',
                        'tableComment': 'u',
                        'className': 'SysUser',
                        'tplCategory': 'crud',
                        'moduleName': 'system',
                        'businessName': 'user',
                        'functionName': '用户',
                    }
                ],
            },
        },
        db_mode=False,
    )
    assert 'items:' in list_paged

    list_paged_empty = presenter.build_gen_table_list_text(
        {'ok': True, 'page': {'pageNum': 1, 'pages': 1, 'pageSize': 10, 'total': 0, 'rows': []}},
        db_mode=True,
    )
    assert 'items: none' in list_paged_empty

    db_items = presenter.build_gen_table_list_text(
        {
            'ok': True,
            'count': 1,
            'items': [{'tableName': 't', 'tableComment': 'c', 'createTime': 'a', 'updateTime': 'b'}],
        },
        db_mode=True,
    )
    assert 'create_time: a' in db_items

    assert 'detail: none' in presenter.build_gen_detail_text({'ok': True, 'tableId': 1})
    assert 'info: none' in presenter.build_gen_detail_text({'ok': True, 'tableId': 1, 'detail': {}})
    detail = presenter.build_gen_detail_text(
        {
            'ok': True,
            'tableId': 1,
            'tableName': 'sys_user',
            'columnCount': 2,
            'tableCount': 1,
            'detail': {
                'info': {
                    'tableComment': '用户',
                    'className': 'SysUser',
                    'tplCategory': 'crud',
                    'tplWebType': 'element-plus',
                    'packageName': 'module_admin',
                    'moduleName': 'system',
                    'businessName': 'user',
                    'functionName': '用户',
                    'functionAuthor': 'ruoyi',
                    'genType': '0',
                    'genPath': '/',
                    'remark': '',
                }
            },
        }
    )
    assert 'class_name: SysUser' in detail
