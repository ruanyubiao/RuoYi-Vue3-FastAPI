"""遥测字段工具与解释器注册表。"""

from __future__ import annotations

from types import SimpleNamespace

from module_payload.constants import PARSER_TM_CAN_BIU, PARSER_TM_CAN_XL, PARSER_TM_XL_BOARD, PARSER_TM_XL_CAMERA
from module_payload.parsers import list_parsers, resolve_parser
from module_payload.parsers.tm_field_util import curve_numeric, line_to_field_dict


class _Num:
    def __init__(self, v):
        self._v = v

    def value(self):
        return self._v


def test_line_to_field_dict_prefers_calc_val() -> None:
    ln = SimpleNamespace(
        id='J1',
        name='电压',
        val=_Num(10),
        calc_val=12.5,
        show='12.5V',
        hex='0A',
        unit='V',
    )
    d = line_to_field_dict(ln)
    assert d['value'] == 10
    assert d['calc_val'] == 12.5
    assert d['unit'] == 'V'
    d2 = line_to_field_dict(ln, unit='A')
    assert d2['unit'] == 'A'


def test_curve_numeric_priority() -> None:
    assert curve_numeric({'calc_val': 1.5, 'value': 9, 'show': 'x'}) == 1.5
    assert curve_numeric({'value': '2.0'}) == 2.0
    assert curve_numeric({'show': '3'}) == 3.0
    assert curve_numeric({'calc_val': '', 'value': None, 'show': 'nope'}) is None
    assert curve_numeric({}) is None


def test_parser_registry() -> None:
    ids = {p['id'] for p in list_parsers()}
    assert ids == {PARSER_TM_CAN_BIU, PARSER_TM_CAN_XL, PARSER_TM_XL_CAMERA, PARSER_TM_XL_BOARD}
    assert resolve_parser(None) is None
    assert resolve_parser('') is None
    assert resolve_parser('nope') is None
    assert resolve_parser(PARSER_TM_CAN_BIU) is not None
    assert resolve_parser(PARSER_TM_XL_CAMERA) is not None
