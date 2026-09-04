"""Raise gen runtime coverage toward 99%."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cli.exit_codes import ARGUMENT_ERROR, DATABASE_ERROR, RUNTIME_ERROR
from cli.runtime.gen import GenRuntimeService
from cli.runtime.gen.gateway import GenInfrastructureGateway
from cli.runtime.gen.support import GenDomainSupport

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _runtime_boost_helpers import (  # noqa: E402
    FakePageModel,
    FakeSessionFactory,
    ServiceExc,
    make_dump_model,
    patch_gateway,
)


class FakeGenVo:
    class GenTablePageQueryModel:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs


class FakeUserVo:
    class CurrentUserModel:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class UserInfoModel:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs


class FakeCreate:
    pass


class FakeDrop:
    pass


class FakeTable:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeSqlglot:
    def __init__(self, statements: list[Any] | None = None) -> None:
        self.statements = statements or []

    def parse(self, sql: str, dialect: str | None = None) -> list[Any]:
        del sql, dialect
        return self.statements


class FakeExprModule:
    Create = FakeCreate
    Add = type('Add', (), {})
    Alter = type('Alter', (), {})
    Delete = type('Delete', (), {})
    Drop = FakeDrop
    Insert = type('Insert', (), {})
    TruncateTable = type('TruncateTable', (), {})
    Update = type('Update', (), {})
    Table = FakeTable


def _wire_gen_gateway(
    gateway: GenInfrastructureGateway,
    *,
    gen_table_service: Any,
    gen_table_column_service: Any | None = None,
    page_model: type = FakePageModel,
    raise_service_exc: bool = True,
) -> None:
    patch_gateway(
        gateway,
        get_async_session_local=lambda: FakeSessionFactory(),
        get_gen_table_service=lambda: gen_table_service,
        get_gen_table_column_service=lambda: gen_table_column_service or SimpleNamespace(),
        get_service_exception_class=lambda: ServiceExc if raise_service_exc else type('X', (Exception,), {}),
        get_gen_vo_module=lambda: FakeGenVo,
        get_user_vo_module=lambda: FakeUserVo,
        get_page_model=lambda: page_model,
        get_gen_config=lambda: SimpleNamespace(allow_overwrite=True, GEN_PATH='/tmp/gen'),
        get_database_config=lambda: SimpleNamespace(sqlglot_parse_dialect='mysql'),
        get_sqlglot_module=lambda: FakeSqlglot(),
        get_sqlglot_expressions_module=lambda: FakeExprModule,
    )


def test_gen_support_build_cli_current_user_and_serialize() -> None:
    gateway = GenInfrastructureGateway()
    support = GenDomainSupport(gateway)
    patch_gateway(gateway, get_user_vo_module=lambda: FakeUserVo)

    user = support.build_cli_current_user()
    assert user.kwargs['roles'] == ['admin']
    assert user.kwargs['user'].kwargs['user_id'] == 1

    dumped = support.serialize_gen_item(make_dump_model({'tableName': 't1'}))
    assert dumped == {'tableName': 't1'}
    assert support.serialize_gen_item({'a': 1}) == {'a': 1}
    assert support.serialize_gen_items([{'a': 1}]) == [{'a': 1}]


def test_gen_support_parse_create_table_sql_paths() -> None:
    gateway = GenInfrastructureGateway()
    support = GenDomainSupport(gateway)

    class Stmt(FakeCreate):
        def find(self, table_cls: type) -> FakeTable:
            del table_cls
            return FakeTable('demo')

    patch_gateway(
        gateway,
        get_sqlglot_module=lambda: FakeSqlglot([Stmt()]),
        get_sqlglot_expressions_module=lambda: FakeExprModule,
        get_database_config=lambda: SimpleNamespace(sqlglot_parse_dialect='mysql'),
    )
    statements, names = support.parse_create_table_sql('CREATE TABLE demo(id int);')
    assert names == ['demo']
    assert statements

    patch_gateway(gateway, get_sqlglot_module=lambda: FakeSqlglot([FakeDrop()]))
    try:
        support.parse_create_table_sql('DROP TABLE demo;')
    except ValueError as exc:
        assert 'CREATE TABLE' in str(exc) or '??' in str(exc)
    else:
        raise AssertionError('expected ValueError')

    patch_gateway(gateway, get_sqlglot_module=lambda: FakeSqlglot([]))
    try:
        support.parse_create_table_sql('SELECT 1')
    except ValueError as exc:
        assert 'CREATE TABLE' in str(exc) or '??' in str(exc)
    else:
        raise AssertionError('expected ValueError')

    class FlipCreateMeta(type):
        calls = 0

        def __instancecheck__(cls, instance: object) -> bool:
            FlipCreateMeta.calls += 1
            return FlipCreateMeta.calls == 1

    class FlipCreate(metaclass=FlipCreateMeta):
        pass

    class FlipExpr(FakeExprModule):
        Create = FlipCreate

    FlipCreateMeta.calls = 0
    patch_gateway(
        gateway,
        get_sqlglot_module=lambda: FakeSqlglot([object()]),
        get_sqlglot_expressions_module=lambda: FlipExpr,
    )
    try:
        support.parse_create_table_sql('CREATE TABLE x(id int);')
    except ValueError:
        pass
    else:
        raise AssertionError('expected ValueError for missing table names')


def test_gen_support_resolve_sql_file_and_list_payload(tmp_path: Path) -> None:
    gateway = GenInfrastructureGateway()
    support = GenDomainSupport(gateway)
    sql_file = tmp_path / 'demo.sql'
    sql_file.write_text(' CREATE TABLE t(id int); ', encoding='utf-8')
    assert support.resolve_sql_text('', str(sql_file)) == 'CREATE TABLE t(id int);'

    missing = tmp_path / 'missing.sql'
    try:
        support.resolve_sql_text('', str(missing))
    except ValueError as exc:
        assert 'SQL' in str(exc)
    else:
        raise AssertionError('expected ValueError')

    patch_gateway(gateway, get_page_model=lambda: FakePageModel)
    page = FakePageModel([make_dump_model({'tableName': 't'})])
    paged = support.build_list_payload(page, filters={'paged': True}, paged=True)
    assert paged['ok'] is True
    assert paged['page']['total'] == 1

    listed = support.build_list_payload([{'tableName': 't'}], filters={}, paged=False)
    assert listed['count'] == 1


@pytest.mark.asyncio
async def test_gen_import_tables_dry_run_and_success() -> None:
    gateway = GenInfrastructureGateway()
    service = GenRuntimeService(infrastructure_gateway=gateway)

    class FakeGenTableService:
        @staticmethod
        async def get_gen_db_table_list_by_name_services(session: Any, names: list[str]) -> list[Any]:
            del session
            return [SimpleNamespace(table_name=names[0])]

        @staticmethod
        async def import_gen_table_services(session: Any, tables: list[Any], user: Any) -> Any:
            del session, tables
            assert user.kwargs['roles'] == ['admin']
            return SimpleNamespace(is_success=True, message='imported')

    _wire_gen_gateway(gateway, gen_table_service=FakeGenTableService())
    patch_gateway(gateway, get_user_vo_module=lambda: FakeUserVo)

    dry = await service.import_tables(['sys_user', 'missing'], dry_run=True)
    assert dry['ok'] is True
    assert dry['matchedTables'] == ['sys_user']
    assert dry['missingTables'] == ['missing']

    ok = await service.import_tables(['sys_user'])
    assert ok['ok'] is True
    assert ok['message'] == 'imported'


@pytest.mark.asyncio
async def test_gen_import_tables_exception_paths() -> None:
    gateway = GenInfrastructureGateway()
    service = GenRuntimeService(infrastructure_gateway=gateway)

    class BoomService:
        @staticmethod
        async def get_gen_db_table_list_by_name_services(session: Any, names: list[str]) -> list[Any]:
            del session, names
            raise ServiceExc('svc')

    _wire_gen_gateway(gateway, gen_table_service=BoomService())
    payload = await service.import_tables(['t1'])
    assert payload['exit_code'] == DATABASE_ERROR

    class GenericBoom:
        @staticmethod
        async def get_gen_db_table_list_by_name_services(session: Any, names: list[str]) -> list[Any]:
            del session, names
            raise RuntimeError('generic')

    _wire_gen_gateway(gateway, gen_table_service=GenericBoom())
    payload2 = await service.import_tables(['t1'])
    assert payload2['exit_code'] == DATABASE_ERROR


@pytest.mark.asyncio
async def test_gen_list_tables_success_and_error() -> None:
    gateway = GenInfrastructureGateway()
    service = GenRuntimeService(infrastructure_gateway=gateway)

    class FakeGenTableService:
        @staticmethod
        async def get_gen_table_list_services(session: Any, query: Any, is_page: bool = False) -> list[Any]:
            del session, query, is_page
            return [{'tableName': 't1'}]

        @staticmethod
        async def get_gen_db_table_list_services(session: Any, query: Any, is_page: bool = False) -> list[Any]:
            del session, query, is_page
            return [{'tableName': 'db1'}]

    _wire_gen_gateway(gateway, gen_table_service=FakeGenTableService())
    listed = await service.list_gen_tables(table_name='t')
    assert listed['ok'] is True
    assert listed['count'] == 1

    db_listed = await service.list_gen_db_tables(table_comment='c')
    assert db_listed['items'][0]['tableName'] == 'db1'

    class Boom:
        @staticmethod
        async def get_gen_table_list_services(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError('list fail')

        @staticmethod
        async def get_gen_db_table_list_services(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError('db list fail')

    _wire_gen_gateway(gateway, gen_table_service=Boom())
    assert (await service.list_gen_tables())['exit_code'] == DATABASE_ERROR
    assert (await service.list_gen_db_tables())['exit_code'] == DATABASE_ERROR


@pytest.mark.asyncio
async def test_gen_create_tables_paths() -> None:
    gateway = GenInfrastructureGateway()
    support = GenDomainSupport(gateway)
    service = GenRuntimeService(infrastructure_gateway=gateway, domain_support=support)

    class Stmt(FakeCreate):
        def find(self, table_cls: type) -> FakeTable:
            del table_cls
            return FakeTable('demo')

    class FakeGenTableService:
        @staticmethod
        async def create_table_services(session: Any, sql: str, user: Any) -> Any:
            del session, sql, user
            return SimpleNamespace(is_success=True, message='created')

    _wire_gen_gateway(gateway, gen_table_service=FakeGenTableService())
    patch_gateway(
        gateway,
        get_sqlglot_module=lambda: FakeSqlglot([Stmt()]),
        get_user_vo_module=lambda: FakeUserVo,
    )

    dry = await service.create_tables('CREATE TABLE demo(id int);', '', dry_run=True)
    assert dry['dryRun'] is True
    assert dry['tableNames'] == ['demo']

    ok = await service.create_tables('CREATE TABLE demo(id int);', '')
    assert ok['ok'] is True

    bad = await service.create_tables('', '')
    assert bad['exit_code'] == ARGUMENT_ERROR

    object.__setattr__(support, 'resolve_sql_text', lambda *_a: (_ for _ in ()).throw(RuntimeError('parse boom')))
    boom = await service.create_tables('x', '')
    assert boom['exit_code'] == RUNTIME_ERROR

    object.__setattr__(support, 'resolve_sql_text', lambda sql, sql_file: sql.strip())
    object.__setattr__(support, 'parse_create_table_sql', lambda sql: ([Stmt()], ['demo']))

    class BoomCreate:
        @staticmethod
        async def create_table_services(*_a: Any, **_k: Any) -> Any:
            raise ServiceExc('create fail')

    _wire_gen_gateway(gateway, gen_table_service=BoomCreate())
    patch_gateway(gateway, get_user_vo_module=lambda: FakeUserVo)
    assert (await service.create_tables('CREATE TABLE demo(id int);', ''))['exit_code'] == DATABASE_ERROR

    class GenericCreate:
        @staticmethod
        async def create_table_services(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError('generic')

    _wire_gen_gateway(gateway, gen_table_service=GenericCreate())
    patch_gateway(gateway, get_user_vo_module=lambda: FakeUserVo)
    assert (await service.create_tables('CREATE TABLE demo(id int);', ''))['exit_code'] == DATABASE_ERROR


@pytest.mark.asyncio
async def test_gen_preview_and_detail() -> None:
    gateway = GenInfrastructureGateway()
    service = GenRuntimeService(infrastructure_gateway=gateway)

    class FakeGenTableService:
        @staticmethod
        async def preview_code_services(session: Any, table_id: int) -> dict[str, str]:
            del session
            assert table_id == 1
            return {'a.py': 'code'}

        @staticmethod
        async def get_gen_table_by_id_services(session: Any, table_id: int) -> Any:
            del session
            if table_id == 99:
                return SimpleNamespace(table_id=None)
            return SimpleNamespace(
                table_id=table_id,
                model_dump=lambda *, by_alias=False, exclude_none=False: {
                    'tableId': table_id,
                    'tableName': 'sys_user',
                },
            )

        @staticmethod
        async def get_gen_table_all_services(session: Any) -> list[Any]:
            del session
            return [make_dump_model({'tableId': 1, 'tableName': 'sys_user'})]

    class FakeColumnService:
        @staticmethod
        async def get_gen_table_column_list_by_table_id_services(session: Any, table_id: int) -> list[Any]:
            del session, table_id
            return [make_dump_model({'columnName': 'id'})]

    _wire_gen_gateway(
        gateway,
        gen_table_service=FakeGenTableService(),
        gen_table_column_service=FakeColumnService(),
    )

    preview = await service.preview_code(1)
    assert preview['ok'] is True
    assert preview['templateCount'] == 1

    detail = await service.get_gen_table_detail(1)
    assert detail['ok'] is True
    assert detail['columnCount'] == 1

    missing = await service.get_gen_table_detail(99)
    assert missing['exit_code'] == RUNTIME_ERROR

    class BoomPreview:
        @staticmethod
        async def preview_code_services(*_a: Any, **_k: Any) -> Any:
            raise ServiceExc('preview')

        @staticmethod
        async def get_gen_table_by_id_services(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError('detail boom')

    _wire_gen_gateway(gateway, gen_table_service=BoomPreview())
    assert (await service.preview_code(1))['exit_code'] == DATABASE_ERROR
    assert (await service.get_gen_table_detail(1))['exit_code'] == DATABASE_ERROR

    class GenericPreview:
        @staticmethod
        async def preview_code_services(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError('generic')

    _wire_gen_gateway(gateway, gen_table_service=GenericPreview())
    assert (await service.preview_code(1))['exit_code'] == DATABASE_ERROR


@pytest.mark.asyncio
async def test_gen_export_code_paths(tmp_path: Path) -> None:
    gateway = GenInfrastructureGateway()
    service = GenRuntimeService(infrastructure_gateway=gateway)

    class FakeGenTableService:
        @staticmethod
        async def batch_gen_code_services(session: Any, names: list[str]) -> bytes:
            del session, names
            return b'ZIPDATA'

        @staticmethod
        async def generate_code_services(session: Any, table_name: str) -> Any:
            del session
            return SimpleNamespace(is_success=True, message=f'ok:{table_name}')

    _wire_gen_gateway(gateway, gen_table_service=FakeGenTableService())

    empty = await service.export_code([])
    assert empty['exit_code'] == ARGUMENT_ERROR
    bad_mode = await service.export_code(['t'], mode='rar')
    assert bad_mode['exit_code'] == ARGUMENT_ERROR

    patch_gateway(gateway, get_gen_config=lambda: SimpleNamespace(allow_overwrite=False, GEN_PATH='/tmp/gen'))
    blocked = await service.export_code(['t'], mode='local')
    assert blocked['exit_code'] == RUNTIME_ERROR

    patch_gateway(gateway, get_gen_config=lambda: SimpleNamespace(allow_overwrite=True, GEN_PATH='/tmp/gen'))
    dry_local = await service.export_code(['t'], mode='local', dry_run=True)
    assert dry_local['genPath'] == '/tmp/gen'

    out = tmp_path / 'out' / 'gen.zip'
    zip_ok = await service.export_code(['sys_user'], mode='zip', output_file=str(out))
    assert zip_ok['ok'] is True
    assert out.read_bytes() == b'ZIPDATA'

    local_ok = await service.export_code(['sys_user'], mode='local')
    assert local_ok['ok'] is True
    assert local_ok['results'][0]['ok'] is True

    class BoomZip:
        @staticmethod
        async def batch_gen_code_services(*_a: Any, **_k: Any) -> Any:
            raise ServiceExc('zip fail')

    _wire_gen_gateway(gateway, gen_table_service=BoomZip())
    assert (await service.export_code(['t'], mode='zip'))['exit_code'] == DATABASE_ERROR

    class GenericZip:
        @staticmethod
        async def batch_gen_code_services(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError('generic')

    _wire_gen_gateway(gateway, gen_table_service=GenericZip())
    assert (await service.export_code(['t'], mode='zip'))['exit_code'] == DATABASE_ERROR

    class OkZip:
        @staticmethod
        async def batch_gen_code_services(*_a: Any, **_k: Any) -> bytes:
            return b'x'

    _wire_gen_gateway(gateway, gen_table_service=OkZip())
    object.__setattr__(
        service.domain_support,
        'write_export_zip',
        lambda *_a, **_k: (_ for _ in ()).throw(OSError('disk full')),
    )
    assert (await service.export_code(['t'], mode='zip'))['exit_code'] == RUNTIME_ERROR


@pytest.mark.asyncio
async def test_gen_sync_from_db_paths() -> None:
    gateway = GenInfrastructureGateway()
    service = GenRuntimeService(infrastructure_gateway=gateway)

    class FakeGenTableService:
        @staticmethod
        async def sync_db_services(session: Any, table_name: str) -> Any:
            del session
            return SimpleNamespace(is_success=True, message=f'synced:{table_name}')

    _wire_gen_gateway(gateway, gen_table_service=FakeGenTableService())
    assert (await service.sync_gen_table_from_db(''))['exit_code'] == ARGUMENT_ERROR
    ok = await service.sync_gen_table_from_db(' sys_user ')
    assert ok['ok'] is True

    class Boom:
        @staticmethod
        async def sync_db_services(*_a: Any, **_k: Any) -> Any:
            raise ServiceExc('sync')

    _wire_gen_gateway(gateway, gen_table_service=Boom())
    assert (await service.sync_gen_table_from_db('t'))['exit_code'] == DATABASE_ERROR

    class Generic:
        @staticmethod
        async def sync_db_services(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError('generic')

    _wire_gen_gateway(gateway, gen_table_service=Generic())
    assert (await service.sync_gen_table_from_db('t'))['exit_code'] == DATABASE_ERROR


def test_gen_gateway_lazy_imports() -> None:
    gateway = GenInfrastructureGateway()
    assert gateway.get_sqlglot_module() is not None
    assert gateway.get_sqlglot_expressions_module() is not None
    assert gateway.get_async_session_local() is not None
    assert gateway.get_page_model() is not None
    assert gateway.get_database_config() is not None
    assert gateway.get_gen_config() is not None
    assert issubclass(gateway.get_service_exception_class(), Exception)
    assert gateway.get_user_vo_module() is not None
    assert gateway.get_gen_vo_module() is not None
    assert gateway.get_gen_table_service() is not None
    assert gateway.get_gen_table_column_service() is not None
