"""调试-时间转换的协议纪元清单：与 gpcan 常量和总线目录保持一致。"""

from __future__ import annotations

import importlib

import pytest

pytest.importorskip('gpcan')

from module_payload.protocol.protocol_catalog import CAN_BUS_FAMILIES
from module_payload.service.payload_timeconv_service import PayloadTimeconvService, epoch_utc_seconds


def test_list_epochs_covers_none_and_every_catalog_family() -> None:
    items = PayloadTimeconvService.list_epochs()
    assert [item['id'] for item in items] == [
        'none',
        *(row.family for row in CAN_BUS_FAMILIES),
    ]


@pytest.mark.parametrize('protocol', ['none', *(row.family for row in CAN_BUS_FAMILIES)])
def test_epoch_matches_gpcan_constant_and_label(protocol: str) -> None:
    item = next(
        row for row in PayloadTimeconvService.list_epochs() if row['id'] == protocol
    )
    expected = int(importlib.import_module(f'gpcan.protocol.{protocol}.defs').EPOCH_UTC)
    assert item['epochUtcSec'] == expected
    assert item['epochUtcSec'] == epoch_utc_seconds(protocol)
    assert item['dateUtc'] in item['label']
    assert item['dateUtc'].count('-') == 2


def test_known_epoch_labels_are_derived_from_seconds() -> None:
    items = {item['id']: item for item in PayloadTimeconvService.list_epochs()}
    assert items['none']['label'] == 'NONE: 1970-01-01'
    assert items['biu']['label'] == 'BIU: 2020-01-01'
    assert items['xl']['label'] == 'XL: 2015-01-01'
    assert items['yj216']['label'] == 'YJ216: 2020-01-01'
