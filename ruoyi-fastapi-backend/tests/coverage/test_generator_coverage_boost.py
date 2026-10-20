"""Raise coverage for module_generator dao/service/vo toward 99%+."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlglot.expressions import Create, Expression

from common.constant import GenConstant
from exceptions.exception import ServiceException
from module_admin.entity.vo.user_vo import CurrentUserModel, UserInfoModel
from module_generator.dao.gen_dao import GenTableColumnDao, GenTableDao
from module_generator.entity.vo.gen_vo import (
    DeleteGenTableColumnModel,
    DeleteGenTableModel,
    EditGenTableModel,
    GenTableBaseModel,
    GenTableColumnBaseModel,
    GenTableColumnModel,
    GenTableColumnPageQueryModel,
    GenTableColumnQueryModel,
    GenTableDbRowModel,
    GenTableDetailModel,
    GenTableModel,
    GenTablePageQueryModel,
    GenTableParamsModel,
    GenTableQueryModel,
    GenTableRowModel,
)
from module_generator.service.gen_service import GenTableColumnService, GenTableService


def _user(name: str = 'admin') -> CurrentUserModel:
    return CurrentUserModel(
        permissions=[],
        roles=[],
        user=UserInfoModel(userId=1, userName=name, deptId=100),
    )


def _column(**kwargs) -> GenTableColumnModel:
    defaults = {
        'columnId': 1,
        'tableId': 1,
        'columnName': 'id',
        'columnComment': 'id',
        'columnType': 'bigint',
        'pythonField': 'id',
        'isPk': '1',
        'isIncrement': '0',
        'isRequired': '1',
        'isUnique': '0',
        'isInsert': '1',
        'isEdit': '1',
        'isList': '1',
        'isQuery': '1',
    }
    defaults.update(kwargs)
    return GenTableColumnModel(**defaults)


def _table(**kwargs) -> GenTableModel:
    defaults = {
        'tableId': 1,
        'tableName': 'sys_demo',
        'tableComment': 'demo',
        'className': 'SysDemo',
        'tplCategory': GenConstant.TPL_CRUD,
        'tplWebType': 'element-plus',
        'packageName': 'module_admin',
        'moduleName': 'demo',
        'businessName': 'demo',
        'functionName': 'Demo',
        'functionAuthor': 'ry',
        'genType': '0',
        'genPath': '/',
        'columns': [_column()],
    }
    defaults.update(kwargs)
    return GenTableModel(**defaults)


# ---------------------------------------------------------------------------
# gen_vo
# ---------------------------------------------------------------------------


def test_gen_vo_validators_and_models() -> None:
    base = GenTableBaseModel(
        tableName='t',
        tableComment='c',
        className='T',
        packageName='p',
        moduleName='m',
        businessName='b',
        functionName='f',
        functionAuthor='a',
    )
    base.validate_fields()
    assert base.get_table_name() == 't'

    col_base = GenTableColumnBaseModel(pythonField='userName')
    col_base.validate_fields()
    assert col_base.get_python_field() == 'userName'

    crud = GenTableModel(tplCategory=GenConstant.TPL_CRUD)
    assert crud.crud is True and crud.tree is False and crud.sub is False
    tree = GenTableModel(tplCategory=GenConstant.TPL_TREE)
    assert tree.tree is True
    sub = GenTableModel(tplCategory=GenConstant.TPL_SUB)
    assert sub.sub is True

    col = _column(pythonField='parentId', isPk='0', isIncrement='1', isRequired='0')
    assert col.cap_python_field == 'ParentId'
    assert col.pk is False
    assert col.increment is True
    assert col.super_column is True or col.usable_column is True

    empty_field = GenTableColumnModel(pythonField=None)
    assert empty_field.cap_python_field is None
    assert empty_field.pk is None or empty_field.pk is False

    GenTableRowModel(tableName='t', columns=[GenTableColumnBaseModel(pythonField='a')])
    GenTableDbRowModel(tableName='t', tableComment='c')
    GenTableParamsModel(treeCode='id', treeParentCode='pid', treeName='name', parentMenuId=1)
    GenTableQueryModel(beginTime='2024-01-01', endTime='2024-01-02')
    GenTablePageQueryModel(pageNum=2, pageSize=5)
    GenTableDetailModel(info=_table(), rows=[_column()], tables=[_table()])
    DeleteGenTableModel(tableIds='1,2')
    GenTableColumnQueryModel(beginTime='a', endTime='b')
    GenTableColumnPageQueryModel(pageNum=1, pageSize=10)
    DeleteGenTableColumnModel(columnIds='1')
    EditGenTableModel(tableId=1, params=GenTableParamsModel(treeCode='x'))


# ---------------------------------------------------------------------------
# gen_dao
# ---------------------------------------------------------------------------


def _exec_result(first=None, all_rows=None, fetchall=None):
    result = MagicMock()
    scalars = MagicMock()
    scalars.first.return_value = first
    scalars.all.return_value = all_rows if all_rows is not None else []
    result.scalars.return_value = scalars
    result.fetchall.return_value = fetchall if fetchall is not None else []
    return result


@pytest.mark.asyncio
async def test_gen_table_dao_crud_and_lists() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_exec_result(first=SimpleNamespace(table_id=1)))
    db.add = MagicMock()
    db.flush = AsyncMock()

    assert await GenTableDao.get_gen_table_by_id(db, 1) is not None
    assert await GenTableDao.get_gen_table_by_name(db, 't') is not None

    db.execute = AsyncMock(return_value=_exec_result(all_rows=[SimpleNamespace(table_id=1)]))
    assert len(await GenTableDao.get_gen_table_all(db)) == 1

    stmt = MagicMock(spec=Expression)
    stmt.sql.return_value = 'create table t(id int)'
    db.execute = AsyncMock()
    await GenTableDao.create_table_by_sql_dao(db, [stmt])
    stmt.sql.assert_called()

    query = GenTablePageQueryModel(
        tableName='Sys',
        tableComment='Demo',
        beginTime='2024-01-01',
        endTime='2024-01-31',
        pageNum=1,
        pageSize=10,
    )
    with patch(
        'module_generator.dao.gen_dao.PageUtil.paginate',
        new=AsyncMock(return_value={'rows': []}),
    ) as paginate:
        await GenTableDao.get_gen_table_list(db, query, is_page=True)
        await GenTableDao.get_gen_table_list(db, GenTablePageQueryModel(), is_page=False)
        assert paginate.await_count == 2

    # db table list mysql / postgresql with filters
    for db_type in ('mysql', 'postgresql'):
        with (
            patch('module_generator.dao.gen_dao.DataBaseConfig.db_type', db_type),
            patch(
                'module_generator.dao.gen_dao.PageUtil.paginate',
                new=AsyncMock(return_value={'rows': []}),
            ),
        ):
            await GenTableDao.get_gen_db_table_list(
                db,
                GenTablePageQueryModel(
                    tableName='t',
                    tableComment='c',
                    beginTime='2024-01-01',
                    endTime='2024-01-02',
                ),
                is_page=True,
            )
            await GenTableDao.get_gen_db_table_list(db, GenTablePageQueryModel(), is_page=False)

    db.execute = AsyncMock(return_value=_exec_result(fetchall=[('t', 'c', None, None)]))
    for db_type in ('mysql', 'postgresql'):
        with patch('module_generator.dao.gen_dao.DataBaseConfig.db_type', db_type):
            rows = await GenTableDao.get_gen_db_table_list_by_names(db, ['t1', 't2'])
            assert rows

    table = _table()
    db.execute = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    with patch('module_generator.dao.gen_dao.GenTable', return_value=SimpleNamespace(table_id=9)) as gt:
        # add uses GenTable(**...) — patch constructor via model dump path instead
        pass
    # real add path: construct GenTable from model — mock GenTable class in module
    with patch('module_generator.dao.gen_dao.GenTable') as GT:
        instance = SimpleNamespace(table_id=9)
        GT.return_value = instance
        GT.side_effect = None
        # GenTableBaseModel still needs real fields; GenTable is only the ORM class
        result = await GenTableDao.add_gen_table_dao(db, table)
        assert result is instance
        db.add.assert_called_once()

    await GenTableDao.edit_gen_table_dao(db, table.model_dump(by_alias=True))
    await GenTableDao.delete_gen_table_dao(db, table)


@pytest.mark.asyncio
async def test_gen_table_column_dao() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_exec_result(all_rows=[SimpleNamespace(column_id=1)]))
    db.add = MagicMock()
    db.flush = AsyncMock()

    cols = await GenTableColumnDao.get_gen_table_column_list_by_table_id(db, 1)
    assert cols

    db.execute = AsyncMock(return_value=_exec_result(fetchall=[('id', '1', '1', 1, 'pk', '0', 'bigint')]))
    for db_type in ('mysql', 'postgresql'):
        with patch('module_generator.dao.gen_dao.DataBaseConfig.db_type', db_type):
            assert await GenTableColumnDao.get_gen_db_table_columns_by_name(db, 'sys_demo')

    col = _column()
    with patch('module_generator.dao.gen_dao.GenTableColumn') as GC:
        instance = SimpleNamespace(column_id=3)
        GC.return_value = instance
        assert await GenTableColumnDao.add_gen_table_column_dao(db, col) is instance

    db.execute = AsyncMock()
    await GenTableColumnDao.edit_gen_table_column_dao(db, col.model_dump(by_alias=True))
    await GenTableColumnDao.delete_gen_table_column_by_table_id_dao(db, col)
    await GenTableColumnDao.delete_gen_table_column_by_column_id_dao(db, col)


# ---------------------------------------------------------------------------
# gen_service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gen_table_service_list_and_import_edit_delete() -> None:
    db = AsyncMock()
    query = GenTablePageQueryModel()

    with patch.object(GenTableDao, 'get_gen_table_list', new=AsyncMock(return_value=[])) as m:
        assert await GenTableService.get_gen_table_list_services(db, query) == []
        m.assert_awaited()
    with patch.object(GenTableDao, 'get_gen_db_table_list', new=AsyncMock(return_value=[])):
        assert await GenTableService.get_gen_db_table_list_services(db, query) == []

    with (
        patch.object(
            GenTableDao,
            'get_gen_db_table_list_by_names',
            new=AsyncMock(return_value=[SimpleNamespace(table_name='t', table_comment='c')]),
        ),
        patch(
            'module_generator.service.gen_service.CamelCaseUtil.transform_result',
            return_value=[{'tableName': 't', 'tableComment': 'c'}],
        ),
    ):
        tables = await GenTableService.get_gen_db_table_list_by_name_services(db, ['t'])
        assert tables[0].table_name == 't'

    table = _table()
    add_result = SimpleNamespace(table_id=88)
    with (
        patch('module_generator.service.gen_service.GenUtils.init_table') as init_t,
        patch('module_generator.service.gen_service.GenUtils.init_column_field') as init_c,
        patch.object(GenTableDao, 'add_gen_table_dao', new=AsyncMock(return_value=add_result)),
        patch.object(
            GenTableColumnDao,
            'get_gen_db_table_columns_by_name',
            new=AsyncMock(return_value=[SimpleNamespace()]),
        ),
        patch(
            'module_generator.service.gen_service.CamelCaseUtil.transform_result',
            return_value=[{'columnName': 'id', 'pythonField': 'id', 'isPk': '1'}],
        ),
        patch.object(GenTableColumnDao, 'add_gen_table_column_dao', new=AsyncMock()),
    ):
        result = await GenTableService.import_gen_table_services(db, [table], _user())
        assert result.is_success is True
        init_t.assert_called()
        init_c.assert_called()
        db.commit.assert_awaited()

    with (
        patch.object(GenTableDao, 'add_gen_table_dao', new=AsyncMock(side_effect=RuntimeError('fail'))),
        patch('module_generator.service.gen_service.GenUtils.init_table'),
    ):
        with pytest.raises(ServiceException):
            await GenTableService.import_gen_table_services(db, [_table()], _user())
        db.rollback.assert_awaited()

    # edit success / missing / rollback
    edit = EditGenTableModel(
        tableId=1,
        tableName='sys_demo',
        columns=[_column()],
        params=GenTableParamsModel(treeCode='id'),
        updateBy='u',
    )
    with (
        patch.object(
            GenTableService,
            'get_gen_table_by_id_services',
            new=AsyncMock(return_value=_table(tableId=1)),
        ),
        patch.object(GenTableDao, 'edit_gen_table_dao', new=AsyncMock()),
        patch.object(GenTableColumnDao, 'edit_gen_table_column_dao', new=AsyncMock()),
    ):
        assert (await GenTableService.edit_gen_table_services(db, edit)).is_success

    with patch.object(
        GenTableService,
        'get_gen_table_by_id_services',
        new=AsyncMock(return_value=_table(tableId=None)),
    ):
        with pytest.raises(ServiceException):
            await GenTableService.edit_gen_table_services(db, edit)

    with (
        patch.object(
            GenTableService,
            'get_gen_table_by_id_services',
            new=AsyncMock(return_value=_table(tableId=1)),
        ),
        patch.object(GenTableDao, 'edit_gen_table_dao', new=AsyncMock(side_effect=ValueError('e'))),
    ):
        with pytest.raises(ValueError):
            await GenTableService.edit_gen_table_services(db, edit)
        db.rollback.assert_awaited()

    # delete
    with (
        patch.object(GenTableDao, 'delete_gen_table_dao', new=AsyncMock()),
        patch.object(GenTableColumnDao, 'delete_gen_table_column_by_table_id_dao', new=AsyncMock()),
    ):
        assert (
            await GenTableService.delete_gen_table_services(db, DeleteGenTableModel(tableIds='1,2'))
        ).is_success

    with patch.object(GenTableDao, 'delete_gen_table_dao', new=AsyncMock(side_effect=RuntimeError('x'))):
        with pytest.raises(RuntimeError):
            await GenTableService.delete_gen_table_services(db, DeleteGenTableModel(tableIds='1'))

    with pytest.raises(ServiceException):
        await GenTableService.delete_gen_table_services(db, DeleteGenTableModel(tableIds=''))


@pytest.mark.asyncio
async def test_gen_table_service_get_create_preview_generate() -> None:
    db = AsyncMock()
    raw_table = {'tableId': 1, 'tableName': 'sys_demo', 'options': json.dumps({
        GenConstant.TREE_CODE: 'id',
        GenConstant.TREE_PARENT_CODE: 'pid',
        GenConstant.TREE_NAME: 'name',
        GenConstant.PARENT_MENU_ID: 1,
        GenConstant.PARENT_MENU_NAME: 'menu',
    }), 'columns': []}

    with (
        patch.object(GenTableDao, 'get_gen_table_by_id', new=AsyncMock(return_value=SimpleNamespace())),
        patch(
            'module_generator.service.gen_service.CamelCaseUtil.transform_result',
            return_value=raw_table,
        ),
    ):
        got = await GenTableService.get_gen_table_by_id_services(db, 1)
        assert got.tree_code == 'id'
        assert got.parent_menu_name == 'menu'

    with (
        patch.object(GenTableDao, 'get_gen_table_all', new=AsyncMock(return_value=[SimpleNamespace()])),
        patch(
            'module_generator.service.gen_service.CamelCaseUtil.transform_result',
            return_value=[{'tableName': 't', 'tableComment': 'c'}],
        ),
    ):
        assert len(await GenTableService.get_gen_table_all_services(db)) == 1

    # create table valid / invalid / exception
    create_expr = MagicMock(spec=Create)
    create_expr.find.return_value = SimpleNamespace(name='sys_demo')
    with (
        patch('module_generator.service.gen_service.sqlglot_parse', return_value=[create_expr]),
        patch.object(GenTableDao, 'create_table_by_sql_dao', new=AsyncMock()),
        patch.object(
            GenTableService,
            'get_gen_db_table_list_by_name_services',
            new=AsyncMock(return_value=[_table()]),
        ),
        patch.object(
            GenTableService,
            'import_gen_table_services',
            new=AsyncMock(return_value=SimpleNamespace(is_success=True)),
        ),
    ):
        assert (await GenTableService.create_table_services(db, 'create table sys_demo(id int)', _user())).is_success

    with patch('module_generator.service.gen_service.sqlglot_parse', return_value=[]):
        with pytest.raises(ServiceException) as exc_invalid:
            await GenTableService.create_table_services(db, 'drop table x', _user())
        assert '不合法' in (exc_invalid.value.message or '')

    with (
        patch('module_generator.service.gen_service.sqlglot_parse', return_value=[create_expr]),
        patch.object(GenTableDao, 'create_table_by_sql_dao', new=AsyncMock(side_effect=RuntimeError('bad'))),
    ):
        with pytest.raises(ServiceException) as exc_create:
            await GenTableService.create_table_services(db, 'create table t(id int)', _user())
        assert '异常' in (exc_create.value.message or '')

    assert GenTableService._GenTableService__is_valid_create_table([create_expr]) is True
    bad = MagicMock()
    # forbidden keyword type
    from sqlglot.expressions import Drop

    drop = MagicMock(spec=Drop)
    assert GenTableService._GenTableService__is_valid_create_table([drop]) is False
    assert GenTableService._GenTableService__get_table_names([create_expr]) == ['sys_demo']

    # preview / generate / batch
    env = MagicMock()
    env.get_template.return_value.render.return_value = 'CODE'
    table = _table(genPath='/')
    with (
        patch.object(GenTableDao, 'get_gen_table_by_id', new=AsyncMock(return_value=SimpleNamespace())),
        patch(
            'module_generator.service.gen_service.CamelCaseUtil.transform_result',
            return_value=table.model_dump(by_alias=True),
        ),
        patch.object(GenTableService, 'set_sub_table', new=AsyncMock()),
        patch.object(GenTableService, 'set_pk_column', new=AsyncMock()),
        patch('module_generator.service.gen_service.TemplateInitializer.init_jinja2', return_value=env),
        patch('module_generator.service.gen_service.TemplateUtils.prepare_context', return_value={}),
        patch(
            'module_generator.service.gen_service.TemplateUtils.get_template_list',
            return_value=['python/service.py.j2'],
        ),
    ):
        preview = await GenTableService.preview_code_services(db, 1)
        assert preview['python/service.py.j2'] == 'CODE'

    render_info = [
        ['python/service.py.j2'],
        ['out/service.py'],
        {},
        _table(genPath='/'),
    ]
    with (
        patch('module_generator.service.gen_service.TemplateInitializer.init_jinja2', return_value=env),
        patch.object(GenTableService, '_GenTableService__get_gen_render_info', new=AsyncMock(return_value=render_info)),
        patch('module_generator.service.gen_service.TemplateUtils.get_file_name', return_value='a.py'),
        patch('module_generator.service.gen_service.aiofiles.open') as aio_open,
        patch('module_generator.service.gen_service.os.makedirs'),
        patch('module_generator.service.gen_service.GenConfig.GEN_PATH', '/tmp/gen'),
    ):
        cm = AsyncMock()
        cm.__aenter__.return_value = AsyncMock(write=AsyncMock())
        cm.__aexit__.return_value = None
        aio_open.return_value = cm
        assert (await GenTableService.generate_code_services(db, 'sys_demo')).is_success

    with (
        patch('module_generator.service.gen_service.TemplateInitializer.init_jinja2', return_value=env),
        patch.object(
            GenTableService,
            '_GenTableService__get_gen_render_info',
            new=AsyncMock(return_value=render_info),
        ),
        patch('module_generator.service.gen_service.aiofiles.open', side_effect=OSError('disk')),
        patch('module_generator.service.gen_service.os.makedirs'),
        patch('module_generator.service.gen_service.TemplateUtils.get_file_name', return_value='a.py'),
        patch('module_generator.service.gen_service.GenConfig.GEN_PATH', '/tmp/gen'),
    ):
        with pytest.raises(ServiceException) as exc_gen:
            await GenTableService.generate_code_services(db, 'sys_demo')
        assert '渲染模板失败' in (exc_gen.value.message or '')

    with (
        patch('module_generator.service.gen_service.TemplateInitializer.init_jinja2', return_value=env),
        patch.object(
            GenTableService,
            '_GenTableService__get_gen_render_info',
            new=AsyncMock(return_value=render_info),
        ),
    ):
        data = await GenTableService.batch_gen_code_services(db, ['sys_demo'])
        assert isinstance(data, (bytes, bytearray)) and len(data) > 0

    # __get_gen_render_info + __get_gen_path
    with (
        patch.object(GenTableDao, 'get_gen_table_by_name', new=AsyncMock(return_value=SimpleNamespace())),
        patch(
            'module_generator.service.gen_service.CamelCaseUtil.transform_result',
            return_value=_table(genPath='/custom').model_dump(by_alias=True),
        ),
        patch.object(GenTableService, 'set_sub_table', new=AsyncMock()),
        patch.object(GenTableService, 'set_pk_column', new=AsyncMock()),
        patch('module_generator.service.gen_service.TemplateUtils.prepare_context', return_value={'a': 1}),
        patch(
            'module_generator.service.gen_service.TemplateUtils.get_template_list',
            return_value=['t.j2'],
        ),
        patch('module_generator.service.gen_service.TemplateUtils.get_file_name', return_value='f.py'),
    ):
        info = await GenTableService._GenTableService__get_gen_render_info(db, 'sys_demo')
        assert info[0] == ['t.j2'] and info[2] == {'a': 1}

    with (
        patch('module_generator.service.gen_service.TemplateUtils.get_file_name', return_value='f.py'),
        patch('module_generator.service.gen_service.GenConfig.GEN_PATH', '/tmp/gen'),
    ):
        p1 = GenTableService._GenTableService__get_gen_path(_table(genPath='/'), 't.j2')
        assert 'f.py' in p1
        p2 = GenTableService._GenTableService__get_gen_path(_table(genPath='/out'), 't.j2')
        assert p2.replace('\\', '/').endswith('/out/f.py') or 'out' in p2


@pytest.mark.asyncio
async def test_gen_table_service_sync_and_helpers() -> None:
    db = AsyncMock()
    existing = _column(columnId=10, columnName='id', isList='1', isRequired='1', isPk='0', isInsert='1', isEdit='1')
    # force usable/super true for preserve-required branch
    object.__setattr__(existing, 'list', True)
    object.__setattr__(existing, 'pk', False)
    object.__setattr__(existing, 'insert', True)
    object.__setattr__(existing, 'edit', True)
    object.__setattr__(existing, 'usable_column', True)
    object.__setattr__(existing, 'super_column', False)
    object.__setattr__(existing, 'dict_type', 'sys_yes')
    object.__setattr__(existing, 'query_type', 'EQ')
    object.__setattr__(existing, 'html_type', 'input')

    stale = _column(columnId=99, columnName='old_col')
    table = _table(columns=[existing, stale])

    db_cols = [
        {
            'columnName': 'id',
            'pythonField': 'id',
            'isPk': '0',
            'isList': '1',
            'isInsert': '1',
            'isEdit': '1',
            'isRequired': '0',
        },
        {'columnName': 'name', 'pythonField': 'name', 'isPk': '0'},
    ]

    with (
        patch.object(GenTableDao, 'get_gen_table_by_name', new=AsyncMock(return_value=SimpleNamespace())),
        patch(
            'module_generator.service.gen_service.CamelCaseUtil.transform_result',
            side_effect=[table.model_dump(by_alias=True), db_cols],
        ),
        patch.object(
            GenTableColumnDao,
            'get_gen_db_table_columns_by_name',
            new=AsyncMock(return_value=[SimpleNamespace(), SimpleNamespace()]),
        ),
        patch('module_generator.service.gen_service.GenUtils.init_column_field'),
        patch.object(GenTableColumnDao, 'edit_gen_table_column_dao', new=AsyncMock()),
        patch.object(GenTableColumnDao, 'add_gen_table_column_dao', new=AsyncMock()),
        patch.object(GenTableColumnDao, 'delete_gen_table_column_by_column_id_dao', new=AsyncMock()),
    ):
        # patch GenTableColumnModel construction to keep usable flags after sync rebuild
        real_model = GenTableColumnModel

        def _col_factory(**kw):
            m = real_model(**kw)
            if m.column_name == 'id':
                object.__setattr__(m, 'list', True)
                object.__setattr__(m, 'pk', False)
                object.__setattr__(m, 'insert', True)
                object.__setattr__(m, 'edit', True)
                object.__setattr__(m, 'usable_column', True)
                object.__setattr__(m, 'super_column', False)
            return m

        with patch('module_generator.service.gen_service.GenTableColumnModel', side_effect=_col_factory):
            # also need GenTableModel from first transform
            with patch(
                'module_generator.service.gen_service.GenTableModel',
                side_effect=lambda **kw: table if 'tableName' in kw or 'table_name' in kw or True else _table(**kw),
            ):
                # simpler: patch transform to return ready models via custom path
                pass

    # Rework sync test more directly by patching models after transform
    with (
        patch.object(GenTableDao, 'get_gen_table_by_name', new=AsyncMock(return_value=SimpleNamespace())),
        patch(
            'module_generator.service.gen_service.CamelCaseUtil.transform_result',
            side_effect=[
                {
                    'tableId': 1,
                    'tableName': 'sys_demo',
                    'columns': [
                        {
                            'columnId': 10,
                            'columnName': 'id',
                            'pythonField': 'id',
                            'isPk': '0',
                            'isList': '1',
                            'isRequired': '1',
                            'isInsert': '1',
                            'isEdit': '1',
                            'dictType': 'sys_yes',
                            'queryType': 'EQ',
                            'htmlType': 'input',
                        },
                        {'columnId': 99, 'columnName': 'old_col', 'pythonField': 'oldCol'},
                    ],
                },
                [
                    {
                        'columnName': 'id',
                        'pythonField': 'parentId',
                        'isPk': '0',
                        'isList': '1',
                        'isInsert': '1',
                        'isEdit': '1',
                        'isRequired': '0',
                    },
                    {'columnName': 'name', 'pythonField': 'name', 'isPk': '0'},
                ],
            ],
        ),
        patch.object(
            GenTableColumnDao,
            'get_gen_db_table_columns_by_name',
            new=AsyncMock(return_value=[1, 2]),
        ),
        patch('module_generator.service.gen_service.GenUtils.init_column_field'),
        patch.object(GenTableColumnDao, 'edit_gen_table_column_dao', new=AsyncMock()) as edit_col,
        patch.object(GenTableColumnDao, 'add_gen_table_column_dao', new=AsyncMock()) as add_col,
        patch.object(
            GenTableColumnDao,
            'delete_gen_table_column_by_column_id_dao',
            new=AsyncMock(),
        ) as del_col,
    ):
        result = await GenTableService.sync_db_services(db, 'sys_demo')
        assert result.is_success is True
        assert edit_col.await_count >= 1
        assert add_col.await_count >= 1
        assert del_col.await_count >= 1

    with (
        patch.object(GenTableDao, 'get_gen_table_by_name', new=AsyncMock(return_value=SimpleNamespace())),
        patch(
            'module_generator.service.gen_service.CamelCaseUtil.transform_result',
            side_effect=[{'tableName': 't', 'columns': []}, []],
        ),
        patch.object(
            GenTableColumnDao,
            'get_gen_db_table_columns_by_name',
            new=AsyncMock(return_value=[]),
        ),
    ):
        with pytest.raises(ServiceException) as exc_sync:
            await GenTableService.sync_db_services(db, 'missing')
        assert '原表结构不存在' in (
            (exc_sync.value.message or '') + (exc_sync.value.data or '')
        )

    with (
        patch.object(GenTableDao, 'get_gen_table_by_name', new=AsyncMock(return_value=SimpleNamespace())),
        patch(
            'module_generator.service.gen_service.CamelCaseUtil.transform_result',
            side_effect=[
                {'tableName': 't', 'columns': [{'columnName': 'id', 'pythonField': 'id', 'columnId': 1}]},
                [{'columnName': 'id', 'pythonField': 'id'}],
            ],
        ),
        patch.object(
            GenTableColumnDao,
            'get_gen_db_table_columns_by_name',
            new=AsyncMock(return_value=[1]),
        ),
        patch('module_generator.service.gen_service.GenUtils.init_column_field'),
        patch.object(
            GenTableColumnDao,
            'edit_gen_table_column_dao',
            new=AsyncMock(side_effect=RuntimeError('sync fail')),
        ),
    ):
        with pytest.raises(RuntimeError):
            await GenTableService.sync_db_services(db, 't')
        db.rollback.assert_awaited()

    # set_sub_table / set_pk_column / set_table_from_options / validate_edit
    gt = _table(subTableName='sub_t', columns=[_column(isPk='0'), _column(columnName='pk', isPk='1')])
    with (
        patch.object(GenTableDao, 'get_gen_table_by_name', new=AsyncMock(return_value=SimpleNamespace())),
        patch(
            'module_generator.service.gen_service.CamelCaseUtil.transform_result',
            return_value={'tableName': 'sub_t', 'columns': [{'columnName': 'id', 'pythonField': 'id', 'isPk': '1'}]},
        ),
    ):
        await GenTableService.set_sub_table(db, gt)
        assert gt.sub_table is not None and gt.sub_table.table_name == 'sub_t'

    await GenTableService.set_sub_table(db, _table(subTableName=None))

    no_pk = _table(columns=[_column(isPk='0'), _column(columnName='name', pythonField='name', isPk='0')])
    await GenTableService.set_pk_column(no_pk)
    assert no_pk.pk_column.column_name == 'id'

    with_pk = _table(columns=[_column(isPk='0'), _column(columnName='pk', pythonField='pk', isPk='1')])
    await GenTableService.set_pk_column(with_pk)
    assert with_pk.pk_column.column_name == 'pk'

    sub_table = _table(
        tplCategory=GenConstant.TPL_SUB,
        columns=[_column()],
        subTable=_table(columns=[_column(isPk='0'), _column(columnName='sid', pythonField='sid', isPk='1')]),
    )
    # GenTableModel validator sets sub based on tpl_category; ensure sub_table present
    sub_table.sub_table = _table(
        columns=[_column(isPk='0'), _column(columnName='sid', pythonField='sid', isPk='1')]
    )
    object.__setattr__(sub_table, 'tpl_category', GenConstant.TPL_SUB)
    await GenTableService.set_pk_column(sub_table)
    assert sub_table.sub_table.pk_column is not None

    # sub without pk falls through — empty pk loop, columns not None so skip dead branch
    sub_nopk = _table(tplCategory=GenConstant.TPL_SUB, columns=[_column()])
    object.__setattr__(sub_nopk, 'tpl_category', GenConstant.TPL_SUB)
    sub_nopk.sub_table = _table(columns=[_column(isPk='0')])
    await GenTableService.set_pk_column(sub_nopk)

    bare = await GenTableService.set_table_from_options(_table(options=None))
    assert bare.tree_code is None
    bare2 = await GenTableService.set_table_from_options(_table(options='{}'))
    assert bare2.tree_code is None

    # validate_edit tree — keys must be absent from model_dump (None keys still present)
    await GenTableService.validate_edit(EditGenTableModel(tplCategory=GenConstant.TPL_CRUD))

    def _tree_edit(dump: dict) -> EditGenTableModel:
        p = MagicMock()
        p.model_dump.return_value = dump
        return EditGenTableModel.model_construct(tpl_category=GenConstant.TPL_TREE, params=p)

    with pytest.raises(ServiceException) as e1:
        await GenTableService.validate_edit(_tree_edit({}))
    assert '树编码' in (e1.value.message or '')
    with pytest.raises(ServiceException) as e2:
        await GenTableService.validate_edit(_tree_edit({GenConstant.TREE_CODE: 'a'}))
    assert '树父编码' in (e2.value.message or '')
    with pytest.raises(ServiceException) as e3:
        await GenTableService.validate_edit(
            _tree_edit({GenConstant.TREE_CODE: 'a', GenConstant.TREE_PARENT_CODE: 'b'})
        )
    assert '树名称' in (e3.value.message or '')
    await GenTableService.validate_edit(
        _tree_edit(
            {
                GenConstant.TREE_CODE: 'a',
                GenConstant.TREE_PARENT_CODE: 'b',
                GenConstant.TREE_NAME: 'c',
            }
        )
    )

    with (
        patch.object(
            GenTableColumnDao,
            'get_gen_table_column_list_by_table_id',
            new=AsyncMock(return_value=[SimpleNamespace()]),
        ),
        patch(
            'module_generator.service.gen_service.CamelCaseUtil.transform_result',
            return_value=[{'columnName': 'id', 'pythonField': 'id', 'isPk': '1'}],
        ),
    ):
        cols = await GenTableColumnService.get_gen_table_column_list_by_table_id_services(db, 1)
        assert cols[0].column_name == 'id'
