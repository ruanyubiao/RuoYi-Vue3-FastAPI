"""前端 H7 轮询 / H6 连接对话框契约（读 Vue/JS，无 vitest）。"""

from __future__ import annotations

from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
_FE = _REPO / 'ruoyi-fastapi-frontend' / 'src'
_IO_PANEL = _FE / 'components' / 'Payload' / 'IoLogPanel.vue'
_XFER = _FE / 'components' / 'Payload' / 'PayloadTransferInfo.vue'
_TM_TABLE = _FE / 'components' / 'Payload' / 'PayloadTelemetryTable.vue'
_IO_POLL = _FE / 'utils' / 'useIoLogPoll.js'
_CAMERA = _FE / 'views' / 'payload' / 'board' / 'camera' / 'index.vue'
_BOARD = _FE / 'views' / 'payload' / 'board' / 'XlBoardPage.vue'
_CAN_DLG = _FE / 'components' / 'Payload' / 'CanConnectDialog.vue'
_UDP_DLG = _FE / 'components' / 'Payload' / 'UdpConnectDialog.vue'
_SERIAL_DLG = _FE / 'components' / 'Payload' / 'SerialConnectDialog.vue'


def test_tm_table_pauses_poll_on_keep_alive() -> None:
    text = _TM_TABLE.read_text(encoding='utf-8')
    assert 'onDeactivated' in text and 'stopPoll' in text
    assert 'onActivated' in text and 'startPoll' in text
    assert 'pollMs: { type: Number, default: 1000 }' in text


def test_io_panels_pause_and_resume_poll() -> None:
    io = _IO_PANEL.read_text(encoding='utf-8')
    xfer = _XFER.read_text(encoding='utf-8')
    poll = _IO_POLL.read_text(encoding='utf-8')
    assert 'useIoLogPoll' in io and 'useIoLogPoll' in xfer
    assert 'onDeactivated(stopPoll)' in io and 'onDeactivated(stopPoll)' in xfer
    assert 'onActivated' in io and 'startPoll' in io
    assert 'onActivated' in xfer and 'startPoll' in xfer
    # H7：默认 1s；启动抖动 50–500；stop 清 timeout+interval
    assert 'pollMs: { type: Number, default: 1000 }' in io
    assert 'pollMs: { type: Number, default: 1000 }' in xfer
    assert '1000' in poll
    assert '50' in poll and '500' in poll
    assert 'clearTimeout' in poll
    assert 'clearInterval' in poll
    assert 'setInterval(pullOnce' not in io
    assert 'setInterval(pullOnce' not in xfer


def test_link_status_poll_composable_pauses() -> None:
    text = (_FE / 'utils' / 'useLinkStatusPoll.js').read_text(encoding='utf-8')
    assert 'onDeactivated' in text
    assert 'onActivated' in text
    assert 'onUnmounted' in text
    assert 'clearInterval' in text
    assert '2000' in text
    cam = _CAMERA.read_text(encoding='utf-8')
    board = _BOARD.read_text(encoding='utf-8')
    for text in (cam, board):
        assert 'useLinkStatusPoll' in text
        assert 'setInterval(checkLinkStatus, 2000)' not in text
        assert "from '@/utils/useLinkStatusPoll'" in text


def test_connect_dialogs_reuse_label_and_already_open() -> None:
    """使用|打开、already_open、allowReuse；列表加载走 composable。"""
    for path in (_CAN_DLG, _UDP_DLG, _SERIAL_DLG):
        text = path.read_text(encoding='utf-8')
        assert 'useConnectPipelineOptions' in text
        assert 'confirmOpenLabel' in text
        assert 'allowReuse' in text
        assert 'isAlreadyOpen' in text or 'already_open' in text


def test_can_udp_dialogs_load_parsers_via_composable() -> None:
    can = _CAN_DLG.read_text(encoding='utf-8')
    udp = _UDP_DLG.read_text(encoding='utf-8')
    assert 'async function loadParsers' not in can
    assert 'async function loadParsers' not in udp
    assert 'loadParserOptions' in can and 'loadAssemblerOptions' in can
    assert 'loadParserOptions' in udp and 'loadAssemblerOptions' in udp
