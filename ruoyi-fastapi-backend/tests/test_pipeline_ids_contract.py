"""前端组装器/解析器 ID 与 cfg_device_connect、constants 对齐。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from module_payload import constants as c

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
_CFG = _BACKEND / 'assets' / 'config' / 'cfg_device_connect.json'
_JS = _REPO / 'ruoyi-fastapi-frontend' / 'src' / 'utils' / 'pipelineIds.js'
_SIMULATE = _REPO / 'ruoyi-fastapi-frontend' / 'src' / 'views' / 'payload' / 'debug' / 'simulate' / 'index.vue'
_IO_PANEL = _REPO / 'ruoyi-fastapi-frontend' / 'src' / 'components' / 'Payload' / 'IoLogPanel.vue'
_XFER = _REPO / 'ruoyi-fastapi-frontend' / 'src' / 'components' / 'Payload' / 'PayloadTransferInfo.vue'
_FILE_CURVE = _REPO / 'ruoyi-fastapi-frontend' / 'src' / 'views' / 'payload' / 'telemetry' / 'fileCurve' / 'index.vue'
_TM_TABLE = _REPO / 'ruoyi-fastapi-frontend' / 'src' / 'components' / 'Payload' / 'PayloadTelemetryTable.vue'

_PY_ASSEMBLERS = {
    c.ASSEMBLER_PASSTHROUGH,
    c.ASSEMBLER_ENG_TM_SUBPKT,
    c.ASSEMBLER_CAMERA_IMAGE_D6,
    c.ASSEMBLER_CAN_BIU,
    c.ASSEMBLER_CAN_XL,
}
_PY_PARSERS = {
    c.PARSER_TM_CAN_BIU,
    c.PARSER_TM_CAN_XL,
    c.PARSER_CAMERA_SC_LINK41EP,
    c.PARSER_XL_BOARD_TM,
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
        if pid:
            assert pid in _PY_PARSERS, f'{key}.parserId={pid}'


def test_pipeline_ids_js_matches_constants() -> None:
    text = _JS.read_text(encoding='utf-8')
    exported = dict(re.findall(r"export const (ASSEMBLER_\w+|PARSER_\w+) = '([^']+)'", text))
    assert exported['ASSEMBLER_PASSTHROUGH'] == c.ASSEMBLER_PASSTHROUGH
    assert exported['ASSEMBLER_ENG_TM_SUBPKT'] == c.ASSEMBLER_ENG_TM_SUBPKT
    assert exported['ASSEMBLER_CAMERA_IMAGE_D6'] == c.ASSEMBLER_CAMERA_IMAGE_D6
    assert exported['ASSEMBLER_CAN_BIU'] == c.ASSEMBLER_CAN_BIU
    assert exported['ASSEMBLER_CAN_XL'] == c.ASSEMBLER_CAN_XL
    assert exported['PARSER_TM_CAN_BIU'] == c.PARSER_TM_CAN_BIU
    assert exported['PARSER_TM_CAN_XL'] == c.PARSER_TM_CAN_XL
    assert exported['PARSER_CAMERA_SC_LINK41EP'] == c.PARSER_CAMERA_SC_LINK41EP
    assert exported['PARSER_XL_BOARD_TM'] == c.PARSER_XL_BOARD_TM


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
