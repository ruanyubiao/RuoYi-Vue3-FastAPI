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
    assert 'getDeviceIoLog(deviceId, opts.lastSeq.value, 200' not in poll
    assert 'getDeviceIoLog(deviceId, opts.lastSeq.value, 1000' in poll


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


def test_io_log_payload_colored_by_direction() -> None:
    """收/发正文走 CSS 变量；light #008000/#0000FF，dark 更亮。"""
    io = _IO_PANEL.read_text(encoding='utf-8')
    xfer = _XFER.read_text(encoding='utf-8')
    raw = (_FE / 'utils' / 'payloadRawData.js').read_text(encoding='utf-8')
    theme = (_FE / 'assets' / 'styles' / 'variables.module.scss').read_text(encoding='utf-8')
    assert 'formatIoLogParts' in raw
    assert 'formatIoLogBlock' in raw
    assert '--payload-io-recv' in io and '--payload-io-send' in io
    assert '--payload-io-recv' in xfer and '--payload-io-send' in xfer
    assert 'io-recv' in io and 'io-send' in io
    assert 'io-meta' in io
    assert 'xfer-meta' in xfer
    assert '--payload-io-recv: #008000' in theme
    assert '--payload-io-send: #0000FF' in theme
    assert '--payload-io-recv: #5CFF6E' in theme
    assert '--payload-io-send: #7EB6FF' in theme


def test_io_log_panel_copy_clear_match_transfer_info() -> None:
    """数据收发 IO 区复制/清理与传输信息同为 link 文字按钮。"""
    io = _IO_PANEL.read_text(encoding='utf-8')
    xfer = _XFER.read_text(encoding='utf-8')
    for text in (io, xfer):
        assert 'copyLocal' in text
        assert 'clearLocal' in text
        assert 'link type="primary"' in text
        assert 'link type="danger"' in text
        assert 'class="xfer-actions"' in text


def test_io_log_panel_polls_stream_kind() -> None:
    """调试页读 :io:stream；相机/单板预览不带 kind=stream。"""
    io = _IO_PANEL.read_text(encoding='utf-8')
    xfer = _XFER.read_text(encoding='utf-8')
    poll = _IO_POLL.read_text(encoding='utf-8')
    assert "getKind: () => 'stream'" in io
    assert "clearDeviceIoLog(props.deviceId, 'stream')" in io
    assert 'getKind' in poll
    assert "getKind: () => 'stream'" not in xfer
    assert "clearDeviceIoLog(activeId.value, 'stream')" not in xfer
