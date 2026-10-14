"""前端组装器/解析器 ID 与 cfg_device_connect、constants 对齐。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from module_payload import constants as c
from module_payload.constants import PARSER_NONE
from module_payload.protocol.protocol_catalog import CAN_BUS_FAMILIES
from module_payload.protocol.registry import CAMERA_IMAGE_ASSEMBLER_IDS

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
_CFG = _BACKEND / 'assets' / 'config' / 'cfg_device_connect.json'
_JS = _REPO / 'ruoyi-fastapi-frontend' / 'src' / 'utils' / 'pipelineIds.js'
_SIMULATE = _REPO / 'ruoyi-fastapi-frontend' / 'src' / 'views' / 'payload' / 'debug' / 'simulate' / 'index.vue'
_IO_PANEL = _REPO / 'ruoyi-fastapi-frontend' / 'src' / 'components' / 'Payload' / 'IoLogPanel.vue'
_XFER = _REPO / 'ruoyi-fastapi-frontend' / 'src' / 'components' / 'Payload' / 'PayloadTransferInfo.vue'
_FILE_CURVE = _REPO / 'ruoyi-fastapi-frontend' / 'src' / 'views' / 'payload' / 'telemetry' / 'fileCurve' / 'index.vue'
_TM_TABLE = _REPO / 'ruoyi-fastapi-frontend' / 'src' / 'components' / 'Payload' / 'PayloadTelemetryTable.vue'

_BUS_ASSEMBLERS = {row.assembler_id for row in CAN_BUS_FAMILIES}
_BUS_PARSERS = {row.parser_id for row in CAN_BUS_FAMILIES}
_PY_ASSEMBLERS = {
    c.ASSEMBLER_PASSTHROUGH,
    c.ASSEMBLER_ENG_TM_SUBPKT,
} | _BUS_ASSEMBLERS | CAMERA_IMAGE_ASSEMBLER_IDS
_PY_PARSERS = {
    c.PARSER_TM_XL_CAMERA,
    c.PARSER_TM_XL_CAMERA_V17,
    c.PARSER_TM_XL_BOARD,
    c.PARSER_TM_XL_CPAZX,
} | _BUS_PARSERS


def test_bus_rows_derive_existing_ids() -> None:
    """总线行只登记族名；推出来的 id、配置文件名、gpcan 名与协议包路径和改造前一致。"""
    got = {
        row.family: (
            row.storage_prefix,
            row.assembler_id,
            row.parser_id,
            row.parser_name,
            row.telecontrol_cfg,
            row.telemetry_cfg,
            row.gpcan_protocol,
            row.telecontrol_protocol,
            row.module,
        )
        for row in CAN_BUS_FAMILIES
    }
    assert got == {
        'biu': (
            'BIU',
            'can_biu',
            'tm_can_biu',
            'BIU-CAN遥测复合帧',
            'BIU-TeleControlCfg.json',
            'BIU-TeleMetryCfg.json',
            'BIU',
            'can_biu',
            'module_payload.protocol.biu.can',
        ),
        'xl': (
            'XL',
            'can_xl',
            'tm_can_xl',
            'XL-CAN遥测复合帧',
            'XL-TeleControlCfg.json',
            'XL-TeleMetryCfg.json',
            'XL',
            'can_xl',
            'module_payload.protocol.xl.can',
        ),
        'yj216': (
            'YJ216',
            'can_yj216',
            'tm_can_yj216',
            'YJ216-CAN实时遥测',
            'YJ216-TeleControlCfg.json',
            'YJ216-TeleMetryCfg.json',
            'YJ216',
            'can_yj216',
            'module_payload.protocol.yj216.can',
        ),
    }


def test_cfg_device_connect_pipeline_ids() -> None:
    cfg = json.loads(_CFG.read_text(encoding='utf-8'))
    for key, entry in cfg.items():
        if key == 'datetime' or not isinstance(entry, dict):
            continue
        aid = str(entry.get('assemblerId') or '').strip()
        pid = str(entry.get('parserId') or '').strip()
        if aid:
            assert aid in _PY_ASSEMBLERS, f'{key}.assemblerId={aid}'
        if pid and pid != PARSER_NONE:
            assert pid in _PY_PARSERS, f'{key}.parserId={pid}'


def test_pipeline_ids_js_matches_constants() -> None:
    text = _JS.read_text(encoding='utf-8')
    exported = dict(re.findall(r"export const (ASSEMBLER_\w+|PARSER_\w+) = '([^']+)'", text))
    assert exported['ASSEMBLER_PASSTHROUGH'] == c.ASSEMBLER_PASSTHROUGH
    assert exported['ASSEMBLER_ENG_TM_SUBPKT'] == c.ASSEMBLER_ENG_TM_SUBPKT
    assert exported['ASSEMBLER_CAMERA_IMAGE_D6'] == c.ASSEMBLER_CAMERA_IMAGE_D6
    assert exported['ASSEMBLER_CAMERA_IMAGE_D6_V17'] == c.ASSEMBLER_CAMERA_IMAGE_D6_V17
    js_ids = set(exported.values())
    assert _BUS_ASSEMBLERS <= js_ids, sorted(_BUS_ASSEMBLERS - js_ids)
    assert _BUS_PARSERS <= js_ids, sorted(_BUS_PARSERS - js_ids)
    assert exported['PARSER_TM_XL_CAMERA'] == c.PARSER_TM_XL_CAMERA
    assert exported['PARSER_TM_XL_CAMERA_V17'] == c.PARSER_TM_XL_CAMERA_V17
    assert exported['PARSER_TM_XL_BOARD'] == c.PARSER_TM_XL_BOARD
    assert exported['PARSER_TM_XL_CPAZX'] == c.PARSER_TM_XL_CPAZX


def test_simulate_uses_bytes_to_hex() -> None:
    text = _SIMULATE.read_text(encoding='utf-8')
    assert 'function formatHex' not in text
    assert 'bytesToHex' in text
    assert "from '@/utils/payloadRawData'" in text


def test_io_panels_share_poll_composable() -> None:
    io = _IO_PANEL.read_text(encoding='utf-8')
    xfer = _XFER.read_text(encoding='utf-8')
    assert 'useIoLogPoll' in io
    assert 'useIoLogPoll' in xfer
    assert 'setInterval(pullOnce' not in io
    assert 'setInterval(pullOnce' not in xfer


def test_telemetry_watch_not_deep() -> None:
    curve = _FILE_CURVE.read_text(encoding='utf-8')
    table = _TM_TABLE.read_text(encoding='utf-8')
    assert 'watch(curves,' not in curve or 'deep: true' not in curve
    assert not re.search(r'watch\(\s*\(\)\s*=>\s*props\.externalSnap[\s\S]{0,120}deep:\s*true', table)
