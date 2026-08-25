"""地检接口冒烟：读配置 / 组帧 / 指令序列 CRUD。不打开串口、CAN、硬件通道。"""

from __future__ import annotations

import json
import time
from typing import Any

import requests

from common.config import Config
from common.login_helper import LoginHelper

_TIMEOUT = 20


def _auth_headers() -> dict[str, str]:
    token = LoginHelper().login(username='admin', password='admin123')
    assert token is not None, '登录应该成功'
    return {'Authorization': f'Bearer {token}'}


def _get(path: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(
        f'{Config.backend_url}{path}',
        headers=headers,
        params=params,
        timeout=_TIMEOUT,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get('code') == 200, body
    return body


def _json(
    method: str,
    path: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = requests.request(
        method,
        f'{Config.backend_url}{path}',
        headers=headers,
        json=payload,
        timeout=_TIMEOUT,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get('code') == 200, body
    return body


def test_payload_device_catalogs() -> None:
    """设备目录类接口可登录访问（枚举端口/厂商，不 open）。"""
    headers = _auth_headers()
    version = _get('/payload/device/version', headers)
    assert version.get('data', {}).get('appVersion')

    parsers = _get('/payload/device/parsers', headers)
    assert isinstance(parsers.get('data'), list)
    assert parsers['data'], '应至少注册一个解释器'

    assemblers = _get('/payload/device/assemblers', headers)
    assert isinstance(assemblers.get('data'), list)
    assert assemblers['data'], '应至少注册一个组装器'

    vendors = _get('/payload/device/can/vendors', headers)
    vendor_list = (vendors.get('data') or {}).get('vendors') or []
    assert vendor_list, 'CAN 厂商列表不应为空'

    serials = _get('/payload/device/serial/list', headers)
    assert isinstance(serials.get('data'), list)

    sessions = _get('/payload/device/sessions', headers)
    assert isinstance(sessions.get('data'), list)

    defaults = _get('/payload/device/connect-defaults', headers)
    assert defaults.get('data') is not None


def test_payload_config_reads() -> None:
    """遥控/遥测/单板/相机/LVDS/配置文件只读接口。"""
    headers = _auth_headers()

    biu_tc = _get('/payload/telecontrol/config', headers, {'family': 'biu'})
    biu_data = biu_tc.get('data') or {}
    assert biu_data.get('family') == 'biu'
    assert biu_data.get('order'), 'BIU 遥控配置应有指令'

    xl_tc = _get('/payload/telecontrol/config', headers, {'family': 'xl'})
    assert (xl_tc.get('data') or {}).get('order'), 'XL 遥控配置应有指令'

    tm_biu = _get('/payload/telemetry/config', headers, {'family': 'biu'})
    tm_pages = (tm_biu.get('data') or {}).get('page') or []
    assert tm_pages, 'BIU 遥测表列表不应为空'
    table_type = str(tm_pages[0].get('key') or '')
    assert table_type
    table_def = _get('/payload/telemetry/def', headers, {'type': table_type, 'family': 'biu'})
    rows = (table_def.get('data') or {}).get('row') or []
    assert rows, f'遥测表 {table_type} 应有字段定义'

    cam_tc = _get('/payload/camera/telecontrol/config', headers)
    assert (cam_tc.get('data') or {}).get('order')
    cam_tm = _get('/payload/camera/telemetry/config', headers)
    assert (cam_tm.get('data') or {}).get('page')

    rkdj = _get('/payload/board/rkdj/telecontrol/config', headers)
    assert (rkdj.get('data') or {}).get('order')
    zk = _get('/payload/board/zk/telemetry/config', headers)
    assert zk.get('data') is not None

    signals = _get('/payload/lvds/signals', headers)
    assert isinstance(signals.get('data'), list)

    files = _get('/payload/config-files/list', headers)
    assert isinstance(files.get('data'), list)
    assert files['data'], '配置文件列表不应为空'


def test_telecontrol_assemble_without_send() -> None:
    """组帧接口不依赖硬件；不下发。"""
    headers = _auth_headers()
    cfg = _get('/payload/telecontrol/config', headers, {'family': 'biu'}).get('data') or {}
    order_map = cfg.get('order') or {}
    order_id = next(iter(order_map), None)
    if not order_id:
        for page in cfg.get('page') or []:
            for oid in page.get('orderList') or []:
                order_id = oid
                break
            if order_id:
                break
    assert order_id, 'BIU 遥控配置中找不到指令代号'

    order = _get(f'/payload/telecontrol/order/{order_id}', headers).get('data') or {}
    assembled = _json(
        'POST',
        '/payload/telecontrol/assemble',
        headers,
        {
            'orderId': order_id,
            'components': order.get('component') or [],
            'family': 'biu',
        },
    )
    hex_text = (assembled.get('data') or {}).get('hex') or ''
    assert hex_text.strip(), f'指令 {order_id} 组帧应返回 hex'


def test_telemetry_calc_and_history() -> None:
    """遥测计算走 Redis 历史，不连采集设备。"""
    headers = _auth_headers()
    pages = (_get('/payload/telemetry/config', headers, {'family': 'biu'}).get('data') or {}).get('page') or []
    assert pages
    table_type = str(pages[0].get('key') or '')
    table_def = _get('/payload/telemetry/def', headers, {'type': table_type, 'family': 'biu'}).get('data') or {}
    field_id = ''
    for row in table_def.get('row') or []:
        if row.get('id'):
            field_id = str(row['id'])
            break
    assert field_id, f'遥测表 {table_type} 无字段 id'

    calc = _json(
        'POST',
        '/payload/telemetry/calc',
        headers,
        {'type': table_type, 'field': field_id, 'hex': '00', 'padTail': True},
    )
    assert calc.get('data') is not None
    history = _get('/payload/telemetry/calc/history', headers)
    assert isinstance(history.get('data'), list)


def test_sequence_crud_without_run() -> None:
    """指令序列增改查删、复制草稿；不执行、不连 CAN。"""
    headers = _auth_headers()
    name = f'e2e-seq-{int(time.time())}'
    commands = json.dumps(
        {
            'defaultInterval': 2000,
            'items': [{'name': '测试帧', 'hex': '0A 91 00 04', 'interval': -1}],
        },
        ensure_ascii=False,
    )
    created = _json(
        'POST',
        '/payload/sequence',
        headers,
        {
            'seqName': name,
            'project': 'biu',
            'commands': commands,
            'status': '0',
            'remark': 'e2e',
        },
    )
    seq_id = (created.get('data') or {}).get('seqId')
    assert seq_id, created

    listed = _get(
        '/payload/sequence/list',
        headers,
        {'pageNum': 1, 'pageSize': 10, 'seqName': name},
    )
    rows = listed.get('rows') or []
    assert any(row.get('seqId') == seq_id for row in rows), listed

    detail = _get(f'/payload/sequence/{seq_id}', headers).get('data') or {}
    assert detail.get('seqName') == name

    _json(
        'PUT',
        '/payload/sequence',
        headers,
        {
            'seqId': seq_id,
            'seqName': f'{name}-edit',
            'project': 'biu',
            'commands': commands,
            'status': '0',
            'remark': 'e2e-edit',
        },
    )
    after_edit = _get(f'/payload/sequence/{seq_id}', headers).get('data') or {}
    assert after_edit.get('seqName') == f'{name}-edit'

    draft = _json('POST', f'/payload/sequence/{seq_id}/copy', headers).get('data') or {}
    assert str(draft.get('seqName') or '').endswith('副本')
    assert draft.get('seqId') in (None, '')

    deleted = requests.delete(
        f'{Config.backend_url}/payload/sequence/{seq_id}',
        headers=headers,
        timeout=_TIMEOUT,
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json().get('code') == 200, deleted.text
