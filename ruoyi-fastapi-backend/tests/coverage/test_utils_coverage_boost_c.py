"""Coverage boost for utils.template_util."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from common.constant import GenConstant
from exceptions.exception import ServiceWarning
from module_generator.entity.vo.gen_vo import GenTableColumnModel, GenTableModel
from utils.template_util import TemplateInitializer, TemplateUtils


def _col(**kwargs) -> GenTableColumnModel:
    defaults = dict(
        columnName='user_name',
        columnType='varchar(64)',
        columnComment='用户',
        pythonField='userName',
        pythonType='str',
        isPk='0',
        isList='1',
        dictType='',
        htmlType=GenConstant.HTML_INPUT,
    )
    defaults.update(kwargs)
    return GenTableColumnModel(**defaults)


def _table(**kwargs) -> GenTableModel:
    defaults = dict(
        tableName='sys_demo',
        tableComment='演示表',
        className='Demo',
        moduleName='system',
        businessName='demo',
        packageName='module_admin.system',
        functionName='演示',
        functionAuthor='tester',
        tplCategory=GenConstant.TPL_CRUD,
        options=json.dumps({GenConstant.PARENT_MENU_ID: '9'}),
        columns=[_col()],
        pkColumn=_col(columnName='id', pythonField='id', isPk='1'),
    )
    defaults.update(kwargs)
    return GenTableModel(**defaults)


def test_init_jinja2_success_and_failure() -> None:
    env = TemplateInitializer.init_jinja2()
    assert env is not None
    assert 'camel_to_snake' in env.filters
    assert 'get_sqlalchemy_type' in env.filters

    with patch('utils.template_util.get_package_root', side_effect=OSError('boom')):
        with pytest.raises(RuntimeError, match='初始化Jinja2'):
            TemplateInitializer.init_jinja2()


def test_prepare_context_requires_options_and_builds_crud() -> None:
    with pytest.raises(ServiceWarning):
        TemplateUtils.prepare_context(_table(options=None))

    ctx = TemplateUtils.prepare_context(_table(functionName=''))
    assert ctx['functionName'] == '【请填写功能名称】'
    assert ctx['parentMenuId'] == '9'
    assert ctx['permissionPrefix'] == 'system:demo'
    assert 'treeCode' not in ctx


def test_prepare_context_tree_and_sub() -> None:
    tree_opts = json.dumps(
        {
            GenConstant.PARENT_MENU_ID: '3',
            GenConstant.TREE_CODE: 'dept_id',
            GenConstant.TREE_PARENT_CODE: 'parent_id',
            GenConstant.TREE_NAME: 'dept_name',
        }
    )
    cols = [
        _col(columnName='dept_id', pythonField='deptId', isList='1'),
        _col(columnName='dept_name', pythonField='deptName', isList='1'),
    ]
    tree_table = _table(tplCategory=GenConstant.TPL_TREE, options=tree_opts, columns=cols)
    ctx = TemplateUtils.prepare_context(tree_table)
    assert ctx['treeCode'] == 'deptId'
    assert ctx['treeParentCode'] == 'parentId'
    assert ctx['treeName'] == 'deptName'
    assert ctx['expandColumn'] >= 1

    sub = _table(
        tableName='sys_item',
        className='Item',
        businessName='item',
        columns=[_col(columnName='item_id', pythonField='itemId', pythonType='int')],
    )
    main = _table(
        tplCategory=GenConstant.TPL_SUB,
        subTable=sub,
        subTableName='sys_item',
        subTableFkName='demo_id',
        columns=[_col()],
    )
    ctx2 = TemplateUtils.prepare_context(main)
    assert ctx2['subTableName'] == 'sys_item'
    assert ctx2['subTableFkClassName'] == 'DemoId'
    assert ctx2['subclassName'] == 'item'


def test_get_template_list_variants() -> None:
    crud = TemplateUtils.get_template_list(GenConstant.TPL_CRUD, 'element-ui')
    assert any(t.endswith('index.vue.jinja2') for t in crud)
    assert not any('index-tree' in t for t in crud)

    tree = TemplateUtils.get_template_list(GenConstant.TPL_TREE, 'element-plus')
    assert any('vue/v3/index-tree.vue.jinja2' in t for t in tree)

    sub = TemplateUtils.get_template_list(GenConstant.TPL_SUB, '')
    assert any(t.endswith('index.vue.jinja2') for t in sub)


def test_get_file_name_all_branches() -> None:
    table = _table()
    cases = [
        ('python/controller.py.jinja2', 'controller/demo_controller.py'),
        ('python/dao.py.jinja2', 'dao/demo_dao.py'),
        ('python/do.py.jinja2', 'entity/do/demo_do.py'),
        ('python/service.py.jinja2', 'service/demo_service.py'),
        ('python/vo.py.jinja2', 'entity/vo/demo_vo.py'),
        ('sql/sql.jinja2', 'sql/demo_menu.sql'),
        ('js/api.js.jinja2', 'api/system/demo.js'),
        ('vue/index.vue.jinja2', 'views/system/demo/index.vue'),
        ('vue/index-tree.vue.jinja2', 'views/system/demo/index.vue'),
        ('unknown.jinja2', ''),
    ]
    for template, expect_suffix in cases:
        name = TemplateUtils.get_file_name(template, table)
        if expect_suffix:
            assert expect_suffix in name
        else:
            assert name == ''


def test_package_prefix_permission_menu_tree_helpers() -> None:
    assert TemplateUtils.get_package_prefix('module_admin.system') == 'module_admin'
    assert TemplateUtils.get_permission_prefix('system', 'user') == 'system:user'
    assert TemplateUtils.get_parent_menu_id({}) == TemplateUtils.DEFAULT_PARENT_MENU_ID
    assert TemplateUtils.get_parent_menu_id({GenConstant.PARENT_MENU_ID: '12'}) == '12'
    assert TemplateUtils.get_tree_code({}) == ''
    assert TemplateUtils.get_tree_parent_code({}) == ''
    assert TemplateUtils.get_tree_name({}) == ''
    assert TemplateUtils.get_tree_code({GenConstant.TREE_CODE: 'a_b'}) == 'aB'
    assert TemplateUtils.get_tree_parent_code({GenConstant.TREE_PARENT_CODE: 'p_id'}) == 'pId'
    assert TemplateUtils.get_tree_name({GenConstant.TREE_NAME: 'dept_name'}) == 'deptName'
    assert TemplateUtils.to_camel_case('hello_world') == 'helloWorld'
    assert TemplateUtils.get_db_type('varchar(10)') == 'varchar'
    assert TemplateUtils.get_db_type('int') == 'int'


def test_vo_do_import_lists_and_merge() -> None:
    cols = [
        _col(pythonType='datetime', columnType='datetime'),
        _col(pythonType='Decimal', columnType='decimal(10,2)', pythonField='amount', columnName='amount'),
        _col(pythonType='date', columnType='date', pythonField='birth', columnName='birth'),
    ]
    sub_cols = [
        _col(pythonType='time', columnType='time', pythonField='t', columnName='t'),
        _col(pythonType='Decimal', columnType='decimal(8,2)', pythonField='price', columnName='price'),
    ]
    sub = _table(columns=sub_cols)
    table = _table(columns=cols, subTable=sub, tplCategory=GenConstant.TPL_SUB)

    vo = TemplateUtils.get_vo_import_list(table)
    assert any('datetime' in x or 'date' in x or 'time' in x for x in vo)
    assert any('Decimal' in x for x in vo)

    do = TemplateUtils.get_do_import_list(table)
    assert any('Column' in x for x in do)
    assert any('ForeignKey' in x for x in do)

    # geometry on main columns — type must match COLUMNTYPE_GEOMETRY entry
    geo_type = GenConstant.COLUMNTYPE_GEOMETRY[0]
    geo_table = _table(
        columns=[_col(columnType=geo_type, pythonType='str')],
        tplCategory=GenConstant.TPL_CRUD,
        subTable=None,
    )
    do_geo = TemplateUtils.get_do_import_list(geo_table)
    assert any('Geometry' in x for x in do_geo)

    merged = TemplateUtils.merge_same_imports(
        ['from datetime import date', 'from datetime import time', 'from decimal import Decimal'],
        'from datetime import',
    )
    assert any(x.startswith('from datetime import') and 'date' in x for x in merged)
    assert 'from decimal import Decimal' in merged

    empty_merge = TemplateUtils.merge_same_imports(['from x import y'], 'from datetime import')
    assert empty_merge == ['from x import y']


def test_dicts_and_expand_column() -> None:
    cols = [
        _col(
            columnName='status',
            pythonField='status',
            dictType='sys_status',
            htmlType=GenConstant.HTML_SELECT,
            isList='1',
        ),
        _col(
            columnName='flag',
            pythonField='flag',
            dictType='sys_flag',
            htmlType=GenConstant.HTML_CHECKBOX,
            isList='1',
        ),
        _col(columnName='plain', pythonField='plain', dictType='', htmlType=GenConstant.HTML_INPUT),
    ]
    sub = _table(
        columns=[
            _col(
                columnName='kind',
                pythonField='kind',
                dictType='sys_kind',
                htmlType=GenConstant.HTML_RADIO,
            )
        ]
    )
    table = _table(columns=cols, subTable=sub)
    dicts = TemplateUtils.get_dicts(table)
    assert "'sys_status'" in dicts
    assert "'sys_kind'" in dicts
    assert "'sys_flag'" in dicts

    tree_opts = json.dumps({GenConstant.TREE_NAME: 'status'})
    expand = TemplateUtils.get_expand_column(_table(options=tree_opts, columns=cols))
    assert expand >= 1

    expand2 = TemplateUtils.get_expand_column(
        _table(options=json.dumps({GenConstant.TREE_NAME: 'missing'}), columns=cols)
    )
    assert expand2 >= 1

    assert TemplateUtils.get_dicts(_table(columns=None, subTable=None)) == ''


def test_get_sqlalchemy_type_branches() -> None:
    sa_str = TemplateUtils.get_sqlalchemy_type('varchar(64)')
    assert sa_str
    assert '(' in sa_str

    sa_num = TemplateUtils.get_sqlalchemy_type('int(11)')
    assert sa_num

    sa_plain = TemplateUtils.get_sqlalchemy_type('datetime')
    assert sa_plain


def test_get_vo_import_without_sub() -> None:
    table = _table(
        columns=[_col(pythonType='str')],
        tplCategory=GenConstant.TPL_CRUD,
        subTable=None,
    )
    assert TemplateUtils.get_vo_import_list(table) == []
    assert TemplateUtils.get_vo_import_list(_table(columns=None, tplCategory=GenConstant.TPL_CRUD, subTable=None)) == []
