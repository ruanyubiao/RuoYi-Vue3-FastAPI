"""地检 /payload/* 接口冒烟：登录后打无硬件副作用的读/安全写。

断言 HTTP 200 + 业务 code==200，并检查关键字段。
模拟页样例：注入后拉遥测表，与 tm_golden_cases 解析结果逐字段比对。

明确跳过（需硬件或改盘/解析文件）：
  设备 can/open|close|cable、serial/open|close、net/open|close、bind-parser
  遥控 /telecontrol/send、/raw/can/send、/control/op
  序列 /{seqId}/run
  相机/单板 telecontrol/send、camera/start|stop
  PUT /config-files/content
  POST /telemetry/file/upload|parse，以及依赖已解析文件的 file/frame|curve
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from common.config import Config
from common.login_helper import LoginHelper

_TIMEOUT = 30
_DUMMY_DEVICE = 'can:0:0:0'
_TABLE_ENVELOPE = ('type', 'changed', 'srcParam', 'cfgDatetime', 'cfgMtime')

# 模拟页通用发送：有黄金样例的组装器+解析器组合
_SIMULATE_PIPELINES: tuple[tuple[str, str], ...] = (
    ('passthrough', 'tm_xl_camera'),
    ('passthrough', 'tm_xl_camera_v17'),
    ('passthrough', 'tm_can_biu'),
    ('passthrough', 'tm_can_xl'),
    ('passthrough', 'tm_xl_board'),
    ('eng_tm_subpkt', 'tm_xl_board'),
)

_GOLDEN_CASES_PATH = (
    Path(__file__).resolve().parents[2]
    / 'ruoyi-fastapi-backend'
    / 'assets'
    / 'data'
    / 'tm_golden_cases.json'
)
_GOLDEN_CASES: dict[str, Any] | None = None


def _gpcan_sdk_available() -> bool:
    """本机是否已安装且可枚举 CAN 厂商（与 E2E 后端同一 Python 环境时有效）。"""
    try:
        from gpcan import CanSdkClient

        return bool(CanSdkClient.get_supported_device_list())
    except Exception:
        return False


def _auth_headers() -> dict[str, str]:
    token = LoginHelper().login(username='admin', password='admin123')
    assert token is not None, '登录应该成功'
    return {'Authorization': f'Bearer {token}'}


def _url(path: str) -> str:
    return f'{Config.backend_url}{path}'


def _expect_ok(response: requests.Response, hint: str) -> dict[str, Any]:
    """HTTP 200 且业务 code==200；失败时带 path/body。"""
    assert response.status_code == 200, f'{hint} HTTP={response.status_code} body={response.text[:800]}'
    body = response.json()
    assert body.get('code') == 200, f'{hint} code={body.get("code")} body={body}'
    return body


def _get(path: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(_url(path), headers=headers, params=params, timeout=_TIMEOUT)
    return _expect_ok(response, f'GET {path}')


def _json(
    method: str,
    path: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = requests.request(
        method,
        _url(path),
        headers=headers,
        json=payload,
        params=params,
        timeout=_TIMEOUT,
    )
    return _expect_ok(response, f'{method} {path}')


def _delete(path: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.delete(_url(path), headers=headers, params=params, timeout=_TIMEOUT)
    return _expect_ok(response, f'DELETE {path}')


def _first_order_id(cfg: dict[str, Any]) -> str:
    order_map = cfg.get('order') or {}
    order_id = next(iter(order_map), None)
    if order_id:
        return str(order_id)
    for page in cfg.get('page') or []:
        for oid in page.get('orderList') or []:
            if oid:
                return str(oid)
    raise AssertionError(f'配置中找不到指令代号 keys={list(cfg.keys())}')


def _first_table_and_field(headers: dict[str, str]) -> tuple[str, str]:
    pages = (_get('/payload/telemetry/config', headers, {'family': 'biu'}).get('data') or {}).get('page') or []
    assert pages, 'BIU 遥测表列表不应为空'
    table_type = str(pages[0].get('key') or '')
    assert table_type
    table_def = _get('/payload/telemetry/def', headers, {'type': table_type, 'family': 'biu'}).get('data') or {}
    field_id = ''
    for row in table_def.get('row') or []:
        if row.get('id'):
            field_id = str(row['id'])
            break
    assert field_id, f'遥测表 {table_type} 无字段 id'
    return table_type, field_id


def _assert_table_envelope(item: dict[str, Any], hint: str) -> None:
    assert isinstance(item, dict), hint
    for key in _TABLE_ENVELOPE:
        assert key in item, f'{hint} 缺 {key}: {item}'
    assert isinstance(item['changed'], bool), hint
    assert isinstance(item.get('srcParam') or '', str), hint


def _load_golden_cases() -> dict[str, Any]:
    global _GOLDEN_CASES
    if _GOLDEN_CASES is None:
        assert _GOLDEN_CASES_PATH.is_file(), f'缺少黄金样例文件: {_GOLDEN_CASES_PATH}'
        _GOLDEN_CASES = json.loads(_GOLDEN_CASES_PATH.read_text(encoding='utf-8'))
    return _GOLDEN_CASES


def _expected_parse_from_golden(key: str) -> tuple[str, list[dict[str, Any]]]:
    """从本地 tm_golden_cases 取期望表类型与 fields（API /dev/sample 会剥掉 fields）。"""
    obj = _load_golden_cases().get(key) or {}
    result = obj.get('result') if isinstance(obj.get('result'), dict) else {}
    fields = result.get('fields')
    table_key = result.get('table_key')
    if not isinstance(fields, list):
        inner = result.get('inner_board') if isinstance(result.get('inner_board'), dict) else {}
        fields = inner.get('fields')
        table_key = inner.get('table_key') or table_key
    assert isinstance(fields, list) and fields, f'黄金样例 {key} 无解析 fields'
    assert table_key, f'黄金样例 {key} 无 table_key'
    return str(table_key), fields


def _values_close(a: Any, b: Any) -> bool:
    """展示值或数值容差相等（浮点 JSON/解析精度差）。"""
    if a == b:
        return True
    if str(a) == str(b):
        return True
    try:
        fa = float(a)
        fb = float(b)
    except (TypeError, ValueError):
        return False
    scale = max(1.0, abs(fa), abs(fb))
    return abs(fa - fb) <= 1e-6 * scale


def _norm_hex(text: Any) -> str:
    return ''.join(str(text or '').split()).upper()


def _assert_table_matches_golden(
    table_item: dict[str, Any],
    *,
    expect_type: str,
    expect_fields: list[dict[str, Any]],
    hint: str,
) -> None:
    """遥测表 rows 与黄金样例 fields 逐 id 比对 show/value/hex。"""
    got_type = str(table_item.get('type') or '').upper()
    exp_type = str(expect_type or '').upper()
    assert got_type == exp_type, f'{hint} type 期望={exp_type} 实际={got_type}'
    assert table_item.get('dataId') not in (None, ''), f'{hint} dataId 为空'
    rows = table_item.get('rows')
    assert isinstance(rows, list) and rows, f'{hint} rows 为空: {table_item}'
    by_id = {str(r.get('id') or ''): r for r in rows if r.get('id')}
    missing: list[str] = []
    mismatches: list[str] = []
    for field in expect_fields:
        fid = str(field.get('id') or '')
        if not fid:
            continue
        got = by_id.get(fid)
        if not got:
            missing.append(fid)
            continue
        exp_show = field.get('show')
        got_show = got.get('show')
        if str(exp_show) != str(got_show):
            mismatches.append(f'{fid}.show 期望={exp_show!r} 实际={got_show!r}')
        if not _values_close(field.get('value'), got.get('value')):
            mismatches.append(
                f'{fid}.value 期望={field.get("value")!r} 实际={got.get("value")!r}'
            )
        exp_hex = field.get('hex')
        if exp_hex not in (None, '') and _norm_hex(exp_hex) != _norm_hex(got.get('hex')):
            mismatches.append(f'{fid}.hex 期望={exp_hex!r} 实际={got.get("hex")!r}')
    assert not missing, f'{hint} 缺字段 {missing[:20]}{"..." if len(missing) > 20 else ""}'
    assert not mismatches, (
        f'{hint} 字段不一致({len(mismatches)}): ' + '; '.join(mismatches[:15])
    )


def _discover_simulate_cases(headers: dict[str, str]) -> list[tuple[str, str, str, str]]:
    """按模拟页 samples API 发现存在样例的 (assembler, parser, key, label)。

    同解析器下将 *_multi 排到对应单帧之前，便于回归 mux 隔离。
    """
    cases: list[tuple[str, str, str, str]] = []
    for assembler_id, parser_id in _SIMULATE_PIPELINES:
        listed = _get(
            '/payload/telemetry/dev/samples',
            headers,
            {'assemblerId': assembler_id, 'parserId': parser_id},
        )
        items = (listed.get('data') or {}).get('items') or []
        assert isinstance(items, list), listed
        bucket: list[tuple[str, str, str, str]] = []
        for item in items:
            key = str(item.get('key') or '').strip()
            if not key:
                continue
            label = str(item.get('label') or key)
            bucket.append((assembler_id, parser_id, key, label))
        bucket.sort(key=lambda row: (0 if '_multi' in row[2] else 1, row[2]))
        cases.extend(bucket)
    return cases


def test_simulate_pipeline_then_telemetry_table() -> None:
    """模拟页：发现样例 → 取 HEX → pipeline 注入 → 拉遥测表，与黄金解析结果比对。"""
    headers = _auth_headers()
    cases = _discover_simulate_cases(headers)
    assert cases, '未发现任何模拟黄金样例（检查 /dev/samples 与 tm_golden_cases.json）'

    failures: list[str] = []
    for assembler_id, parser_id, key, label in cases:
        hint = f'{key} ({assembler_id}+{parser_id}, {label})'
        try:
            expect_type, expect_fields = _expected_parse_from_golden(key)
            sample = _get('/payload/telemetry/dev/sample', headers, {'key': key}).get('data') or {}
            hex_text = str(sample.get('hex') or '').strip()
            assert hex_text, f'{hint} /dev/sample 无 hex'

            injected = _json(
                'POST',
                '/payload/telemetry/dev/pipeline',
                headers,
                {
                    'hex': hex_text,
                    'assemblerId': assembler_id,
                    'parserId': parser_id,
                },
            )
            inj = injected.get('data') or {}
            data_type = str(inj.get('dataType') or '').strip()
            assert data_type, f'{hint} pipeline 未返回 dataType: {inj}'
            assert int(inj.get('parsedCount') or 0) >= 1, f'{hint} parsedCount={inj.get("parsedCount")}'
            assert str(data_type).upper() == str(expect_type).upper(), (
                f'{hint} dataType={data_type} 与黄金 table_key={expect_type} 不一致'
            )

            table_body = _get(
                '/payload/telemetry/table',
                headers,
                {'type': data_type, 'needCfg': False, 'source': 'live'},
            )
            item = table_body.get('data') or {}
            assert item.get('changed') is True or item.get('rows'), (
                f'{hint} 表未下发行: changed={item.get("changed")} dataId={item.get("dataId")}'
            )
            _assert_table_matches_golden(
                item,
                expect_type=expect_type,
                expect_fields=expect_fields,
                hint=hint,
            )
        except AssertionError as exc:
            failures.append(f'{hint}: {exc}')

    assert not failures, (
        f'模拟注入→遥测表比对失败 {len(failures)}/{len(cases)} 条:\n'
        + '\n'.join(failures)
    )


def test_telemetry_dev_pipeline() -> None:
    """保留轻量入口：相机样例列表非空（完整比对见 test_simulate_pipeline_then_telemetry_table）。"""
    headers = _auth_headers()
    listed = _get(
        '/payload/telemetry/dev/samples',
        headers,
        {'assemblerId': 'passthrough', 'parserId': 'tm_xl_camera'},
    )
    sample_items = (listed.get('data') or {}).get('items') or []
    assert isinstance(sample_items, list)
    assert sample_items, '相机黄金样本列表不应为空'


def test_payload_device_catalogs() -> None:
    """设备目录/快照/空状态；不 open。"""
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
    assert isinstance(vendor_list, list)
    if _gpcan_sdk_available():
        assert vendor_list, '已安装 gpcan 时 CAN 厂商列表不应为空'

    can_list = _get('/payload/device/can/list', headers)
    assert isinstance(can_list.get('data'), list)

    serials = _get('/payload/device/serial/list', headers)
    assert isinstance(serials.get('data'), list)

    opened = _get('/payload/device/serial/opened', headers)
    assert isinstance(opened.get('data'), list)

    addrs = _get('/payload/device/net/addresses', headers)
    assert isinstance(addrs.get('data'), list)

    net_opened = _get('/payload/device/net/opened', headers)
    assert isinstance(net_opened.get('data'), list)

    sessions = _get('/payload/device/sessions', headers)
    assert isinstance(sessions.get('data'), list)

    defaults = _get('/payload/device/connect-defaults', headers)
    assert defaults.get('data') is not None

    snap = _get(
        '/payload/device/snapshot',
        headers,
        {'parts': 'can,serialList,serialOpened,netOpened,sessions,parsers,assemblers'},
    )
    snap_data = snap.get('data') or {}
    for key in ('can', 'serialList', 'serialOpened', 'netOpened', 'sessions', 'parsers', 'assemblers'):
        assert key in snap_data, snap_data

    st = _get('/payload/device/status', headers, {'deviceId': _DUMMY_DEVICE})
    st_data = st.get('data') or {}
    assert st_data.get('deviceId') == _DUMMY_DEVICE
    assert 'connected' in st_data

    io_log = _get('/payload/device/io-log', headers, {'deviceId': _DUMMY_DEVICE})
    io_data = io_log.get('data') or {}
    assert io_data.get('deviceId') == _DUMMY_DEVICE
    assert isinstance(io_data.get('items'), list)

    cleared = _delete('/payload/device/io-log', headers, {'deviceId': _DUMMY_DEVICE})
    assert (cleared.get('data') or {}).get('cleared') is True

    closed = _json('POST', '/payload/device/close-all', headers)
    close_data = closed.get('data') or {}
    assert 'ok' in close_data and 'fail' in close_data
    assert isinstance(close_data.get('closed'), list)


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
    order_id = _first_order_id(cfg)

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


def test_telecontrol_history_empty() -> None:
    """无会话时发送历史可空；清空不依赖硬件。"""
    headers = _auth_headers()
    hist = _get('/payload/telecontrol/history', headers, {'deviceId': _DUMMY_DEVICE})
    assert isinstance(hist.get('data'), list)
    _delete('/payload/telecontrol/history', headers, {'deviceId': _DUMMY_DEVICE})


def test_telemetry_calc_and_history() -> None:
    """遥测计算走 Redis 历史，不连采集设备。"""
    headers = _auth_headers()
    table_type, field_id = _first_table_and_field(headers)

    calc = _json(
        'POST',
        '/payload/telemetry/calc',
        headers,
        {'type': table_type, 'field': field_id, 'hex': '00', 'padTail': True},
    )
    assert calc.get('data') is not None
    history = _get('/payload/telemetry/calc/history', headers)
    assert isinstance(history.get('data'), list)
    _delete('/payload/telemetry/calc/history', headers)
    after = _get('/payload/telemetry/calc/history', headers)
    assert after.get('data') == []


def test_telemetry_table_and_curves() -> None:
    """table/batch 瘦信封 + 实时曲线；无热层时结构仍合法。"""
    headers = _auth_headers()
    table_type, field_id = _first_table_and_field(headers)

    one = _get(
        '/payload/telemetry/table',
        headers,
        {'type': table_type, 'needCfg': True, 'source': 'live'},
    )
    item = one.get('data') or {}
    _assert_table_envelope(item, 'GET /table')
    assert str(item.get('type') or '').upper() == table_type.upper()

    batch = _json(
        'POST',
        '/payload/telemetry/table/batch',
        headers,
        {'items': [{'type': table_type, 'needCfg': False, 'source': 'live'}]},
    )
    items = (batch.get('data') or {}).get('items') or []
    assert len(items) == 1, batch
    _assert_table_envelope(items[0], 'POST /table/batch')

    fields = _get('/payload/telemetry/fields', headers, {'type': table_type, 'family': 'biu'})
    assert isinstance(fields.get('data'), list)
    assert fields['data']

    curve = _get(
        '/payload/telemetry/curve/data',
        headers,
        {'type': table_type, 'field': field_id, 'limit': 10},
    )
    curve_data = curve.get('data') or {}
    assert curve_data.get('type')
    assert curve_data.get('field') == field_id
    assert isinstance(curve_data.get('points'), list)

    batch_curve = _json(
        'POST',
        '/payload/telemetry/curve/data/batch',
        headers,
        {'items': [{'type': table_type, 'field': field_id, 'limit': 10}]},
    )
    batch_list = batch_curve.get('data')
    assert isinstance(batch_list, list) and batch_list
    assert isinstance(batch_list[0].get('points'), list)


def test_telemetry_archive_and_files() -> None:
    """空归档曲线/回放会话 + 文件浏览定位；不 upload/parse。"""
    headers = _auth_headers()
    table_type, field_id = _first_table_and_field(headers)

    hist_curve = _json(
        'POST',
        '/payload/telemetry/history/curve/batch',
        headers,
        {
            'items': [
                {
                    'type': table_type,
                    'field': field_id,
                    'startT': 1,
                    'endT': 2,
                    'limit': 10,
                }
            ]
        },
    )
    hist_items = hist_curve.get('data')
    assert isinstance(hist_items, list) and hist_items
    assert isinstance(hist_items[0].get('points'), list)

    opened = _json(
        'POST',
        '/payload/telemetry/history/frames/open',
        headers,
        {'type': table_type, 'start': '2020-01-01 00:00:00', 'end': '2020-01-01 00:00:01'},
    )
    meta = opened.get('data') or {}
    assert meta.get('session')
    assert int(meta.get('frameCount') or 0) == 0

    frame = _get(
        '/payload/telemetry/history/frames',
        headers,
        {'session': meta['session'], 'index': 1},
    )
    frame_data = frame.get('data') or {}
    assert frame_data.get('session') == meta['session']
    assert int(frame_data.get('frameCount') or 0) == 0

    browse = _get('/payload/telemetry/file/browse', headers, {'root': 'upload'})
    browse_data = browse.get('data') or {}
    assert browse_data.get('root') in ('upload', 'log_data', 'uploaddir')
    assert isinstance(browse_data.get('entries'), list)

    locate = _get('/payload/telemetry/file/locate', headers, {'path': ''})
    assert (locate.get('data') or {}).get('found') is False

    status = _get(
        '/payload/telemetry/file/status',
        headers,
        {'path': browse_data.get('absPath') or ''},
    )
    st = status.get('data') or {}
    assert 'status' in st
    assert 'frameCount' in st


def test_sequence_crud_without_run() -> None:
    """指令序列增改查删、复制草稿、执行历史；不执行、不连 CAN。"""
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

    runs = _get(f'/payload/sequence/{seq_id}/runs', headers)
    assert isinstance(runs.get('data'), list)

    missing = requests.get(
        _url('/payload/sequence/run/no-such-run-id'),
        headers=headers,
        timeout=_TIMEOUT,
    )
    assert missing.status_code == 200, missing.text
    missing_body = missing.json()
    assert missing_body.get('code') != 200, missing_body
    assert '不存在' in str(missing_body.get('msg') or '')

    deleted = requests.delete(
        _url(f'/payload/sequence/{seq_id}'),
        headers=headers,
        timeout=_TIMEOUT,
    )
    _expect_ok(deleted, f'DELETE /payload/sequence/{seq_id}')


def test_camera_config_assemble_status() -> None:
    """相机 v16/v17 配置、组帧、空串口图像/状态；不下发不 start。"""
    headers = _auth_headers()
    v16 = _get('/payload/camera/telecontrol/config', headers, {'protocol': 'v16'}).get('data') or {}
    assert v16.get('order')
    v17 = _get('/payload/camera/telecontrol/config', headers, {'protocol': 'v17'}).get('data') or {}
    assert v17.get('order')
    v17_tm = _get('/payload/camera/telemetry/config', headers, {'protocol': 'v17'}).get('data') or {}
    assert v17_tm.get('page')

    order_id = _first_order_id(v16)
    assembled = _json(
        'POST',
        '/payload/camera/telecontrol/assemble',
        headers,
        {'orderId': order_id, 'values': [], 'protocol': 'v16'},
    )
    hex_text = (assembled.get('data') or {}).get('hex') or ''
    assert hex_text.strip(), f'相机指令 {order_id} 组帧应返回 hex'

    image = _get('/payload/camera/image', headers, {'port': 'COM99'})
    img = image.get('data') or {}
    assert 'image' in img and 'status' in img
    assert img['status'].get('connected') is False

    cam_st = _get('/payload/camera/status', headers, {'port': 'COM99'})
    st = cam_st.get('data') or {}
    assert 'connected' in st
    assert st.get('deviceId')


def test_xl_board_config_assemble() -> None:
    """rkdj/zk/dj 遥控遥测配置 + 组帧。"""
    headers = _auth_headers()
    for board in ('rkdj', 'zk', 'dj'):
        tc = _get(f'/payload/board/{board}/telecontrol/config', headers).get('data') or {}
        assert tc.get('board') == board, tc
        assert tc.get('order'), f'{board} 遥控配置应有指令'
        tm = _get(f'/payload/board/{board}/telemetry/config', headers).get('data') or {}
        assert tm.get('board') == board, tm
        order_id = _first_order_id(tc)
        assembled = _json(
            'POST',
            f'/payload/board/{board}/telecontrol/assemble',
            headers,
            {'orderId': order_id, 'values': []},
        )
        hex_text = (assembled.get('data') or {}).get('hex') or ''
        assert hex_text.strip(), f'{board} 指令 {order_id} 组帧应返回 hex'


def test_lvds_data() -> None:
    """工程遥测信号 + 波形点（无 Redis 时走演示曲线）。"""
    headers = _auth_headers()
    signals = _get('/payload/lvds/signals', headers).get('data') or []
    assert isinstance(signals, list)
    if not signals:
        return
    sid = str(signals[0].get('id') or '')
    assert sid
    data = _get('/payload/lvds/data', headers, {'signal': sid}).get('data') or {}
    assert data.get('signal') == sid
    assert isinstance(data.get('points'), list)
    assert data['points']


def test_config_files_read_reload() -> None:
    """读配置原文/下载/导出指令/重载缓存；不 PUT 保存。"""
    headers = _auth_headers()
    files = _get('/payload/config-files/list', headers).get('data') or []
    assert files
    name = str(files[0].get('name') or '')
    assert name

    content = _get('/payload/config-files/content', headers, {'name': name})
    cdata = content.get('data') or {}
    assert cdata.get('name') == name
    assert isinstance(cdata.get('content'), str)
    assert cdata['content'].strip()

    dl = requests.get(
        _url('/payload/config-files/download'),
        headers=headers,
        params={'name': name},
        timeout=_TIMEOUT,
    )
    assert dl.status_code == 200, dl.text[:400]
    disp = dl.headers.get('Content-Disposition') or dl.headers.get('content-disposition') or ''
    ctype = dl.headers.get('Content-Type') or dl.headers.get('content-type') or ''
    assert 'json' in ctype.lower() or 'attachment' in disp.lower() or dl.content, (ctype, disp)

    tc_name = next(
        (str(f.get('name')) for f in files if str(f.get('name') or '').endswith('-TeleControlCfg.json')),
        'BIU-TeleControlCfg.json',
    )
    exported = _get('/payload/config-files/export-orders', headers, {'name': tc_name})
    rows = exported.get('data') or []
    assert isinstance(rows, list)
    assert rows, f'{tc_name} 导出指令不应为空'
    assert rows[0].get('hex')

    reloaded = _json('POST', '/payload/config-files/reload', headers, params={'name': name})
    rdata = reloaded.get('data') or {}
    assert rdata.get('name') == name
