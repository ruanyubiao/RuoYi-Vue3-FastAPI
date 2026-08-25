"""打开连接 VO：fullDuplex 驼峰别名、网口无 net: 前缀。"""

from __future__ import annotations

from module_payload.entity.vo.payload_device_vo import (
    CanOpenModel,
    NetOpenModel,
    SerialOpenModel,
)
from module_payload.entity.vo.payload_telemetry_vo import TelemetryTableBatchItemModel


def test_serial_open_full_duplex_alias() -> None:
    body = SerialOpenModel.model_validate(
        {'port': 'COM4', 'source': 'camera_ctrl', 'fullDuplex': True}
    )
    assert body.full_duplex is True
    assert body.source == 'camera_ctrl'
    snake = SerialOpenModel(port='COM3', full_duplex=False)
    assert snake.full_duplex is False


def test_can_open_full_duplex_default_none() -> None:
    body = CanOpenModel.model_validate({'vendor': 3, 'devIndex': 0, 'canIndex': 1})
    assert body.full_duplex is None
    assert body.assembler_id == 'can_biu'


def test_net_open_model() -> None:
    body = NetOpenModel.model_validate(
        {
            'proto': 'udp',
            'localHost': '127.0.0.1',
            'localPort': 9000,
            'fullDuplex': False,
            'source': 'home',
        }
    )
    assert body.local_port == 9000
    assert body.full_duplex is False
    from module_payload import redis_keys as rk

    assert rk.net_id(body.proto, body.local_host, body.local_port) == 'udp:127.0.0.1:9000'


def test_telemetry_batch_data_id_str() -> None:
    item = TelemetryTableBatchItemModel.model_validate({'type': 'FF', 'dataId': 12, 'needCfg': True})
    assert item.data_id_str() == '12'
    empty = TelemetryTableBatchItemModel(type='D8')
    assert empty.data_id_str() is None
    blank = TelemetryTableBatchItemModel.model_validate({'type': 'D8', 'dataId': ''})
    assert blank.data_id_str() is None
